# Create your tests here.
from copy import deepcopy
from decimal import Decimal
from unittest.mock import patch

from django.conf import settings
from django.test import TestCase

from catalog.models import Category, ProductInfo, ProductParameter, Shop
from catalog.services.catalog_import import import_catalog
from catalog.services.importer import (
    CatalogImportError,
    load_catalog_yaml,
)
from users.models import User


class CatalogImportTests(TestCase):
    """
    Проверяет импорт и синхронизацию каталога поставщика.

    Тесты используют отдельную тестовую базу данных
    и не изменяют основной каталог приложения.
    """

    shop: Shop

    @classmethod
    def setUpTestData(cls) -> None:
        """
        Создаёт поставщика и магазин для тестирования.

        Вызывается один раз перед выполнением тестов класса.
        Подготовленные данные доступны всем его тестам.
        """
        user = User.objects.create_user(
            email="supplier-test@example.com",
            password="test-password-123",
            type="shop",
        )

        cls.shop = Shop.objects.create(
            name="Связной",
            user=user,
        )

    def test_repeated_import_does_not_create_duplicates(self) -> None:
        """
        Проверяет, что повторный импорт не создаёт дубликаты.

        Убеждается, что количество товарных предложений
        и характеристик не изменяется, а идентификаторы
        существующих предложений сохраняются.
        """
        file_path = settings.BASE_DIR / "data" / "shop1.yaml"

        # Первый импорт создаёт товары и характеристики.
        first_result = import_catalog(self.shop, file_path)

        offers_before = dict(
            ProductInfo.objects.filter(
                shop=self.shop,
            ).values_list("external_id", "pk")
        )

        parameters_before = ProductParameter.objects.filter(
            product_info__shop=self.shop,
        ).count()

        # Второй импорт должен обновить существующие записи.
        second_result = import_catalog(self.shop, file_path)

        offers_after = dict(
            ProductInfo.objects.filter(
                shop=self.shop,
            ).values_list("external_id", "pk")
        )

        parameters_after = ProductParameter.objects.filter(
            product_info__shop=self.shop,
        ).count()

        # Проверяем количество импортированных предложений.
        self.assertEqual(first_result["products"], 14)
        self.assertEqual(second_result["products"], 14)

        # Проверяем сохранность идентификаторов предложений.
        self.assertEqual(offers_before, offers_after)

        # Проверяем, что характеристики не дублируются.
        self.assertEqual(parameters_before, parameters_after)

        # Все 14 товаров присутствуют в магазине.
        self.assertEqual(len(offers_after), 14)

        # Повторный импорт не должен обнулять остатки.
        self.assertEqual(second_result["deactivated"], 0)

    def test_import_rollback_on_error(self) -> None:
        """
        Проверяет откат транзакции при ошибке импорта.

        Убеждается, что новая категория не сохраняется,
        а изменение цены существующего предложения
        отменяется при исключении во время импорта.
        """
        file_path = settings.BASE_DIR / "data" / "shop1.yaml"

        # Создаём исходный каталог в тестовой базе.
        import_catalog(self.shop, file_path)

        data = load_catalog_yaml(file_path)

        external_id = data["goods"][0]["id"]

        product_info = ProductInfo.objects.get(
            shop=self.shop,
            external_id=external_id,
        )

        original_price = product_info.price

        # Добавляем новую категорию.
        test_category_name = "Тестовая категория отката"

        data["categories"].append(
            {
                "id": max(category["id"] for category in data["categories"]) + 1,
                "name": test_category_name,
            }
        )

        # Изменяем цену существующего товара.
        data["goods"][0]["price"] = str(original_price + Decimal("500.00"))

        # Подменяем чтение YAML и искусственно вызываем
        # ошибку после сохранения категорий и товаров.
        with (
            patch(
                "catalog.services.catalog_import.load_catalog_yaml",
                return_value=data,
            ),
            patch(
                "catalog.services.catalog_import.import_parameters",
                side_effect=RuntimeError("Тестовая ошибка импорта"),
            ),
            self.assertRaisesRegex(
                RuntimeError,
                "Тестовая ошибка импорта",
            ),
        ):
            import_catalog(self.shop, file_path)

        # Новая категория не должна сохраниться.
        self.assertFalse(
            Category.objects.filter(
                name=test_category_name,
            ).exists()
        )

        # Цена должна остаться исходной.
        product_info.refresh_from_db()

        self.assertEqual(
            product_info.price,
            original_price,
        )

    def test_catalog_synchronization(self) -> None:
        """
        Проверяет синхронизацию товаров и характеристик.

        Убеждается, что отсутствующий в прайс-листе товар
        сохраняет свой идентификатор, но получает нулевой остаток.

        Проверяет удаление устаревшей характеристики,
        а также восстановление данных при повторном импорте
        исходного каталога.
        """
        file_path = settings.BASE_DIR / "data" / "shop1.yaml"

        # Создаём исходный каталог.
        import_catalog(self.shop, file_path)

        data = load_catalog_yaml(file_path)

        # Выбираем товар с положительным остатком.
        removed_item = next(
            item
            for item in data["goods"]
            if item["id"] != 4216292 and item["quantity"] > 0
        )

        removed_id = removed_item["id"]
        original_quantity = removed_item["quantity"]

        product_info = ProductInfo.objects.get(
            shop=self.shop,
            external_id=removed_id,
        )

        original_pk = product_info.pk

        # Удаляем товар из нового прайс-листа.
        data["goods"] = [item for item in data["goods"] if item["id"] != removed_id]

        # Удаляем характеристику "Цвет" у iPhone.
        iphone_item = next(item for item in data["goods"] if item["id"] == 4216292)

        iphone_item["parameters"].pop("Цвет")

        # Имитируем загрузку изменённого YAML.
        with patch(
            "catalog.services.catalog_import.load_catalog_yaml",
            return_value=data,
        ):
            result = import_catalog(self.shop, file_path)

        # Проверяем обработку отсутствующего товара.
        product_info.refresh_from_db()

        self.assertEqual(product_info.pk, original_pk)
        self.assertEqual(product_info.quantity, 0)
        self.assertEqual(result["deactivated"], 1)

        # Проверяем удаление устаревшей характеристики.
        color_exists = ProductParameter.objects.filter(
            product_info__shop=self.shop,
            product_info__external_id=4216292,
            parameter__name="Цвет",
        ).exists()

        self.assertFalse(color_exists)

        # Повторно импортируем исходный YAML.
        import_catalog(self.shop, file_path)

        product_info.refresh_from_db()

        # Остаток и первичный ключ должны восстановиться.
        self.assertEqual(
            product_info.quantity,
            original_quantity,
        )
        self.assertEqual(product_info.pk, original_pk)

        # Характеристика "Цвет" должна восстановиться.
        color_restored = ProductParameter.objects.filter(
            product_info__shop=self.shop,
            product_info__external_id=4216292,
            parameter__name="Цвет",
        ).exists()

        self.assertTrue(color_restored)

    def test_invalid_catalog_data(self) -> None:
        """
        Проверяет отклонение некорректного каталога.

        Тестирует отрицательные числовые значения,
        неизвестные категории, повторяющиеся идентификаторы
        и неправильные типы характеристик.

        Убеждается, что при ошибке валидации данные
        не сохраняются в PostgreSQL.
        """
        file_path = settings.BASE_DIR / "data" / "shop1.yaml"
        source_data = load_catalog_yaml(file_path)

        # Сценарий 1. Отрицательная цена.
        invalid_price = deepcopy(source_data)
        invalid_price["goods"][0]["price"] = -100

        # Сценарий 2. Отрицательное количество.
        invalid_quantity = deepcopy(source_data)
        invalid_quantity["goods"][0]["quantity"] = -5

        # Сценарий 3. Несуществующая категория.
        unknown_category = deepcopy(source_data)
        unknown_category["goods"][0]["category"] = 999999

        # Сценарий 4. Повторяющиеся ID товаров.
        duplicate_product = deepcopy(source_data)
        duplicate_product["goods"][1]["id"] = duplicate_product["goods"][0]["id"]

        # Сценарий 5. Недопустимое значение характеристики.
        invalid_parameter = deepcopy(source_data)
        invalid_parameter["goods"][0]["parameters"]["Цвет"] = [
            "золотистый",
            "серебристый",
        ]

        test_cases = {
            "Отрицательная цена": invalid_price,
            "Отрицательное количество": invalid_quantity,
            "Неизвестная категория": unknown_category,
            "Дублирующийся ID": duplicate_product,
            "Неверный тип характеристики": invalid_parameter,
        }

        for scenario, invalid_data in test_cases.items():
            with self.subTest(scenario=scenario):
                # Подменяем содержимое загружаемого YAML.
                with patch(  # noqa: SIM117
                    "catalog.services.catalog_import.load_catalog_yaml",
                    return_value=invalid_data,
                ):
                    # Импорт обязан завершиться ошибкой.
                    with self.assertRaises(CatalogImportError):
                        import_catalog(self.shop, file_path)

                # Ошибка не должна приводить к записи данных.
                self.assertEqual(Category.objects.count(), 0)

                self.assertEqual(
                    ProductInfo.objects.filter(
                        shop=self.shop,
                    ).count(),
                    0,
                )

                self.assertEqual(
                    ProductParameter.objects.count(),
                    0,
                )
