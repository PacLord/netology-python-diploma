from django.contrib import admin

from .models import (
    Category,
    Parameter,
    Product,
    ProductInfo,
    ProductParameter,
    Shop,
)


@admin.register(Shop)
class ShopAdmin(admin.ModelAdmin):
    """
    Настраивает административный интерфейс магазинов.

    Позволяет просматривать поставщиков, искать магазины
    по названию и владельцу, фильтровать по статусу.
    """

    list_display = ("id", "name", "user", "state")
    list_display_links = ("id", "name")
    list_filter = ("state",)
    search_fields = ("name", "user__email")
    list_select_related = ("user",)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    """
    Настраивает управление категориями товаров.

    Обеспечивает поиск категорий и управление связями
    между категориями и магазинами.
    """

    list_display = ("id", "name")
    search_fields = ("name",)
    ordering = ("name",)
    filter_horizontal = ("shops",)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    """
    Настраивает административный интерфейс товаров.

    Позволяет искать товары по названию и описанию,
    а также фильтровать их по категориям.
    """

    list_display = ("id", "name", "category")
    list_filter = ("category",)
    search_fields = ("name", "description")
    list_select_related = ("category",)


@admin.register(ProductInfo)
class ProductInfoAdmin(admin.ModelAdmin):
    """
    Настраивает управление товарными предложениями.

    Отображает цены, остатки и поставщиков товаров.
    Позволяет находить предложения конкретного магазина.
    """

    list_display = (
        "id",
        "product",
        "shop",
        "external_id",
        "price",
        "quantity",
    )

    list_filter = ("shop",)
    search_fields = (
        "product__name",
        "shop__name",
        "model",
    )
    list_select_related = ("product", "shop")


@admin.register(Parameter)
class ParameterAdmin(admin.ModelAdmin):
    """
    Настраивает справочник характеристик товаров.

    Позволяет просматривать и искать названия характеристик.
    """

    list_display = ("id", "name")
    search_fields = ("name",)


@admin.register(ProductParameter)
class ProductParameterAdmin(admin.ModelAdmin):
    """
    Настраивает отображение характеристик товарных предложений.

    Позволяет просматривать значения характеристик
    и искать их по названию параметра или товара.
    """

    list_display = (
        "id",
        "product_info",
        "parameter",
        "value",
    )

    list_filter = ("parameter",)
    search_fields = (
        "parameter__name",
        "product_info__product__name",
        "value",
    )
    list_select_related = (
        "product_info__product",
        "product_info__shop",
        "parameter",
    )
