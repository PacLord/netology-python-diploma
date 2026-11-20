from decimal import Decimal
from typing import cast

from django.db import transaction
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    PolymorphicProxySerializer,
    extend_schema,
)
from rest_framework import status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import (
    IsAdminUser,
    IsAuthenticated,
)
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from catalog.models import ProductInfo, Shop
from catalog.permissions import IsSupplier
from orders.models import Order, OrderItem
from orders.serializers import (
    BasketAddSerializer,
    BasketDeleteResponseSerializer,
    BasketDeleteSerializer,
    BasketSerializer,
    BasketUpdateSerializer,
    OrderHistorySerializer,
    OrderListFilterSerializer,
    OrderPlaceResponseSerializer,
    OrderPlaceSerializer,
    OrderStatusUpdateSerializer,
    SupplierOrderSerializer,
)
from orders.services.notifications import send_order_notifications
from orders.services.statuses import change_order_status
from users.models import Contact, User


class BasketView(APIView):
    """
    Управляет корзиной авторизованного пользователя.

    Корзина представлена заказом со статусом basket.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Корзина"],
        summary="Получение корзины пользователя",
        description=(
            "Возвращает текущую корзину с товарными "
            "позициями и общей стоимостью. "
            "Если корзина ещё не создана, возвращает []."
        ),
        responses={
            200: BasketSerializer(many=True),
            401: OpenApiTypes.OBJECT,
            403: OpenApiTypes.OBJECT,
        },
    )
    def get(self, request: Request) -> Response:
        """
        Возвращает активную корзину пользователя.

        Загружает связанные товарные предложения,
        товары и магазины без дополнительных запросов
        к базе для каждой позиции.

        Args:
            request (Request): Запрос пользователя.

        Returns:
            Response: Список с текущей корзиной
                либо пустой список.
        """
        basket = Order.objects.filter(
            user_id=request.user.pk,
            state=Order.Status.BASKET,
        ).prefetch_related(
            "ordered_items__product_info__product",
            "ordered_items__product_info__shop",
        )

        serializer = BasketSerializer(
            basket,
            many=True,
        )

        return Response(
            serializer.data,
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        tags=["Корзина"],
        summary="Добавление товаров в корзину",
        description=(
            "Добавляет товарные предложения в корзину "
            "текущего пользователя. Если предложение уже "
            "присутствует, его количество увеличивается. "
            "Проверяются доступность магазина и остатки."
        ),
        request=BasketAddSerializer,
        responses={
            200: BasketSerializer,
            400: OpenApiTypes.OBJECT,
            401: OpenApiTypes.OBJECT,
        },
    )
    @transaction.atomic
    def post(self, request: Request) -> Response:
        """
        Добавляет товары в корзину пользователя.

        Создаёт корзину при необходимости, проверяет
        доступность предложений и увеличивает количество
        уже существующих позиций.

        Операция выполняется атомарно. Блокировка записи
        пользователя предотвращает конфликты между
        одновременными запросами к его корзине.

        Args:
            request (Request): Запрос с массивом товаров.

        Returns:
            Response: Обновлённая корзина пользователя.

        Raises:
            ValidationError: Если входные данные некорректны,
                магазин не принимает заказы или товара
                недостаточно на складе.
        """
        serializer = BasketAddSerializer(
            data=request.data,
        )

        serializer.is_valid(raise_exception=True)

        data = cast(
            dict[str, list[dict[str, int]]],
            serializer.validated_data,
        )

        items = data["items"]

        product_ids = [item["product_info_id"] for item in items]

        # Запрещаем повторять один товар в одном запросе.
        if len(product_ids) != len(set(product_ids)):
            raise ValidationError(
                {"items": ["Предложения товаров не должны повторяться."]}
            )

        # Сериализуем изменения корзины одного пользователя.
        User.objects.select_for_update().get(
            pk=request.user.pk,
        )

        # Получаем предложения с информацией о магазинах.
        products = ProductInfo.objects.select_related("shop").in_bulk(product_ids)

        if len(products) != len(product_ids):
            raise ValidationError(
                {"items": ["Одно или несколько товарных предложений не найдены."]}
            )

        basket = Order.objects.filter(
            user_id=request.user.pk,
            state=Order.Status.BASKET,
        ).first()

        # Получаем позиции, уже находящиеся в корзине.
        existing_items = {}

        if basket is not None:
            existing_items = {
                item.product_info_id: item
                for item in OrderItem.objects.filter(
                    order=basket,
                    product_info_id__in=product_ids,
                )
            }

        # Проверяем все позиции до изменения базы данных.
        for item in items:
            product_id = item["product_info_id"]
            product = products[product_id]

            if not product.shop.state:
                raise ValidationError(
                    {
                        "items": [
                            f"Магазин предложения #{product_id} не принимает заказы."
                        ]
                    }
                )

            existing = existing_items.get(product_id)

            current_quantity = existing.quantity if existing is not None else 0

            new_quantity = current_quantity + item["quantity"]

            if new_quantity > product.quantity:
                raise ValidationError(
                    {
                        "items": [
                            f"Недостаточно товара #{product_id}. "
                            f"Доступно: {product.quantity}, "
                            f"запрошено всего: {new_quantity}."
                        ]
                    }
                )

        # Создаём корзину только после всех проверок.
        if basket is None:
            basket = Order.objects.create(
                user_id=request.user.pk,
                state=Order.Status.BASKET,
            )

        for item in items:
            product_id = item["product_info_id"]
            quantity = item["quantity"]

            existing = existing_items.get(product_id)

            if existing is not None:
                existing.quantity += quantity
                existing.save(
                    update_fields=["quantity"],
                )
            else:
                OrderItem.objects.create(
                    order=basket,
                    product_info=products[product_id],
                    quantity=quantity,
                )

        # Повторно загружаем корзину вместе с товарами.
        basket = Order.objects.prefetch_related(
            "ordered_items__product_info__product",
            "ordered_items__product_info__shop",
        ).get(pk=basket.pk)

        return Response(
            BasketSerializer(basket).data,
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        tags=["Корзина"],
        summary="Изменение количества товаров в корзине",
        description=(
            "Изменяет количество существующих позиций "
            "корзины текущего пользователя. "
            "При quantity=0 позиция удаляется. "
            "Все изменения выполняются атомарно."
        ),
        request=BasketUpdateSerializer,
        responses={
            200: BasketSerializer,
            400: OpenApiTypes.OBJECT,
            401: OpenApiTypes.OBJECT,
            404: OpenApiTypes.OBJECT,
        },
    )
    @transaction.atomic
    def put(self, request: Request) -> Response:
        """
        Изменяет количество товаров в корзине пользователя.

        Проверяет входные данные, принадлежность позиций
        текущей корзине, доступность магазинов и остатки.

        Все проверки выполняются до сохранения изменений.

        Args:
            request (Request): Запрос с идентификаторами
                позиций и новыми количествами.

        Returns:
            Response: Обновлённая корзина пользователя.

        Raises:
            ValidationError: Если данные некорректны
                или запрошенное количество недоступно.
            NotFound: Если корзина или одна из её позиций
                не найдена.
        """
        serializer = BasketUpdateSerializer(
            data=request.data,
        )

        serializer.is_valid(raise_exception=True)

        data = cast(
            dict[str, list[dict[str, int]]],
            serializer.validated_data,
        )

        items = data["items"]

        item_ids = [item["order_item_id"] for item in items]

        # Проверяем уникальность позиций в запросе.
        if len(item_ids) != len(set(item_ids)):
            raise ValidationError(
                {"items": ["Идентификаторы позиций не должны повторяться."]}
            )

        # Сериализуем изменения корзины пользователя.
        User.objects.select_for_update().get(
            pk=request.user.pk,
        )

        # Находим активную корзину текущего пользователя.
        basket = Order.objects.filter(
            user_id=request.user.pk,
            state=Order.Status.BASKET,
        ).first()

        if basket is None:
            raise NotFound("Корзина пользователя не найдена.")

        # Получаем только позиции текущей корзины.
        existing_items = (
            OrderItem.objects.filter(
                order=basket,
                id__in=item_ids,
            )
            .select_related(
                "product_info__shop",
            )
            .in_bulk(item_ids)
        )

        # Все переданные позиции должны существовать
        # и принадлежать текущей корзине.
        if len(existing_items) != len(item_ids):
            raise NotFound("Одна или несколько позиций корзины не найдены.")

        # Проверяем все изменения до сохранения.
        for item in items:
            # Удаление позиции разрешаем без проверки
            # остатков и состояния магазина.
            if item["quantity"] == 0:
                continue

            order_item = existing_items[item["order_item_id"]]
            product = order_item.product_info

            if not product.shop.state:
                raise ValidationError(
                    {
                        "items": [
                            f"Магазин предложения #{product.pk} не принимает заказы."
                        ]
                    }
                )

            if item["quantity"] > product.quantity:
                raise ValidationError(
                    {
                        "items": [
                            f"Недостаточно товара #{product.pk}. "
                            f"Доступно: {product.quantity}, "
                            f"запрошено: {item['quantity']}."
                        ]
                    }
                )

        # Все проверки пройдены — применяем изменения.
        for item in items:
            order_item = existing_items[item["order_item_id"]]

            if item["quantity"] == 0:
                # Удаляем позицию из корзины.
                order_item.delete()
            else:
                # Обновляем количество товара.
                order_item.quantity = item["quantity"]
                order_item.save(
                    update_fields=["quantity"],
                )

        # Получаем обновлённую корзину для ответа.
        basket = Order.objects.prefetch_related(
            "ordered_items__product_info__product",
            "ordered_items__product_info__shop",
        ).get(pk=basket.pk)

        return Response(
            BasketSerializer(basket).data,
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        tags=["Корзина"],
        summary="Удаление товаров из корзины",
        description=(
            "Удаляет выбранные позиции корзины или "
            "полностью очищает корзину пользователя.\n\n"
            "Если order_item_ids не передан — "
            "удаляются все позиции.\n"
            "Если order_item_ids указан — удаляются "
            "только перечисленные позиции OrderItem."
        ),
        parameters=[
            OpenApiParameter(
                name="order_item_ids",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description=(
                    "Необязательные ID позиций корзины "
                    "(OrderItem) через запятую, "
                    "например: 1,3,5. "
                    "Если параметр отсутствует, "
                    "корзина очищается полностью."
                ),
            ),
        ],
        responses={
            200: BasketDeleteResponseSerializer,
            400: OpenApiTypes.OBJECT,
            401: OpenApiTypes.OBJECT,
            404: OpenApiTypes.OBJECT,
        },
    )
    @transaction.atomic
    def delete(self, request: Request) -> Response:
        """
        Удаляет позиции или полностью очищает корзину.

        При отсутствии параметра order_item_ids удаляет
        все позиции текущей корзины пользователя.

        При наличии order_item_ids проверяет
        идентификаторы и принадлежность всех
        перечисленных позиций текущей корзине.

        Args:
            request (Request): HTTP-запрос с необязательным
                query-параметром order_item_ids.

        Returns:
            Response: Количество удалённых позиций.

        Raises:
            ValidationError: Если список ID некорректен.
            NotFound: Если при выборочном удалении
                корзина или позиции не найдены.
        """
        # None означает отсутствие query-параметра.
        items_raw = request.query_params.get(
            "order_item_ids",
        )

        # Если параметр передан, проверяем его.
        item_ids = None

        if items_raw is not None:
            serializer = BasketDeleteSerializer(
                data={
                    "order_item_ids": items_raw.split(","),
                },
            )

            serializer.is_valid(raise_exception=True)

            data = cast(
                dict[str, list[int]],
                serializer.validated_data,
            )

            item_ids = data["order_item_ids"]

        # Блокируем пользователя на время операции.
        User.objects.select_for_update().get(
            pk=request.user.pk,
        )

        basket = Order.objects.filter(
            user_id=request.user.pk,
            state=Order.Status.BASKET,
        ).first()

        if basket is None:
            # Полная очистка отсутствующей корзины.
            if item_ids is None:
                return Response(
                    {"deleted": 0},
                    status=status.HTTP_200_OK,
                )

            # Выборочное удаление требует корзину.
            raise NotFound("Корзина пользователя не найдена.")

        positions = OrderItem.objects.filter(
            order=basket,
        )

        # Выборочное удаление.
        if item_ids is not None:
            positions = positions.filter(
                id__in=item_ids,
            )

        # Блокируем выбранные записи.
        positions = positions.select_for_update()

        existing_ids = list(positions.values_list("id", flat=True))

        # При выборочном удалении должны найтись
        # все переданные позиции.
        if item_ids is not None and len(existing_ids) != len(item_ids):
            raise NotFound("Одна или несколько позиций корзины не найдены.")

        deleted_count = len(existing_ids)

        positions.delete()

        return Response(
            {"deleted": deleted_count},
            status=status.HTTP_200_OK,
        )


class OrderView(APIView):
    """
    Управляет оформлением заказов пользователя.

    Позволяет авторизованному пользователю подтвердить
    свою корзину, указав контакт доставки.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Заказы"],
        summary="Оформление заказа",
        description=(
            "Подтверждает корзину текущего пользователя. "
            "Проверяет контакт доставки, остатки товаров "
            "и доступность магазинов. Фиксирует цены, "
            "списывает остатки и устанавливает статус new."
        ),
        request=OrderPlaceSerializer,
        responses={
            200: OrderPlaceResponseSerializer,
            400: OpenApiTypes.OBJECT,
            401: OpenApiTypes.OBJECT,
            404: OpenApiTypes.OBJECT,
        },
    )
    @transaction.atomic
    def post(self, request: Request) -> Response:
        """
        Оформляет заказ из существующей корзины.

        Выполняет проверку и списание остатков
        в одной транзакции. Сохраняет цены и адрес
        доставки на момент оформления.

        Args:
            request (Request): Запрос с ID корзины
                и ID контакта доставки.

        Returns:
            Response: Номер, статус, дата и сумма заказа.

        Raises:
            ValidationError: Если корзина пуста,
                магазин недоступен или недостаточно товара.
            Http404: Если корзина или контакт не принадлежат
                текущему пользователю либо не существуют.
        """
        serializer = OrderPlaceSerializer(
            data=request.data,
        )
        serializer.is_valid(raise_exception=True)

        data = cast(
            dict[str, int],
            serializer.validated_data,
        )

        # Сериализуем операции с корзиной пользователя.
        User.objects.select_for_update().get(
            pk=request.user.pk,
        )

        # Находим только собственную активную корзину.
        basket = get_object_or_404(
            Order.objects.select_for_update(),
            pk=data["basket_id"],
            user_id=request.user.pk,
            state=Order.Status.BASKET,
        )

        # Контакт должен принадлежать тому же пользователю.
        contact = get_object_or_404(
            Contact,
            pk=data["contact_id"],
            user_id=request.user.pk,
        )

        # Получаем все позиции корзины.
        items = list(
            OrderItem.objects.filter(
                order=basket,
            )
        )

        if not items:
            raise ValidationError({"detail": ["Нельзя оформить пустую корзину."]})

        product_ids = [item.product_info_id for item in items]

        # Блокируем предложения до конца транзакции.
        product_queryset = (
            ProductInfo.objects.filter(pk__in=product_ids)
            .select_related("shop", "product")
            .select_for_update(of=("self",))
            .order_by("pk")
        )

        # Получаем словарь: {product_info_id: ProductInfo}.
        products = product_queryset.in_bulk()

        if len(products) != len(product_ids):
            raise ValidationError(
                {"detail": ["Некоторые товарные предложения недоступны."]}
            )

        total_sum = Decimal("0.00")

        # Проверяем все позиции до изменения данных.
        for item in items:
            product = products[item.product_info_id]

            if not product.shop.state:
                raise ValidationError(
                    {"detail": [f"Магазин «{product.shop.name}» не принимает заказы."]}
                )

            if item.quantity > product.quantity:
                raise ValidationError(
                    {
                        "detail": [
                            f"Недостаточно товара "
                            f"«{product.product.name}». "
                            f"Доступно: {product.quantity}, "
                            f"запрошено: {item.quantity}."
                        ]
                    }
                )

            total_sum += product.price * item.quantity

        # Проверки пройдены: фиксируем данные
        # и списываем остатки.
        for item in items:
            product = products[item.product_info_id]

            item.price_at_order = product.price
            item.product_name_at_order = product.product.name
            item.shop_name_at_order = product.shop.name

            item.save(
                update_fields=[
                    "price_at_order",
                    "product_name_at_order",
                    "shop_name_at_order",
                ]
            )

            product.quantity -= item.quantity
            product.save(
                update_fields=["quantity"],
            )

        # Фиксируем реквизиты доставки на момент покупки.
        basket.delivery_data = {
            "last_name": contact.last_name,
            "first_name": contact.first_name,
            "middle_name": contact.middle_name,
            "email": contact.email,
            "phone": contact.phone,
            "city": contact.city,
            "street": contact.street,
            "house": contact.house,
            "structure": contact.structure,
            "building": contact.building,
            "apartment": contact.apartment,
        }

        basket.contact_id = contact.pk
        basket.placed_at = timezone.now()
        basket.state = Order.Status.NEW

        basket.save(
            update_fields=[
                "contact",
                "delivery_data",
                "placed_at",
                "state",
            ]
        )

        # Запоминаем ID оформленного заказа.
        order_id = int(basket.pk)

        def send_notifications_after_commit() -> None:
            """
            Отправляет письма после успешной фиксации заказа.

            Returns:
                None: Результат обработки фиксируется сервисом.
            """
            send_order_notifications(order_id)

        transaction.on_commit(
            send_notifications_after_commit,
            robust=True,
        )

        response_serializer = OrderPlaceResponseSerializer(
            {
                "id": basket.pk,
                "state": basket.state,
                "placed_at": basket.placed_at,
                "total_sum": total_sum,
            }
        )

        return Response(
            response_serializer.data,
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        tags=["Заказы"],
        summary="Получение истории заказов",
        description=(
            "Возвращает оформленные заказы текущего "
            "авторизованного пользователя. "
            "Корзины со статусом basket исключаются. "
            "Цены и реквизиты доставки соответствуют "
            "моменту оформления заказа."
        ),
        responses={
            200: OrderHistorySerializer(many=True),
            401: OpenApiTypes.OBJECT,
        },
    )
    def get(self, request: Request) -> Response:
        """
        Возвращает историю заказов текущего пользователя.

        Исключает активную корзину. Загружает товарные
        позиции заранее, чтобы избежать дополнительных
        запросов к БД для каждого заказа.

        Args:
            request (Request): HTTP-запрос
                авторизованного пользователя.

        Returns:
            Response: Список оформленных заказов
                с товарами, суммами и данными доставки.
        """
        orders = (
            Order.objects.filter(
                user_id=request.user.pk,
            )
            .exclude(
                state=Order.Status.BASKET,
            )
            .prefetch_related(
                "ordered_items",
            )
            .order_by(
                "-placed_at",
                "-pk",
            )
        )

        serializer = OrderHistorySerializer(
            orders,
            many=True,
        )

        return Response(
            serializer.data,
            status=status.HTTP_200_OK,
        )


