from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class Shop(models.Model):
    """
    Магазин поставщика в системе автоматизации закупок.

    Каждый магазин принадлежит одному пользователю-поставщику.
    Магазин может включать и отключать приём новых заказов.
    """

    name = models.CharField(
        verbose_name="Название магазина",
        max_length=100,
    )

    url = models.URLField(
        verbose_name="Сайт магазина",
        blank=True,
    )

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        verbose_name="Владелец магазина",
        on_delete=models.PROTECT,
        related_name="shop",
    )

    state = models.BooleanField(
        verbose_name="Принимает заказы",
        default=True,
    )

    class Meta:
        verbose_name = "Магазин"
        verbose_name_plural = "Магазины"
        ordering = ["name"]

    def __str__(self):
        """
        Возвращает название магазина для отображения в Django Admin.

        Returns:
            str: Название магазина.
        """
        return self.name


class Category(models.Model):
    """
    Категория товаров в общем каталоге закупок.

    Одна категория может использоваться несколькими магазинами.
    Категории являются общими для всех поставщиков системы.
    """

    name = models.CharField(
        verbose_name="Название категории",
        max_length=100,
        unique=True,
    )

    shops = models.ManyToManyField(
        Shop,
        verbose_name="Магазины",
        related_name="categories",
        blank=True,
    )

    class Meta:
        verbose_name = "Категория"
        verbose_name_plural = "Категории"
        ordering = ["name"]

    def __str__(self):
        """
        Возвращает название категории.

        Returns:
            str: Название категории товаров.
        """
        return self.name


class Product(models.Model):
    """
    Товар в общем каталоге системы автоматизации закупок.

    Содержит общую информацию о товаре, не зависящую
    от конкретного поставщика.

    Цена, количество и другие параметры предложения
    хранятся отдельно в модели ProductInfo.
    """

    name = models.CharField(
        verbose_name="Название товара",
        max_length=255,
    )

    description = models.TextField(
        verbose_name="Описание товара",
        blank=True,
    )

    category = models.ForeignKey(
        Category,
        verbose_name="Категория",
        on_delete=models.PROTECT,
        related_name="products",
    )

    class Meta:
        verbose_name = "Товар"
        verbose_name_plural = "Товары"
        ordering = ["name"]
        constraints = [
            # запрещает создавать два товара с одинаковым названием внутри одной категории
            models.UniqueConstraint(
                fields=["category", "name"],
                name="unique_product_category_name",
            ),
        ]

    def __str__(self):
        """
        Возвращает название товара.

        Returns:
            str: Название товара.
        """
        return self.name


class ProductInfo(models.Model):
    """
    Товарное предложение конкретного поставщика.

    Содержит информацию о наличии, цене и модели товара
    в отдельном магазине. Один товар может иметь несколько
    предложений от разных поставщиков.

    Внешний идентификатор товара уникален в пределах магазина.
    """

    product = models.ForeignKey(
        Product,
        verbose_name="Товар",
        on_delete=models.PROTECT,
        related_name="product_infos",
    )

    shop = models.ForeignKey(
        Shop,
        verbose_name="Магазин",
        on_delete=models.PROTECT,
        related_name="product_infos",
    )

    external_id = models.PositiveBigIntegerField(
        verbose_name="Внешний ID товара",
    )

    model = models.CharField(
        verbose_name="Модель производителя",
        max_length=255,
        blank=True,
    )

    quantity = models.PositiveIntegerField(
        verbose_name="Количество на складе",
        default=0,
    )

    price = models.DecimalField(
        verbose_name="Цена",
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )

    price_rrc = models.DecimalField(
        verbose_name="Рекомендованная розничная цена",
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )

    class Meta:
        verbose_name = "Товарное предложение"
        verbose_name_plural = "Товарные предложения"
        ordering = ["product__name", "shop__name"]

        constraints = [
            # один поставщик не может создать два предложения
            # с одинаковым внешним идентификатором,
            # даже если они ссылаются на разные записи Product
            models.UniqueConstraint(
                fields=["shop", "external_id"],
                name="unique_shop_external_product",
            ),
        ]

    def __str__(self):
        """
        Возвращает название товара и магазина.

        Returns:
            str: Строковое представление товарного предложения.
        """
        return f"{self.product.name} — {self.shop.name}"


class Parameter(models.Model):
    """
    Справочник названий характеристик товаров.

    Позволяет использовать общие характеристики для разных
    товарных предложений без дублирования их названий.
    """

    name = models.CharField(
        verbose_name="Название характеристики",
        max_length=100,
        unique=True,
    )

    class Meta:
        verbose_name = "Характеристика"
        verbose_name_plural = "Характеристики"
        ordering = ["name"]

    def __str__(self):
        """
        Возвращает название характеристики.

        Returns:
            str: Название характеристики товара.
        """
        return self.name


class ProductParameter(models.Model):
    """
    Значение характеристики конкретного товарного предложения.

    Связывает товарное предложение с характеристикой
    и хранит её значение в строковом формате.
    """

    product_info = models.ForeignKey(
        ProductInfo,
        verbose_name="Товарное предложение",
        on_delete=models.CASCADE,
        related_name="product_parameters",
    )

    parameter = models.ForeignKey(
        Parameter,
        verbose_name="Характеристика",
        on_delete=models.PROTECT,
        related_name="product_parameters",
    )

    value = models.CharField(
        verbose_name="Значение характеристики",
        max_length=255,
    )

    class Meta:
        verbose_name = "Характеристика товара"
        verbose_name_plural = "Характеристики товаров"
        ordering = ["parameter__name"]
        constraints = [
            # Для одного предложения нельзя дважды указать одну характеристику
            models.UniqueConstraint(
                fields=["product_info", "parameter"],
                name="unique_product_info_parameter",
            ),
        ]

    def __str__(self):
        """
        Возвращает характеристику и её значение.

        Returns:
            str: Название характеристики и её значение.
        """
        return f"{self.parameter.name}: {self.value}"
