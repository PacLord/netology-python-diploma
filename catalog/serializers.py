from urllib.parse import urlsplit

from rest_framework import serializers

from catalog.models import (
    Category,
    Product,
    ProductInfo,
    ProductParameter,
    Shop,
)


class CategorySerializer(serializers.ModelSerializer):
    """
    Сериализует категории товаров для публичного API.

    Возвращает идентификатор и название категории.
    """

    class Meta:
        model = Category
        fields = ("id", "name")
        read_only_fields = fields


class ShopSerializer(serializers.ModelSerializer):
    """
    Сериализует данные магазина для публичного API.

    Возвращает идентификатор, название магазина
    и его текущий статус приёма заказов.
    """

    class Meta:
        model = Shop
        fields = ("id", "name", "state")
        read_only_fields = fields


class ProductSerializer(serializers.ModelSerializer):
    """
    Сериализует основную информацию о товаре.

    Возвращает название, описание и категорию товара.
    """

    category = serializers.StringRelatedField()

    class Meta:
        model = Product
        fields = ("name", "description", "category")
        read_only_fields = fields


class ProductParameterSerializer(serializers.ModelSerializer):
    """
    Сериализует характеристику товарного предложения.

    Возвращает название характеристики и её значение.
    """

    parameter = serializers.StringRelatedField()

    class Meta:
        model = ProductParameter
        fields = ("parameter", "value")
        read_only_fields = fields


class ProductInfoSerializer(serializers.ModelSerializer):
    """
    Сериализует товарное предложение поставщика.

    Объединяет информацию о товаре, его стоимости,
    количестве на складе и характеристиках.
    """

    product = ProductSerializer(read_only=True)

    product_parameters = ProductParameterSerializer(
        many=True,
        read_only=True,
    )

    class Meta:
        model = ProductInfo
        fields = (
            "id",
            "model",
            "product",
            "shop",
            "quantity",
            "price",
            "price_rrc",
            "product_parameters",
        )
        read_only_fields = fields


class ProductFilterSerializer(serializers.Serializer):
    """
    Проверяет параметры фильтрации товарных предложений.

    Оба параметра необязательны и должны содержать
    положительные целые числа.
    """

    shop_id = serializers.IntegerField(
        required=False,
        min_value=1,
        help_text="ID магазина. Показывает товары выбранного поставщика.",
    )

    category_id = serializers.IntegerField(
        required=False,
        min_value=1,
        help_text="ID категории. Показывает товары выбранной категории.",
    )

    search = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=255,
        help_text="Поиск по названию, модели и описанию товара.",
    )


class PartnerStateUpdateSerializer(serializers.Serializer):
    """
    Проверяет запрос на изменение состояния магазина.

    Принимает обязательный булев параметр state,
    определяющий возможность приёма новых заказов.
    """

    state = serializers.BooleanField(
        required=True,
        help_text=("true — магазин принимает заказы; false — приём заказов отключён."),
    )


class PartnerUpdateSerializer(serializers.Serializer):
    """
    Проверяет данные запроса на обновление прайс-листа.

    Принимает URL YAML-файла поставщика.
    Разрешает только протоколы HTTP и HTTPS.
    """

    url = serializers.URLField(
        max_length=2048,
        help_text=(
            "HTTP или HTTPS ссылка на YAML-файл с каталогом товаров поставщика."
        ),
    )

    def validate_url(self, value: str) -> str:
        """
        Проверяет допустимость URL прайс-листа.

        Запрещает неподдерживаемые протоколы
        и передачу учётных данных внутри URL.

        Args:
            value (str): Адрес YAML-файла.

        Returns:
            str: Проверенный URL.

        Raises:
            serializers.ValidationError: Если URL содержит
                недопустимый протокол или учётные данные.
        """
        parsed_url = urlsplit(value)

        if parsed_url.scheme.lower() not in ("http", "https"):
            raise serializers.ValidationError(
                "Разрешены только протоколы HTTP и HTTPS."
            )

        if parsed_url.username is not None or parsed_url.password is not None:
            raise serializers.ValidationError(
                "URL не должен содержать логин или пароль."
            )

        return value


class PartnerUpdateResponseSerializer(serializers.Serializer):
    """
    Описывает результат обновления каталога поставщика.

    Содержит сообщение об успешном импорте
    и статистику обработки товарного каталога.
    """

    detail = serializers.CharField()
    categories = serializers.IntegerField()
    products = serializers.IntegerField()
    parameters = serializers.IntegerField()
    deactivated = serializers.IntegerField()