class PartnerOrdersView(APIView):
    """
    Предоставляет поставщику список его заказов.

    Возвращает оформленные заказы, содержащие
    товары собственного магазина поставщика.
    """

    permission_classes = [IsAuthenticated, IsSupplier]

    @extend_schema(
        tags=["Поставщики"],
        summary="Получение заказов поставщика",
        description=(
            "Возвращает оформленные заказы с товарами "
            "магазина текущего поставщика. "
            "В составе заказа отображаются исключительно "
            "позиции этого магазина. "
            "Сумма supplier_total рассчитана только "
            "по товарам данного поставщика."
        ),
        responses={
            200: SupplierOrderSerializer(many=True),
            401: OpenApiTypes.OBJECT,
            403: OpenApiTypes.OBJECT,
            404: OpenApiTypes.OBJECT,
        },
    )
    def get(self, request: Request) -> Response:
        """
        Возвращает оформленные заказы своего магазина.

        Проверяет роль пользователя и наличие магазина.
        Исключает корзины и фильтрует товарные позиции
        по текущему поставщику.

        Args:
            request (Request): Запрос авторизованного
                пользователя-поставщика.

        Returns:
            Response: Список заказов с позициями
                собственного магазина.

        Raises:
            Http404: Если магазин поставщика не найден.
        """
        shop = get_object_or_404(
            Shop,
            user_id=request.user.pk,
        )

        # Позиции, принадлежащие только этому магазину.
        supplier_items = OrderItem.objects.filter(
            product_info__shop_id=shop.pk,
        ).order_by("pk")

        # Выбираем заказы с товарами этого магазина.
        orders = (
            Order.objects.filter(
                ordered_items__product_info__shop_id=shop.pk,
            )
            .exclude(
                state=Order.Status.BASKET,
            )
            .order_by(
                "-placed_at",
                "-pk",
            )
            .distinct()
            .prefetch_related(
                Prefetch(
                    "ordered_items",
                    queryset=supplier_items,
                    to_attr="supplier_items",
                )
            )
        )

        serializer = SupplierOrderSerializer(
            orders,
            many=True,
        )

        return Response(
            serializer.data,
            status=status.HTTP_200_OK,
        )


