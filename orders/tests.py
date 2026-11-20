from decimal import Decimal
from typing import cast

from django.core import mail
from django.core.mail import EmailMessage
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.test import APIClient, APITestCase

from catalog.models import Category, Product, ProductInfo, Shop
from orders.models import Order, OrderItem
from users.models import Contact, User


class BasketAPITests(APITestCase):
    """
    Проверяет API корзины пользователя.

    Создаёт тестовых пользователей, магазин и товарное
    предложение для проверки операций с корзиной.
    """

    client: APIClient

    def setUp(self) -> None:
        """
        Подготавливает данные для каждого теста.

        Создаёт покупателя, поставщика, магазин
        и товарное предложение с остатком 10 штук.

        Returns:
            None: Тестовые данные сохраняются в тестовой БД.
        """
        self.buyer = User.objects.create_user(
            email="buyer@test.example",
            password="test-password",
            type=User.UserType.BUYER,
            is_active=True,
        )

        supplier = User.objects.create_user(
            email="supplier@test.example",
            password="test-password",
            type=User.UserType.SHOP,
            is_active=True,
        )

        shop = Shop.objects.create(
            name="Тестовый магазин",
            user=supplier,
            state=True,
        )

        category = Category.objects.create(
            name="Электроника",
        )

        product = Product.objects.create(
            name="Тестовый телевизор",
            category=category,
        )

        self.product_info = ProductInfo.objects.create(
            product=product,
            shop=shop,
            external_id=1001,
            quantity=10,
            price=Decimal("1200.00"),
            price_rrc=Decimal("1500.00"),
        )

        # Авторизуем покупателя в тестовом API-клиенте.
        self.client.force_authenticate(
            user=self.buyer,
        )

    def test_add_product_to_basket(self) -> None:
        """
        Проверяет добавление товара в корзину.

        Отправляет POST-запрос и проверяет создание
        корзины, товарной позиции и расчёт суммы.

        Товар при добавлении в корзину не должен
        списываться со склада.

        Returns:
            None: Результаты проверяются утверждениями.
        """
        url = reverse("orders:basket")

        response = cast(
            Response,
            self.client.post(
                url,
                data={
                    "items": [
                        {
                            "product_info_id": self.product_info.pk,
                            "quantity": 2,
                        }
                    ]
                },
                format="json",
            ),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )

        # Проверяем, что API вернул JSON-объект.
        response_data = response.data
        assert isinstance(response_data, dict)

        # У покупателя должна появиться корзина.
        basket = Order.objects.get(
            user=self.buyer,
            state=Order.Status.BASKET,
        )

        # В корзине должна быть одна позиция.
        order_item = OrderItem.objects.get(
            order=basket,
            product_info=self.product_info,
        )

        self.assertEqual(
            order_item.quantity,
            2,
        )

        # Проверяем ответ API.
        self.assertEqual(
            response_data["total_sum"],
            "2400.00",
        )

        self.assertEqual(
            response_data["id"],
            basket.pk,
        )

        self.assertEqual(
            response_data["ordered_items"][0]["product_info_id"],
            self.product_info.pk,
        )

        # Добавление в корзину не списывает товар.
        self.product_info.refresh_from_db()

        self.assertEqual(
            self.product_info.quantity,
            10,
        )

    def test_add_existing_product_increases_quantity(self) -> None:
        """
        Проверяет повторное добавление товара в корзину.

        При повторном добавлении того же предложения
        увеличивается количество существующей позиции,
        а новая запись OrderItem не создаётся.

        Returns:
            None: Результаты проверяются утверждениями.
        """
        url = reverse("orders:basket")

        # Дважды добавляем одно товарное предложение.
        for quantity in (2, 3):
            response = cast(
                Response,
                self.client.post(
                    url,
                    data={
                        "items": [
                            {
                                "product_info_id": self.product_info.pk,
                                "quantity": quantity,
                            }
                        ]
                    },
                    format="json",
                ),
            )

            self.assertEqual(
                response.status_code,
                status.HTTP_200_OK,
                response.data,
            )

        # У покупателя должна быть только одна корзина.
        self.assertEqual(
            Order.objects.filter(
                user=self.buyer,
                state=Order.Status.BASKET,
            ).count(),
            1,
        )

        # Проверяем, что товарная позиция не дублируется.
        basket = Order.objects.get(
            user=self.buyer,
            state=Order.Status.BASKET,
        )

        self.assertEqual(
            OrderItem.objects.filter(order=basket).count(),
            1,
        )

        # Количество должно увеличиться до 5.
        order_item = OrderItem.objects.get(
            order=basket,
            product_info=self.product_info,
        )

        self.assertEqual(
            order_item.quantity,
            5,
        )

        # Проверяем сумму после повторного добавления.
        response_data = response.data

        assert isinstance(response_data, dict)

        self.assertEqual(
            response_data["total_sum"],
            "6000.00",
        )

        # Складские остатки не должны измениться.
        self.product_info.refresh_from_db()

        self.assertEqual(
            self.product_info.quantity,
            10,
        )

    def test_cannot_add_more_than_available_stock(self) -> None:
        """
        Проверяет запрет превышения складских остатков.

        Если суммарное количество товара в корзине
        превышает доступный остаток, API возвращает 400.

        При ошибке существующая корзина и складские
        остатки должны оставаться без изменений.

        Returns:
            None: Результаты проверяются утверждениями.
        """
        url = reverse("orders:basket")

        # Сначала успешно добавляем 2 товара.
        first_response = cast(
            Response,
            self.client.post(
                url,
                data={
                    "items": [
                        {
                            "product_info_id": self.product_info.pk,
                            "quantity": 2,
                        }
                    ]
                },
                format="json",
            ),
        )

        self.assertEqual(
            first_response.status_code,
            status.HTTP_200_OK,
        )

        # Пытаемся добавить ещё 9 товаров.
        # В сумме получится 11, хотя на складе только 10.
        response = cast(
            Response,
            self.client.post(
                url,
                data={
                    "items": [
                        {
                            "product_info_id": self.product_info.pk,
                            "quantity": 9,
                        }
                    ]
                },
                format="json",
            ),
        )

        # API должен отклонить запрос.
        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
            response.data,
        )

        # Корзина должна остаться единственной.
        baskets = Order.objects.filter(
            user=self.buyer,
            state=Order.Status.BASKET,
        )

        self.assertEqual(
            baskets.count(),
            1,
        )

        basket = baskets.get()

        # В корзине по-прежнему одна товарная позиция.
        self.assertEqual(
            OrderItem.objects.filter(order=basket).count(),
            1,
        )

        # Количество товара не должно увеличиться.
        order_item = OrderItem.objects.get(
            order=basket,
            product_info=self.product_info,
        )

        self.assertEqual(
            order_item.quantity,
            2,
        )

        # Ошибочная операция не затрагивает склад.
        self.product_info.refresh_from_db()

        self.assertEqual(
            self.product_info.quantity,
            10,
        )

    def test_update_and_remove_basket_item(self) -> None:
        """
        Проверяет изменение и удаление позиции корзины.

        Сначала устанавливает новое количество товара
        через PUT, затем удаляет позицию, передав
        quantity=0.

        Проверяет итоговую стоимость, содержимое
        корзины и сохранность складских остатков.

        Returns:
            None: Результаты проверяются утверждениями.
        """
        url = reverse("orders:basket")

        # Создаём корзину с двумя телевизорами.
        response = cast(
            Response,
            self.client.post(
                url,
                data={
                    "items": [
                        {
                            "product_info_id": self.product_info.pk,
                            "quantity": 2,
                        }
                    ]
                },
                format="json",
            ),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )

        basket = Order.objects.get(
            user=self.buyer,
            state=Order.Status.BASKET,
        )

        order_item = OrderItem.objects.get(
            order=basket,
            product_info=self.product_info,
        )

        # Устанавливаем количество равным 5.
        response = cast(
            Response,
            self.client.put(
                url,
                data={
                    "items": [
                        {
                            "order_item_id": order_item.pk,
                            "quantity": 5,
                        }
                    ]
                },
                format="json",
            ),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )

        order_item.refresh_from_db()

        # PUT устанавливает количество, а не прибавляет.
        self.assertEqual(
            order_item.quantity,
            5,
        )

        response_data = response.data
        assert isinstance(response_data, dict)

        self.assertEqual(
            response_data["total_sum"],
            "6000.00",
        )

        # Удаляем позицию, передав количество 0.
        response = cast(
            Response,
            self.client.put(
                url,
                data={
                    "items": [
                        {
                            "order_item_id": order_item.pk,
                            "quantity": 0,
                        }
                    ]
                },
                format="json",
            ),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )

        # Товарная позиция должна быть удалена.
        self.assertFalse(
            OrderItem.objects.filter(
                pk=order_item.pk,
            ).exists(),
        )

        # Сама корзина должна сохраниться.
        self.assertTrue(
            Order.objects.filter(
                pk=basket.pk,
                state=Order.Status.BASKET,
            ).exists(),
        )

        # Проверяем пустую корзину в ответе.
        response_data = response.data
        assert isinstance(response_data, dict)

        self.assertEqual(
            response_data["ordered_items"],
            [],
        )

        self.assertEqual(
            response_data["total_sum"],
            "0.00",
        )

        # Складские остатки не изменились.
        self.product_info.refresh_from_db()

        self.assertEqual(
            self.product_info.quantity,
            10,
        )

    def test_delete_selected_items_and_clear_basket(self) -> None:
        """
        Проверяет выборочное и полное удаление товаров.

        Создаёт корзину с двумя товарными предложениями.
        Сначала удаляет одну позицию по идентификатору,
        затем полностью очищает оставшуюся корзину.

        Проверяет количество удалённых позиций,
        сохранность корзины и складских остатков.

        Returns:
            None: Результаты проверяются утверждениями.
        """
        url = reverse("orders:basket")

        # Создаём второе товарное предложение.
        second_product_info = ProductInfo.objects.create(
            product=self.product_info.product,
            shop=self.product_info.shop,
            external_id=1002,
            quantity=7,
            price=Decimal("2000.00"),
            price_rrc=Decimal("2500.00"),
        )

        # Добавляем оба предложения в корзину.
        response = cast(
            Response,
            self.client.post(
                url,
                data={
                    "items": [
                        {
                            "product_info_id": self.product_info.pk,
                            "quantity": 2,
                        },
                        {
                            "product_info_id": second_product_info.pk,
                            "quantity": 3,
                        },
                    ]
                },
                format="json",
            ),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )

        basket = Order.objects.get(
            user=self.buyer,
            state=Order.Status.BASKET,
        )

        self.assertEqual(
            OrderItem.objects.filter(order=basket).count(),
            2,
        )

        first_item = OrderItem.objects.get(
            order=basket,
            product_info=self.product_info,
        )

        second_item = OrderItem.objects.get(
            order=basket,
            product_info=second_product_info,
        )

        # Удаляем только первую товарную позицию.
        response = cast(
            Response,
            self.client.delete(
                f"{url}?order_item_ids={first_item.pk}",
            ),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )

        response_data = response.data
        assert isinstance(response_data, dict)

        self.assertEqual(
            response_data["deleted"],
            1,
        )

        # Первая позиция удалена.
        self.assertFalse(
            OrderItem.objects.filter(
                pk=first_item.pk,
            ).exists(),
        )

        # Вторая позиция сохранилась.
        self.assertTrue(
            OrderItem.objects.filter(
                pk=second_item.pk,
                order=basket,
            ).exists(),
        )

        # Полностью очищаем корзину.
        response = cast(
            Response,
            self.client.delete(url),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )

        response_data = response.data
        assert isinstance(response_data, dict)

        self.assertEqual(
            response_data["deleted"],
            1,
        )

        # В корзине больше нет товаров.
        self.assertFalse(
            OrderItem.objects.filter(
                order=basket,
            ).exists(),
        )

        # Сама корзина остаётся в базе данных.
        self.assertTrue(
            Order.objects.filter(
                pk=basket.pk,
                state=Order.Status.BASKET,
            ).exists(),
        )

        # Проверяем остатки обоих предложений.
        first_product = ProductInfo.objects.get(
            pk=self.product_info.pk,
        )

        second_product = ProductInfo.objects.get(
            pk=second_product_info.pk,
        )

        self.assertEqual(first_product.quantity, 10)
        self.assertEqual(second_product.quantity, 7)

    def test_place_order_from_basket(self) -> None:
        """
        Проверяет успешное оформление заказа из корзины.

        Создаёт контакт доставки, добавляет товар
        в корзину и оформляет заказ через API.

        Проверяет статус заказа, списание остатков,
        сохранение цены и реквизитов доставки.

        Returns:
            None: Результаты проверяются утверждениями.
        """
        # Создаём контакт доставки покупателя.
        contact = Contact.objects.create(
            user=self.buyer,
            last_name="Иванов",
            first_name="Иван",
            email="buyer@test.example",
            phone="+79991234567",
            city="Москва",
            street="Тверская",
            house="10",
            apartment="25",
        )

        # Добавляем два телевизора в корзину.
        basket_response = cast(
            Response,
            self.client.post(
                reverse("orders:basket"),
                data={
                    "items": [
                        {
                            "product_info_id": self.product_info.pk,
                            "quantity": 2,
                        }
                    ]
                },
                format="json",
            ),
        )

        self.assertEqual(
            basket_response.status_code,
            status.HTTP_200_OK,
            basket_response.data,
        )

        basket = Order.objects.get(
            user=self.buyer,
            state=Order.Status.BASKET,
        )

        # Оформляем заказ с выбранным контактом.
        response = cast(
            Response,
            self.client.post(
                reverse("orders:order"),
                data={
                    "basket_id": basket.pk,
                    "contact_id": contact.pk,
                },
                format="json",
            ),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )

        response_data = response.data
        assert isinstance(response_data, dict)

        # Проверяем ответ API.
        self.assertEqual(
            response_data["id"],
            basket.pk,
        )

        self.assertEqual(
            response_data["state"],
            Order.Status.NEW,
        )

        self.assertEqual(
            response_data["total_sum"],
            "2400.00",
        )

        # Корзина должна стать оформленным заказом.
        order = Order.objects.get(
            pk=basket.pk,
        )

        self.assertEqual(
            order.state,
            Order.Status.NEW,
        )

        self.assertEqual(
            order.user_id,
            self.buyer.pk,
        )

        self.assertEqual(
            order.contact_id,
            contact.pk,
        )

        self.assertIsNotNone(
            order.placed_at,
        )

        # Активной корзины больше нет.
        self.assertFalse(
            Order.objects.filter(
                user=self.buyer,
                state=Order.Status.BASKET,
            ).exists(),
        )

        # Проверяем сохранённые реквизиты доставки.
        self.assertEqual(
            order.delivery_data["city"],
            "Москва",
        )

        self.assertEqual(
            order.delivery_data["street"],
            "Тверская",
        )

        self.assertEqual(
            order.delivery_data["house"],
            "10",
        )

        # Проверяем товарную позицию заказа.
        order_item = OrderItem.objects.get(
            order=order,
            product_info=self.product_info,
        )

        self.assertEqual(
            order_item.quantity,
            2,
        )

        # Проверяем историческую стоимость.
        self.assertEqual(
            order_item.price_at_order,
            Decimal("1200.00"),
        )

        self.assertEqual(
            order_item.product_name_at_order,
            "Тестовый телевизор",
        )

        self.assertEqual(
            order_item.shop_name_at_order,
            "Тестовый магазин",
        )

        # Проверяем списание товара со склада.
        product_info = ProductInfo.objects.get(
            pk=self.product_info.pk,
        )

        self.assertEqual(
            product_info.quantity,
            8,
        )

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="noreply@test.example",
        ORDER_NOTIFICATION_EMAIL="admin@test.example",
    )
    def test_order_placement_sends_email_notifications(self) -> None:
        """
        Проверяет отправку писем после оформления заказа.

        Оформляет корзину через API и выполняет
        обработчики transaction.on_commit().

        Проверяет отправку подтверждения покупателю
        и накладной администратору.

        Returns:
            None: Результаты проверяются утверждениями.
        """
        # Создаём контакт доставки покупателя.
        contact = Contact.objects.create(
            user=self.buyer,
            last_name="Иванов",
            first_name="Иван",
            email="buyer@test.example",
            phone="+79991234567",
            city="Москва",
            street="Тверская",
            house="10",
        )

        # Подготавливаем корзину с двумя товарами.
        basket = Order.objects.create(
            user=self.buyer,
            state=Order.Status.BASKET,
        )

        OrderItem.objects.create(
            order=basket,
            product_info=self.product_info,
            quantity=2,
        )

        # Выполняем зарегистрированные on_commit
        # после завершения запроса.
        with self.captureOnCommitCallbacks(  # type: ignore
            execute=True,
        ) as callbacks:
            response = cast(
                Response,
                self.client.post(
                    reverse("orders:order"),
                    data={
                        "basket_id": basket.pk,
                        "contact_id": contact.pk,
                    },
                    format="json",
                ),
            )

            self.assertEqual(
                response.status_code,
                status.HTTP_200_OK,
                response.data,
            )

        # Оформление должно зарегистрировать
        # один обработчик отправки уведомлений.
        self.assertEqual(
            len(callbacks),
            1,
        )

        # Получаем письма из тестового почтового ящика.
        outbox = cast(
            list[EmailMessage],
            getattr(mail, "outbox"),
        )

        # Должно быть отправлено ровно два письма.
        self.assertEqual(
            len(outbox),
            2,
        )

        buyer_email = outbox[0]
        admin_email = outbox[1]

        # Проверяем письмо покупателю.
        self.assertEqual(
            buyer_email.to,
            ["buyer@test.example"],
        )

        self.assertIn(
            "Подтверждение заказа",
            buyer_email.subject,
        )

        self.assertIn(
            "Тестовый телевизор",
            buyer_email.body,
        )

        self.assertIn(
            "2400.00",
            buyer_email.body,
        )

        # Проверяем письмо администратору.
        self.assertEqual(
            admin_email.to,
            ["admin@test.example"],
        )

        self.assertIn(
            "Накладная по заказу",
            admin_email.subject,
        )

        self.assertIn(
            "Тестовый телевизор",
            admin_email.body,
        )

        self.assertIn(
            "Москва",
            admin_email.body,
        )

        self.assertIn(
            "2400.00",
            admin_email.body,
        )

    def test_cannot_place_empty_basket(self) -> None:
        """
        Проверяет запрет оформления пустой корзины.

        Создаёт пустую корзину и контакт доставки.
        Попытка оформить заказ должна вернуть HTTP 400.

        После ошибки корзина должна сохранить
        первоначальный статус, а складские остатки
        не должны измениться.

        Returns:
            None: Результаты проверяются утверждениями.
        """
        # Создаём контакт доставки покупателя.
        contact = Contact.objects.create(
            user=self.buyer,
            last_name="Иванов",
            first_name="Иван",
            email="buyer@test.example",
            phone="+79991234567",
            city="Москва",
            street="Тверская",
            house="10",
        )

        # Создаём пустую корзину.
        basket = Order.objects.create(
            user=self.buyer,
            state=Order.Status.BASKET,
        )

        # Проверяем отсутствие товарных позиций.
        self.assertFalse(
            OrderItem.objects.filter(
                order=basket,
            ).exists(),
        )

        # Пытаемся оформить пустую корзину.
        response = cast(
            Response,
            self.client.post(
                reverse("orders:order"),
                data={
                    "basket_id": basket.pk,
                    "contact_id": contact.pk,
                },
                format="json",
            ),
        )

        # API должен вернуть ошибку.
        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
            response.data,
        )

        # Проверяем, что статус корзины не изменился.
        order = Order.objects.get(
            pk=basket.pk,
        )

        self.assertEqual(
            order.state,
            Order.Status.BASKET,
        )

        # Дата оформления не должна появиться.
        self.assertIsNone(
            order.placed_at,
        )

        # Контакт не должен быть привязан к корзине.
        self.assertIsNone(
            order.contact_id,
        )

        # Количество позиций остаётся нулевым.
        self.assertFalse(
            OrderItem.objects.filter(
                order=order,
            ).exists(),
        )

        # Проверяем сохранность складских остатков.
        product_info = ProductInfo.objects.get(
            pk=self.product_info.pk,
        )

        self.assertEqual(
            product_info.quantity,
            10,
        )

    def test_cannot_place_order_with_another_users_contact(self) -> None:
        """
        Проверяет запрет использования чужого контакта доставки.

        Покупатель пытается оформить собственную корзину,
        передав идентификатор контакта другого пользователя.

        API должен вернуть 404 без изменения корзины,
        товарных позиций и складских остатков.

        Returns:
            None: Результаты проверяются утверждениями.
        """
        # Создаём второго пользователя.
        other_user = User.objects.create_user(
            email="another-buyer@test.example",
            password="test-password",
            type=User.UserType.BUYER,
            is_active=True,
        )

        # Контакт принадлежит второму пользователю.
        foreign_contact = Contact.objects.create(
            user=other_user,
            last_name="Петров",
            first_name="Пётр",
            email="another-buyer@test.example",
            phone="+79990000000",
            city="Санкт-Петербург",
            street="Невский проспект",
            house="20",
        )

        # Создаём корзину первого покупателя.
        basket = Order.objects.create(
            user=self.buyer,
            state=Order.Status.BASKET,
        )

        order_item = OrderItem.objects.create(
            order=basket,
            product_info=self.product_info,
            quantity=2,
        )

        # Пытаемся оформить заказ с чужим контактом.
        response = cast(
            Response,
            self.client.post(
                reverse("orders:order"),
                data={
                    "basket_id": basket.pk,
                    "contact_id": foreign_contact.pk,
                },
                format="json",
            ),
        )

        # Чужой контакт должен быть недоступен.
        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
            response.data,
        )

        # Корзина не должна перейти в статус new.
        order = Order.objects.get(pk=basket.pk)

        self.assertEqual(
            order.state,
            Order.Status.BASKET,
        )

        self.assertIsNone(order.placed_at)
        self.assertIsNone(order.contact_id)

        # Товарная позиция не должна измениться.
        saved_item = OrderItem.objects.get(
            pk=order_item.pk,
        )

        self.assertEqual(
            saved_item.quantity,
            2,
        )

        self.assertIsNone(
            saved_item.price_at_order,
        )

        # Складские остатки не должны списываться.
        product_info = ProductInfo.objects.get(
            pk=self.product_info.pk,
        )

        self.assertEqual(
            product_info.quantity,
            10,
        )

    def test_cannot_place_order_with_insufficient_stock(self) -> None:
        """
        Проверяет остатки товаров при оформлении заказа.

        После добавления двух товаров в корзину
        уменьшает складской остаток до одного.

        Оформление должно завершиться ошибкой 400,
        не изменив корзину и складские остатки.

        Returns:
            None: Результаты проверяются утверждениями.
        """
        # Создаём контакт доставки покупателя.
        contact = Contact.objects.create(
            user=self.buyer,
            last_name="Иванов",
            first_name="Иван",
            email="buyer@test.example",
            phone="+79991234567",
            city="Москва",
            street="Тверская",
            house="10",
        )

        # Создаём корзину с двумя телевизорами.
        basket = Order.objects.create(
            user=self.buyer,
            state=Order.Status.BASKET,
        )

        order_item = OrderItem.objects.create(
            order=basket,
            product_info=self.product_info,
            quantity=2,
        )

        # Имитируем изменение остатков на складе.
        # В корзине 2 товара, на складе остался только 1.
        ProductInfo.objects.filter(
            pk=self.product_info.pk,
        ).update(
            quantity=1,
        )

        # Пытаемся оформить заказ.
        response = cast(
            Response,
            self.client.post(
                reverse("orders:order"),
                data={
                    "basket_id": basket.pk,
                    "contact_id": contact.pk,
                },
                format="json",
            ),
        )

        # API должен вернуть ошибку.
        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
            response.data,
        )

        # Корзина не должна стать заказом.
        order = Order.objects.get(
            pk=basket.pk,
        )

        self.assertEqual(
            order.state,
            Order.Status.BASKET,
        )

        self.assertIsNone(order.placed_at)
        self.assertIsNone(order.contact_id)

        self.assertEqual(
            order.delivery_data,
            {},
        )

        # Товарная позиция должна остаться без изменений.
        saved_item = OrderItem.objects.get(
            pk=order_item.pk,
        )

        self.assertEqual(
            saved_item.quantity,
            2,
        )

        self.assertIsNone(
            saved_item.price_at_order,
        )

        self.assertEqual(
            saved_item.product_name_at_order,
            "",
        )

        # Складской остаток не должен уменьшиться повторно.
        product_info = ProductInfo.objects.get(
            pk=self.product_info.pk,
        )

        self.assertEqual(
            product_info.quantity,
            1,
        )

    def test_cannot_place_another_users_basket(self) -> None:
        """
        Проверяет запрет оформления чужой корзины.

        Авторизованный покупатель пытается оформить
        корзину другого пользователя, передав свой
        действительный контакт доставки.

        API должен вернуть 404 без изменения заказа,
        товарных позиций и складских остатков.

        Returns:
            None: Результаты проверяются утверждениями.
        """
        # Создаём второго покупателя.
        other_user = User.objects.create_user(
            email="another-buyer@test.example",
            password="test-password",
            type=User.UserType.BUYER,
            is_active=True,
        )

        # Создаём корзину второго покупателя.
        foreign_basket = Order.objects.create(
            user=other_user,
            state=Order.Status.BASKET,
        )

        foreign_item = OrderItem.objects.create(
            order=foreign_basket,
            product_info=self.product_info,
            quantity=2,
        )

        # Создаём контакт первого покупателя.
        contact = Contact.objects.create(
            user=self.buyer,
            last_name="Иванов",
            first_name="Иван",
            email="buyer@test.example",
            phone="+79991234567",
            city="Москва",
            street="Тверская",
            house="10",
        )

        # self.client уже авторизован как self.buyer.
        # Пытаемся оформить чужую корзину.
        response = cast(
            Response,
            self.client.post(
                reverse("orders:order"),
                data={
                    "basket_id": foreign_basket.pk,
                    "contact_id": contact.pk,
                },
                format="json",
            ),
        )

        # Чужая корзина должна быть недоступна.
        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
            response.data,
        )

        # Чужая корзина не должна стать заказом.
        saved_order = Order.objects.get(
            pk=foreign_basket.pk,
        )

        self.assertEqual(
            saved_order.user_id,
            other_user.pk,
        )

        self.assertEqual(
            saved_order.state,
            Order.Status.BASKET,
        )

        self.assertIsNone(
            saved_order.placed_at,
        )

        self.assertIsNone(
            saved_order.contact_id,
        )

        self.assertEqual(
            saved_order.delivery_data,
            {},
        )

        # Состав корзины не должен измениться.
        saved_item = OrderItem.objects.get(
            pk=foreign_item.pk,
        )

        self.assertEqual(
            saved_item.quantity,
            2,
        )

        self.assertIsNone(
            saved_item.price_at_order,
        )

        # Складские остатки не должны списываться.
        product_info = ProductInfo.objects.get(
            pk=self.product_info.pk,
        )

        self.assertEqual(
            product_info.quantity,
            10,
        )

        # У первого покупателя не должно появиться
        # ни нового заказа, ни активной корзины.
        self.assertFalse(
            Order.objects.filter(
                user=self.buyer,
            ).exists(),
        )

    def test_order_history_and_detail_access(self) -> None:
        """
        Проверяет историю заказов и разграничение доступа.

        Создаёт оформленный заказ покупателя,
        чужой заказ и активную корзину.

        Проверяет, что история содержит только
        собственный оформленный заказ, использует
        исторические цены и не раскрывает чужие данные.

        Returns:
            None: Результаты проверяются утверждениями.
        """
        # Создаём оформленный заказ покупателя.
        own_order = Order.objects.create(
            user=self.buyer,
            state=Order.Status.NEW,
            placed_at=timezone.now(),
            delivery_data={
                "city": "Москва",
                "street": "Тверская",
            },
        )

        OrderItem.objects.create(
            order=own_order,
            product_info=self.product_info,
            quantity=2,
            price_at_order=Decimal("1200.00"),
            product_name_at_order="Тестовый телевизор",
            shop_name_at_order="Тестовый магазин",
        )

        # Создаём другого покупателя.
        other_user = User.objects.create_user(
            email="another-buyer@test.example",
            password="test-password",
            type=User.UserType.BUYER,
            is_active=True,
        )

        # Его заказ не должен быть виден первому.
        foreign_order = Order.objects.create(
            user=other_user,
            state=Order.Status.NEW,
            placed_at=timezone.now(),
        )

        # Активная корзина не должна попадать в историю.
        basket = Order.objects.create(
            user=self.buyer,
            state=Order.Status.BASKET,
        )

        # Меняем текущую цену товара в каталоге.
        # Историческая стоимость заказа должна сохраниться.
        ProductInfo.objects.filter(
            pk=self.product_info.pk,
        ).update(
            price=Decimal("1800.00"),
        )

        # Получаем историю заказов покупателя.
        response = cast(
            Response,
            self.client.get(
                reverse("orders:order"),
            ),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )

        history_data = response.data

        assert isinstance(history_data, list)

        # В истории должен быть только один заказ.
        self.assertEqual(
            len(history_data),
            1,
        )

        own_order_data = history_data[0]

        assert isinstance(own_order_data, dict)

        self.assertEqual(
            own_order_data["id"],
            own_order.pk,
        )

        self.assertEqual(
            own_order_data["state"],
            Order.Status.NEW,
        )

        # Проверяем историческую стоимость.
        self.assertEqual(
            own_order_data["total_sum"],
            "2400.00",
        )

        self.assertEqual(
            own_order_data["ordered_items"][0]["price"],
            "1200.00",
        )

        # Проверяем сохранённый адрес доставки.
        self.assertEqual(
            own_order_data["delivery_data"]["city"],
            "Москва",
        )

        # Получаем детали собственного заказа.
        detail_response = cast(
            Response,
            self.client.get(
                reverse(
                    "orders:order-detail",
                    kwargs={"order_id": own_order.pk},
                ),
            ),
        )

        self.assertEqual(
            detail_response.status_code,
            status.HTTP_200_OK,
            detail_response.data,
        )

        detail_data = detail_response.data

        assert isinstance(detail_data, dict)

        self.assertEqual(
            detail_data["id"],
            own_order.pk,
        )

        self.assertEqual(
            detail_data["total_sum"],
            "2400.00",
        )

        # Попытка получить чужой заказ должна вернуть 404.
        foreign_response = cast(
            Response,
            self.client.get(
                reverse(
                    "orders:order-detail",
                    kwargs={"order_id": foreign_order.pk},
                ),
            ),
        )

        self.assertEqual(
            foreign_response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

        # Активная корзина также недоступна
        # через эндпоинт деталей оформленного заказа.
        basket_response = cast(
            Response,
            self.client.get(
                reverse(
                    "orders:order-detail",
                    kwargs={"order_id": basket.pk},
                ),
            ),
        )

        self.assertEqual(
            basket_response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_cancel_order_restores_stock_once(self) -> None:
        """
        Проверяет отмену заказа и возврат товаров на склад.

        Администратор отменяет оформленный заказ.
        Проверяет восстановление количества товара.

        Повторная отмена должна вернуть ошибку 400
        и не должна повторно увеличивать остатки.

        Returns:
            None: Результаты проверяются утверждениями.
        """
        # Создаём администратора.
        admin_user = User.objects.create_user(
            email="admin@test.example",
            password="test-password",
            is_staff=True,
            is_active=True,
        )

        # Создаём оформленный заказ покупателя.
        order = Order.objects.create(
            user=self.buyer,
            state=Order.Status.NEW,
            placed_at=timezone.now(),
        )

        OrderItem.objects.create(
            order=order,
            product_info=self.product_info,
            quantity=2,
            price_at_order=Decimal("1200.00"),
            product_name_at_order="Тестовый телевизор",
            shop_name_at_order="Тестовый магазин",
        )

        # Имитируем уже выполненное списание при покупке.
        # Изначально на складе было 10 телевизоров.
        ProductInfo.objects.filter(
            pk=self.product_info.pk,
        ).update(
            quantity=8,
        )

        # Авторизуем администратора.
        self.client.force_authenticate(
            user=admin_user,
        )

        url = reverse(
            "orders:order-status-update",
            kwargs={"order_id": order.pk},
        )

        # Отменяем оформленный заказ.
        response = cast(
            Response,
            self.client.patch(
                url,
                data={
                    "state": Order.Status.CANCELED,
                },
                format="json",
            ),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )

        response_data = response.data
        assert isinstance(response_data, dict)

        self.assertEqual(
            response_data["state"],
            Order.Status.CANCELED,
        )

        # Проверяем сохранённый статус заказа.
        saved_order = Order.objects.get(
            pk=order.pk,
        )

        self.assertEqual(
            saved_order.state,
            Order.Status.CANCELED,
        )

        # Два ранее списанных товара должны вернуться.
        product_info = ProductInfo.objects.get(
            pk=self.product_info.pk,
        )

        self.assertEqual(
            product_info.quantity,
            10,
        )

        # Повторно пытаемся отменить тот же заказ.
        repeat_response = cast(
            Response,
            self.client.patch(
                url,
                data={
                    "state": Order.Status.CANCELED,
                },
                format="json",
            ),
        )

        # Повторная отмена запрещена.
        self.assertEqual(
            repeat_response.status_code,
            status.HTTP_400_BAD_REQUEST,
            repeat_response.data,
        )

        # Заказ остаётся отменённым.
        saved_order = Order.objects.get(
            pk=order.pk,
        )

        self.assertEqual(
            saved_order.state,
            Order.Status.CANCELED,
        )

        # Остатки не должны увеличиться до 12.
        product_info = ProductInfo.objects.get(
            pk=self.product_info.pk,
        )

        self.assertEqual(
            product_info.quantity,
            10,
        )

    def test_supplier_sees_only_own_order_items(self) -> None:
        """
        Проверяет изоляцию товарных позиций поставщика.

        Создаёт заказ с товарами двух магазинов
        и отдельный заказ конкурирующего магазина.

        Проверяет, что поставщик получает только
        связанные с его магазином заказы, позиции
        и стоимость собственных товаров.

        Returns:
            None: Результаты проверяются утверждениями.
        """
        # Получаем поставщика из setUp().
        supplier = User.objects.get(
            email="supplier@test.example",
        )

        # Создаём второго поставщика.
        other_supplier = User.objects.create_user(
            email="other-supplier@test.example",
            password="test-password",
            type=User.UserType.SHOP,
            is_active=True,
        )

        other_shop = Shop.objects.create(
            name="Магазин конкурента",
            user=other_supplier,
            state=True,
        )

        # Создаём предложение второго магазина.
        other_product_info = ProductInfo.objects.create(
            product=self.product_info.product,
            shop=other_shop,
            external_id=2001,
            quantity=10,
            price=Decimal("2000.00"),
            price_rrc=Decimal("2500.00"),
        )

        # Создаём заказ с товарами двух поставщиков.
        mixed_order = Order.objects.create(
            user=self.buyer,
            state=Order.Status.NEW,
            placed_at=timezone.now(),
            delivery_data={"city": "Москва"},
        )

        own_item = OrderItem.objects.create(
            order=mixed_order,
            product_info=self.product_info,
            quantity=2,
            price_at_order=Decimal("1200.00"),
            product_name_at_order="Тестовый телевизор",
            shop_name_at_order="Тестовый магазин",
        )

        OrderItem.objects.create(
            order=mixed_order,
            product_info=other_product_info,
            quantity=1,
            price_at_order=Decimal("2000.00"),
            product_name_at_order="Тестовый телевизор",
            shop_name_at_order="Магазин конкурента",
        )

        # Создаём заказ только с товаром конкурента.
        foreign_order = Order.objects.create(
            user=self.buyer,
            state=Order.Status.NEW,
            placed_at=timezone.now(),
        )

        OrderItem.objects.create(
            order=foreign_order,
            product_info=other_product_info,
            quantity=1,
            price_at_order=Decimal("2000.00"),
            product_name_at_order="Тестовый телевизор",
            shop_name_at_order="Магазин конкурента",
        )

        # Создаём активную корзину.
        # Она не должна попадать в заказы поставщика.
        basket = Order.objects.create(
            user=self.buyer,
            state=Order.Status.BASKET,
        )

        OrderItem.objects.create(
            order=basket,
            product_info=self.product_info,
            quantity=1,
        )

        # Авторизуем первого поставщика.
        self.client.force_authenticate(
            user=supplier,
        )

        response = cast(
            Response,
            self.client.get(
                reverse("orders:partner-orders"),
            ),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )

        response_data = response.data
        assert isinstance(response_data, list)

        # Поставщик должен получить только один заказ.
        self.assertEqual(
            len(response_data),
            1,
        )

        order_data = response_data[0]
        assert isinstance(order_data, dict)

        self.assertEqual(
            order_data["id"],
            mixed_order.pk,
        )

        # В заказе должна отображаться только
        # товарная позиция первого поставщика.
        items = order_data["ordered_items"]
        assert isinstance(items, list)

        self.assertEqual(
            len(items),
            1,
        )

        self.assertEqual(
            items[0]["id"],
            own_item.pk,
        )

        self.assertEqual(
            items[0]["product_info_id"],
            self.product_info.pk,
        )

        self.assertEqual(
            items[0]["quantity"],
            2,
        )

        self.assertEqual(
            items[0]["price"],
            "1200.00",
        )

        # Сумма должна учитывать только
        # товары первого поставщика.
        self.assertEqual(
            order_data["supplier_total"],
            "2400.00",
        )

        # Данные доставки доступны для исполнения заказа.
        self.assertEqual(
            order_data["delivery_data"]["city"],
            "Москва",
        )

    def test_orders_list_permissions_and_state_filter(self) -> None:
        """
        Проверяет общий список заказов и фильтрацию.

        Создаёт заказы двух магазинов и активную корзину.

        Проверяет полный доступ администратора,
        ограничение позиций поставщика, фильтрацию
        по статусу и запрет доступа покупателям.

        Returns:
            None: Результаты проверяются утверждениями.
        """
        supplier = User.objects.get(
            email="supplier@test.example",
        )

        other_supplier = User.objects.create_user(
            email="other-supplier@test.example",
            password="test-password",
            type=User.UserType.SHOP,
            is_active=True,
        )

        other_shop = Shop.objects.create(
            name="Магазин конкурента",
            user=other_supplier,
            state=True,
        )

        other_product = ProductInfo.objects.create(
            product=self.product_info.product,
            shop=other_shop,
            external_id=2001,
            quantity=10,
            price=Decimal("2000.00"),
            price_rrc=Decimal("2500.00"),
        )

        # Первый заказ содержит товары двух магазинов.
        mixed_order = Order.objects.create(
            user=self.buyer,
            state=Order.Status.NEW,
            placed_at=timezone.now(),
        )

        own_item = OrderItem.objects.create(
            order=mixed_order,
            product_info=self.product_info,
            quantity=2,
            price_at_order=Decimal("1200.00"),
            product_name_at_order="Тестовый телевизор",
            shop_name_at_order="Тестовый магазин",
        )

        OrderItem.objects.create(
            order=mixed_order,
            product_info=other_product,
            quantity=1,
            price_at_order=Decimal("2000.00"),
            product_name_at_order="Тестовый телевизор",
            shop_name_at_order="Магазин конкурента",
        )

        # Второй заказ принадлежит только другому магазину.
        confirmed_order = Order.objects.create(
            user=self.buyer,
            state=Order.Status.CONFIRMED,
            placed_at=timezone.now(),
        )

        OrderItem.objects.create(
            order=confirmed_order,
            product_info=other_product,
            quantity=1,
            price_at_order=Decimal("2000.00"),
            product_name_at_order="Тестовый телевизор",
            shop_name_at_order="Магазин конкурента",
        )

        # Активная корзина не должна попадать в список.
        Order.objects.create(
            user=self.buyer,
            state=Order.Status.BASKET,
        )

        admin_user = User.objects.create_user(
            email="admin@test.example",
            password="test-password",
            is_staff=True,
            is_active=True,
        )

        url = reverse("orders:orders-list")

        # 1. Администратор видит все оформленные заказы.
        self.client.force_authenticate(user=admin_user)

        response = cast(
            Response,
            self.client.get(url),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )

        admin_data = response.data
        assert isinstance(admin_data, list)

        self.assertCountEqual(
            [item["id"] for item in admin_data],
            [mixed_order.pk, confirmed_order.pk],
        )

        mixed_data = next(item for item in admin_data if item["id"] == mixed_order.pk)

        # Администратор видит оба товара и общую сумму.
        self.assertEqual(
            len(mixed_data["ordered_items"]),
            2,
        )

        self.assertEqual(
            mixed_data["total_sum"],
            "4400.00",
        )

        # 2. Проверяем фильтр администратора.
        response = cast(
            Response,
            self.client.get(
                url,
                {"state": Order.Status.CONFIRMED},
            ),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        filtered_data = response.data
        assert isinstance(filtered_data, list)

        self.assertEqual(
            len(filtered_data),
            1,
        )

        self.assertEqual(
            filtered_data[0]["id"],
            confirmed_order.pk,
        )

        # 3. Поставщик видит только собственные позиции.
        self.client.force_authenticate(user=supplier)

        response = cast(
            Response,
            self.client.get(url),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )

        supplier_data = response.data
        assert isinstance(supplier_data, list)

        self.assertEqual(
            len(supplier_data),
            1,
        )

        supplier_order = supplier_data[0]
        assert isinstance(supplier_order, dict)

        self.assertEqual(
            supplier_order["id"],
            mixed_order.pk,
        )

        items = supplier_order["ordered_items"]
        assert isinstance(items, list)

        self.assertEqual(len(items), 1)

        self.assertEqual(
            items[0]["id"],
            own_item.pk,
        )

        self.assertEqual(
            supplier_order["supplier_total"],
            "2400.00",
        )

        # Общая сумма чужих товаров не раскрывается.
        self.assertNotIn(
            "total_sum",
            supplier_order,
        )

        # 4. Фильтр confirmed не должен вернуть
        # поставщику заказ другого магазина.
        response = cast(
            Response,
            self.client.get(
                url,
                {"state": Order.Status.CONFIRMED},
            ),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.assertEqual(
            response.data,
            [],
        )

        # 5. Покупателю общий список недоступен.
        self.client.force_authenticate(user=self.buyer)

        response = cast(
            Response,
            self.client.get(url),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

        # 6. Без авторизации доступ запрещён.
        self.client.force_authenticate(user=None)

        response = cast(
            Response,
            self.client.get(url),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

        # 7. Некорректный статус возвращает 400.
        self.client.force_authenticate(user=admin_user)

        response = cast(
            Response,
            self.client.get(
                url,
                {"state": "unknown"},
            ),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
