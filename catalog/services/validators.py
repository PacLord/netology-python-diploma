from decimal import Decimal
from typing import Any

from rest_framework import serializers

from .importer import CatalogImportError


class ParameterValueField(serializers.Field):
    """
    Проверяет и преобразует значение характеристики товара.

    Поддерживает строки, числа и логические значения.
    Все допустимые значения преобразуются в строки.
    """

    def to_internal_value(self, data):
        """
        Преобразует значение характеристики в строку.

        Args:
            data: Исходное значение из YAML.

        Returns:
            str: Нормализованное значение характеристики.

        Raises:
            ValidationError: Если тип или длина значения недопустимы.
        """
        if isinstance(data, bool):
            value = str(data).lower()
        elif isinstance(data, (str, int, float, Decimal)):
            value = str(data).strip()
        else:
            raise serializers.ValidationError(
                "Недопустимый тип значения характеристики."
            )

        if not value or len(value) > 255:
            raise serializers.ValidationError(
                "Значение должно содержать от 1 до 255 символов."
            )

        return value

    def to_representation(self, value):
        """
        Возвращает строковое представление характеристики.

        Args:
            value: Значение характеристики.

        Returns:
            str: Значение в строковом формате.
        """
        return str(value)


class CategoryYamlSerializer(serializers.Serializer):
    """
    Проверяет данные категории из YAML-файла поставщика.
    """

    id = serializers.IntegerField(min_value=1)
    name = serializers.CharField(max_length=100)


class ProductYamlSerializer(serializers.Serializer):
    """
    Проверяет товарное предложение из YAML-файла.

    Контролирует идентификаторы, стоимость, остаток
    и структуру характеристик товара.
    """

    id = serializers.IntegerField(min_value=1)
    category = serializers.IntegerField(min_value=1)
    model = serializers.CharField(
        max_length=255,
        allow_blank=True,
        required=False,
        default="",
    )
    name = serializers.CharField(max_length=255)

    price = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.01"),
    )

    price_rrc = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.01"),
    )

    quantity = serializers.IntegerField(min_value=0)

    parameters = serializers.DictField(
        child=ParameterValueField(),
        required=False,
        default=dict,
    )

    def validate_parameters(self, value):
        """
        Проверяет названия характеристик товара.

        Args:
            value (dict): Характеристики из YAML-файла.

        Returns:
            dict: Проверенные характеристики.

        Raises:
            ValidationError: Если название характеристики некорректно.
        """
        for name in value:
            if not isinstance(name, str) or not name.strip():
                raise serializers.ValidationError(
                    "Название характеристики не может быть пустым."
                )

            if len(name) > 100:
                raise serializers.ValidationError(
                    "Название характеристики не должно превышать 100 символов."
                )

        return value


class CatalogYamlSerializer(serializers.Serializer):
    """
    Проверяет структуру каталога поставщика.

    Контролирует корректность категорий и товаров,
    уникальность внешних идентификаторов и существование
    категорий, на которые ссылаются товары.
    """

    shop = serializers.CharField(max_length=100)
    categories = CategoryYamlSerializer(
        many=True,
        allow_empty=False,
    )
    goods = ProductYamlSerializer(
        many=True,
        allow_empty=False,
    )

    def validate(self, attrs):
        """
        Выполняет проверки связей и уникальности данных.

        Args:
            attrs (dict): Проверенные поля каталога.

        Returns:
            dict: Данные каталога после валидации.

        Raises:
            ValidationError: При обнаружении дубликатов
                или ссылок на неизвестные категории.
        """
        categories = attrs["categories"]
        goods = attrs["goods"]

        category_ids = [item["id"] for item in categories]
        category_names = [item["name"] for item in categories]
        product_ids = [item["id"] for item in goods]

        if len(category_ids) != len(set(category_ids)):
            raise serializers.ValidationError("Обнаружены повторяющиеся ID категорий.")

        if len(category_names) != len(set(category_names)):
            raise serializers.ValidationError(
                "Обнаружены повторяющиеся названия категорий."
            )

        if len(product_ids) != len(set(product_ids)):
            raise serializers.ValidationError("Обнаружены повторяющиеся ID товаров.")

        known_categories = set(category_ids)

        for item in goods:
            if item["category"] not in known_categories:
                raise serializers.ValidationError(
                    f"Товар {item['id']} ссылается "
                    f"на неизвестную категорию {item['category']}."
                )

        return attrs


def validate_catalog_data(data: dict[str, Any]) -> dict[str, Any]:
    """
    Проверяет и нормализует данные каталога поставщика.

    Args:
        data (dict[str, Any]): Данные, полученные из YAML-файла.

    Returns:
        dict[str, Any]: Проверенный каталог с нормализованными значениями.

    Raises:
        CatalogImportError: Если структура или данные каталога
            не соответствуют требованиям.
    """
    serializer = CatalogYamlSerializer(data=data)

    if not serializer.is_valid():
        raise CatalogImportError(f"Ошибки валидации каталога: {serializer.errors}")

    validated_data = serializer.validated_data

    if not isinstance(validated_data, dict):
        raise CatalogImportError("Результат валидации каталога должен быть словарём.")

    return validated_data