class OrderDetailView(APIView):
    """
    Предоставляет подробную информацию об оформленном заказе.

    Доступ разрешён только владельцу заказа.
    Активные корзины не включаются в историю покупок.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Заказы"],
        summary="Получение подробной информации о заказе",
        description=(
            "Возвращает один оформленный заказ текущего "
            "авторизованного пользователя. "
            "Содержит товарные позиции, зафиксированные "
            "цены, общую сумму и реквизиты доставки. "
            "Активная корзина недоступна через этот метод."
        ),
        responses={
            200: OrderHistorySerializer,
            401: OpenApiTypes.OBJECT,
            404: OpenApiTypes.OBJECT,
        },
    )
    def get(
        self,
        request: Request,
        order_id: int,
    ) -> Response:
        """
        Возвращает подробную информацию о собственном заказе.

        Находит заказ по идентификатору, проверяет
        владельца и исключает активные корзины.

        Args:
            request (Request): Запрос авторизованного пользователя.
            order_id (int): Идентификатор оформленного заказа.

        Returns:
            Response: Информация об оформленном заказе.

        Raises:
            Http404: Если заказ не существует, принадлежит
                другому пользователю или является корзиной.
        """
        order = get_object_or_404(
            Order.objects.exclude(
                state=Order.Status.BASKET,
            ).prefetch_related(
                "ordered_items",
            ),
            pk=order_id,
            user_id=request.user.pk,
        )

        serializer = OrderHistorySerializer(order)

        return Response(
            serializer.data,
            status=status.HTTP_200_OK,
        )


class OrderStatusUpdateView(APIView):
    """
    Позволяет администратору изменять статус заказа.

    Проверяет права доступа и передаёт изменение
    статуса в сервис управления заказами.
    """

    permission_classes = [IsAuthenticated, IsAdminUser]

    @extend_schema(
        tags=["Заказы"],
        summary="Изменение статуса заказа",
        description=(
            "Изменяет статус оформленного заказа. "
            "Доступ разрешён только администраторам. "
            "Допустимые переходы определяются бизнес-логикой. "
            "При отмене заказа восстанавливаются остатки товаров."
        ),
        request=OrderStatusUpdateSerializer,
        responses={
            200: OrderHistorySerializer,
            400: OpenApiTypes.OBJECT,
            401: OpenApiTypes.OBJECT,
            403: OpenApiTypes.OBJECT,
            404: OpenApiTypes.OBJECT,
        },
    )
    def patch(
        self,
        request: Request,
        order_id: int,
    ) -> Response:
        """
        Изменяет статус оформленного заказа.

        Проверяет входные данные и вызывает сервис,
        выполняющий изменение статуса в транзакции.

        Args:
            request (Request): HTTP-запрос администратора.
            order_id (int): Идентификатор заказа.

        Returns:
            Response: Обновлённые сведения о заказе.

        Raises:
            ValidationError: Если статус или переход
                между статусами недопустим.
            Http404: Если заказ не существует
                или является корзиной.
        """
        serializer = OrderStatusUpdateSerializer(
            data=request.data,
        )

        serializer.is_valid(raise_exception=True)

        data = cast(
            dict[str, str],
            serializer.validated_data,
        )

        # Изменяем статус через сервис.
        order = change_order_status(
            order_id=order_id,
            new_state=data["state"],
        )

        # Возвращаем обновлённый заказ.
        response_serializer = OrderHistorySerializer(
            order,
        )

        return Response(
            response_serializer.data,
            status=status.HTTP_200_OK,
        )


class OrdersListView(APIView):
    """
    Предоставляет список оформленных заказов.

    Администратор получает все оформленные заказы.
    Поставщик получает только заказы, содержащие
    товары принадлежащего ему магазина.

    Покупателям доступ запрещён.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Заказы"],
        summary="Получение списка заказов",
        description=(
            "Администратор получает все оформленные заказы. "
            "Поставщик получает заказы только со своими "
            "товарными позициями. "
            "Поддерживается необязательный фильтр state. "
            "Корзины исключаются из результатов."
        ),
        parameters=[OrderListFilterSerializer],
        responses={
            200: PolymorphicProxySerializer(
                component_name="OrdersListResponse",
                serializers=[
                    OrderHistorySerializer,
                    SupplierOrderSerializer,
                ],
                resource_type_field_name=None,
                many=True,
            ),
            400: OpenApiTypes.OBJECT,
            401: OpenApiTypes.OBJECT,
            403: OpenApiTypes.OBJECT,
            404: OpenApiTypes.OBJECT,
        },
    )
    def get(self, request: Request) -> Response:
        """
        Возвращает список заказов с учётом прав доступа.

        Проверяет роль пользователя и необязательный
        фильтр по статусу заказа.

        Для администратора возвращает все позиции заказов.
        Для поставщика оставляет только товарные
        позиции его магазина.

        Args:
            request (Request): HTTP-запрос авторизованного
                пользователя с необязательным параметром state.

        Returns:
            Response: Отфильтрованный список заказов.

        Raises:
            ValidationError: Если указан неверный статус.
            PermissionDenied: Если пользователь не является
                администратором или поставщиком.
            Http404: Если у поставщика отсутствует магазин.
        """
        # Проверяем параметры фильтрации.
        filter_serializer = OrderListFilterSerializer(
            data=request.query_params,
        )

        filter_serializer.is_valid(raise_exception=True)

        filters = cast(
            dict[str, str],
            filter_serializer.validated_data,
        )

        # Получаем только оформленные заказы.
        orders = Order.objects.exclude(
            state=Order.Status.BASKET,
        )

        # Фильтруем по статусу, если он передан.
        if "state" in filters:
            orders = orders.filter(
                state=filters["state"],
            )

        # Новые заказы отображаются первыми.
        orders = orders.order_by(
            "-placed_at",
            "-pk",
        )

        # Администратор видит все заказы и их позиции.
        if request.user.is_staff:
            orders = orders.prefetch_related(
                "ordered_items",
            )

            serializer = OrderHistorySerializer(
                orders,
                many=True,
            )

            return Response(
                serializer.data,
                status=status.HTTP_200_OK,
            )

        # Остальным покупателям доступ запрещён.
        if request.user.type != User.UserType.SHOP:
            raise PermissionDenied(
                "Доступ разрешён только администраторам и поставщикам."
            )

        # Находим магазин текущего поставщика.
        shop = get_object_or_404(
            Shop,
            user_id=request.user.pk,
        )

        # Выбираем только позиции магазина поставщика.
        supplier_items = OrderItem.objects.filter(
            product_info__shop_id=shop.pk,
        ).order_by("pk")

        # Выбираем заказы, содержащие товары магазина.
        orders = (
            orders.filter(
                ordered_items__product_info__shop_id=shop.pk,
            )
            .distinct()
            .prefetch_related(
                Prefetch(
                    "ordered_items",
                    queryset=supplier_items,
                    to_attr="supplier_items",
                )
            )
        )

        serializer = SupplierOrderSerializer(
            orders,
            many=True,
        )

        return Response(
            serializer.data,
            status=status.HTTP_200_OK,
        )
