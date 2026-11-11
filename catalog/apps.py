from django.apps import AppConfig


class CatalogConfig(AppConfig):
    """
    Конфигурация приложения каталога товаров.

    Приложение отвечает за поставщиков, категории,
    товары, их характеристики и импорт прайс-листов.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "catalog"
    verbose_name = "Каталог товаров"
