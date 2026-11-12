
from pathlib import Path
from typing import Any

from django.db import transaction

from catalog.models import (
    Category,
    Parameter,
    Product,
    ProductInfo,
    ProductParameter,
    Shop,
)

from .importer import CatalogImportError, load_catalog_yaml
from .validators import validate_catalog_data


@transaction.atomic
def import_categories(
    shop: Shop,
    catalog_data: dict[str, Any],
) -> dict[int, Category]:
    """
    Создаёт или обновляет связи категорий с магазином.

    Сопоставляет категории по названию и связывает их
    с указанным поставщиком. Повторный вызов функции
    не создаёт дубликатов категорий и связей.

    Args:
        shop (Shop): Магазин, которому принадлежит каталог.
        catalog_data (dict[str, Any]): Проверенные данные
            каталога поставщика.

    Returns:
        dict[int, Category]: Словарь соответствия внешних
            ID категорий и объектов Category.

    Raises:
        CatalogImportError: Если название магазина в каталоге
            не соответствует указанному поставщику.
    """
    if catalog_data["shop"] != shop.name:
        raise CatalogImportError(
            "Название магазина в YAML не соответствует выбранному поставщику."
        )

    categories_by_external_id: dict[int, Category] = {}

    for item in catalog_data["categories"]:
        category, _ = Category.objects.get_or_create(
            name=item["name"],
        )

        category.shops.add(shop)

        categories_by_external_id[item["id"]] = category

    return categories_by_external_id


@transaction.atomic
def import_products(
    shop: Shop,
    catalog_data: dict[str, Any],
    categories: dict[int, Category],
) -> dict[int, ProductInfo]:
    """
    Создаёт или обновляет товарные предложения поставщика.

    Находит товары по названию и категории. Для каждого товара
    создаёт или обновляет предложение конкретного магазина
    по внешнему идентификатору.

    Повторный импорт сохраняет идентификаторы существующих
    предложений и обновляет их цены, остатки и другие сведения.

    Args:
        shop (Shop): Магазин, которому принадлежит каталог.
        catalog_data (dict[str, Any]): Проверенные данные YAML.
        categories (dict[int, Category]): Соответствие внешних
            ID категорий объектам Django ORM.

    Returns:
        dict[int, ProductInfo]: Соответствие внешних ID товаров
            и сохранённых товарных предложений.

    Raises:
        CatalogImportError: Если товар ссылается на категорию,
            отсутствующую в переданном словаре.
    """
    products_by_external_id: dict[int, ProductInfo] = {}

    for item in catalog_data["goods"]:
        category_id = item["category"]

        category = categories.get(category_id)

        if category is None:
            raise CatalogImportError(
                f"Не найдена категория с внешним ID {category_id}."
            )

        product, _ = Product.objects.get_or_create(
            name=item["name"],
            category=category,
        )

        product_info, _ = ProductInfo.objects.update_or_create(
            shop=shop,
            external_id=item["id"],
            defaults={
                "product": product,
                "model": item["model"],
                "quantity": item["quantity"],
                "price": item["price"],
                "price_rrc": item["price_rrc"],
            },
        )

        products_by_external_id[item["id"]] = product_info

    return products_by_external_id


@transaction.atomic
def import_parameters(
    catalog_data: dict[str, Any],
    products: dict[int, ProductInfo],
) -> int:
    """
    Создаёт или обновляет характеристики товарных предложений.

    Находит характеристики по названию и связывает их
    с товарными предложениями поставщика.

    При повторном импорте обновляет значения существующих
    характеристик без создания дубликатов.

    Args:
        catalog_data (dict[str, Any]): Проверенные данные каталога.
        products (dict[int, ProductInfo]): Соответствие внешних
            ID товаров и объектов ProductInfo.

    Returns:
        int: Количество обработанных характеристик.

    Raises:
        CatalogImportError: Если товарное предложение
            отсутствует в переданном словаре.
    """
    processed_count = 0

    for item in catalog_data["goods"]:
        external_id = item["id"]

        product_info = products.get(external_id)

        if product_info is None:
            raise CatalogImportError(
                f"Не найдено товарное предложение с ID {external_id}."
            )

        # Удаляем устаревшие характеристики предложения.
        current_parameter_names = set(item["parameters"])

        ProductParameter.objects.filter(
            product_info=product_info,
        ).exclude(
            parameter__name__in=current_parameter_names,
        ).delete()

        for name, value in item["parameters"].items():
            parameter, _ = Parameter.objects.get_or_create(
                name=name,
            )

            ProductParameter.objects.update_or_create(
                product_info=product_info,
                parameter=parameter,
                defaults={
                    "value": value,
                },
            )

            processed_count += 1

    return processed_count


@transaction.atomic
def import_catalog(
    shop: Shop,
    file_path: str | Path,
) -> dict[str, int]:
    """
    Выполняет полный импорт каталога товаров поставщика.

    Загружает YAML-файл, проверяет его содержимое и сохраняет
    категории, товарные предложения и характеристики.

    Все операции сохранения выполняются в одной транзакции.
    При возникновении ошибки изменения отменяются.

    Args:
        shop (Shop): Магазин, для которого выполняется импорт.
        file_path (str | Path): Путь к YAML-файлу каталога.

    Returns:
        dict[str, int]: Статистика выполненного импорта:
            categories — количество обработанных категорий;
            products — количество обработанных предложений;
            parameters — количество обработанных характеристик;
            deactivated — количество предложений, остатки которых обнулены.

    Raises:
        CatalogImportError: Если файл невозможно прочитать,
            данные некорректны или магазин не соответствует
            указанному в YAML.
    """
    # Читаем файл и проверяем данные до записи в БД.
    catalog_data = load_catalog_yaml(file_path)
    validated_data = validate_catalog_data(catalog_data)

    # Создаём категории и связываем их с магазином.
    categories = import_categories(
        shop=shop,
        catalog_data=validated_data,
    )

    # Создаём или обновляем товарные предложения.
    products = import_products(
        shop=shop,
        catalog_data=validated_data,
        categories=categories,
    )

    # Сохраняем характеристики товарных предложений.
    parameters_count = import_parameters(
        catalog_data=validated_data,
        products=products,
    )

    # Обнуляем остатки предложений, отсутствующих в новом прайсе.
    deactivated_count = (
        ProductInfo.objects.filter(shop=shop)
        .exclude(external_id__in=products.keys())
        .exclude(quantity=0)
        .update(quantity=0)
    )

    return {
        "categories": len(categories),
        "products": len(products),
        "parameters": parameters_count,
        "deactivated": deactivated_count,
    }
