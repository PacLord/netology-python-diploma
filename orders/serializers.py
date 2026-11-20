from decimal import Decimal

from rest_framework import serializers

from orders.models import Order, OrderItem


class BasketItemSerializer(serializers.ModelSerializer):
    """
    Представляет товарную позицию корзины.

    Возвращает товар, магазин, актуальную цену,
    количество и стоимость позиции.
    """

    product_info_id = serializers.IntegerField(
        read_only=True,
    )

    product_name = serializers.CharField(
        source="product_info.product.name",
        read_only=True,
    )

    shop_name = serializers.CharField(
        source="product_info.shop.name",
        read_only=True,
    )

    price = serializers.DecimalField(
        source="product_info.price",
        max_digits=12,
        decimal_places=2,
        read_only=True,
    )

    total = serializers.SerializerMethodField()

    class Meta:
        model = OrderItem

        fields = (
            "id",
            "product_info_id",
            "product_name",
            "shop_name",
            "price",
            "quantity",
            "total",
        )

        read_only_fields = fields

    def get_total(self, obj: OrderItem) -> str:
        """
        Вычисляет стоимость товарной позиции.

        Args:
            obj (OrderItem): Позиция корзины.

        Returns:
            str: Цена, умноженная на количество.
        """
        total = obj.product_info.price * obj.quantity

        return f"{total:.2f}"


class BasketSerializer(serializers.ModelSerializer):
    """
    Представляет корзину текущего пользователя.

    Включает товарные позиции и общую стоимость,
    рассчитанную по актуальным ценам поставщиков.
    """

    ordered_items = BasketItemSerializer(
        many=True,
        read_only=True,
    )

    total_sum = serializers.SerializerMethodField()

    class Meta:
        model = Order

        fields = (
            "id",
            "state",
            "created_at",
            "ordered_items",
            "total_sum",
        )

        read_only_fields = fields

    def get_total_sum(self, obj: Order) -> str:
        """
        Вычисляет общую стоимость корзины.

        Args:
            obj (Order): Корзина пользователя.

        Returns:
            str: Общая стоимость товаров.
        """
        items = getattr(obj, "ordered_items").all()

        total = sum(
            (item.product_info.price * item.quantity for item in items),
            Decimal("0.00"),
        )

        return f"{total:.2f}"


class BasketAddItemSerializer(serializers.Serializer):
    """
    Проверяет товарную позицию для добавления в корзину.

    Принимает идентификатор товарного предложения
    и положительное целочисленное количество.
    """

    product_info_id = serializers.IntegerField(
        min_value=1,
        help_text="Идентификатор товарного предложения (ProductInfo).",
    )

    quantity = serializers.IntegerField(
        min_value=1,
        help_text="Количество добавляемого товара.",
    )


class BasketAddSerializer(serializers.Serializer):
    """
    Проверяет запрос на добавление товаров в корзину.

    Принимает непустой массив товарных позиций.
    """

    items = BasketAddItemSerializer(
        many=True,
        allow_empty=False,
    )


class BasketUpdateItemSerializer(serializers.Serializer):
    """
    Проверяет данные изменения позиции корзины.

    Принимает идентификатор позиции заказа
    и новое количество товара.

    Нулевое количество означает удаление позиции.
    """

    order_item_id = serializers.IntegerField(
        min_value=1,
        help_text="ID позиции корзины (OrderItem).",
    )

    quantity = serializers.IntegerField(
        min_value=0,
        help_text=(
            "Новое количество товара. При значении 0 позиция удаляется из корзины."
        ),
    )


class BasketUpdateSerializer(serializers.Serializer):
    """
    Проверяет запрос на обновление позиций корзины.

    Принимает непустой массив существующих позиций
    и их новые количества.
    """

    items = BasketUpdateItemSerializer(
        many=True,
        allow_empty=False,
    )


class BasketDeleteSerializer(serializers.Serializer):
    """
    Проверяет список позиций для удаления из корзины.

    Принимает непустой список идентификаторов OrderItem.
    """

    order_item_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
        help_text="Список ID удаляемых позиций корзины.",
    )

    def validate_order_item_ids(self, value):
        """
        Проверяет уникальность идентификаторов позиций.

        Args:
            value (list[int]): Список идентификаторов.

        Returns:
            list[int]: Проверенные идентификаторы.

        Raises:
            serializers.ValidationError: Если обнаружены
                повторяющиеся идентификаторы.
        """
        if len(value) != len(set(value)):
            raise serializers.ValidationError(
                "Идентификаторы позиций не должны повторяться."
            )

        return value


class BasketDeleteResponseSerializer(serializers.Serializer):
    """
    Описывает результат удаления позиций корзины.

    Содержит количество успешно удалённых записей.
    """

    deleted = serializers.IntegerField(
        help_text="Количество удалённых позиций корзины.",
    )


class OrderPlaceSerializer(serializers.Serializer):
    """
    Проверяет данные для оформления заказа.

    Принимает идентификатор корзины пользователя
    и идентификатор выбранного контакта доставки.
    """

    basket_id = serializers.IntegerField(
        min_value=1,
        help_text=("ID корзины пользователя (Order со статусом basket)."),
    )

    contact_id = serializers.IntegerField(
        min_value=1,
        help_text="ID контакта доставки пользователя.",
    )


class OrderPlaceResponseSerializer(serializers.Serializer):
    """
    Описывает результат успешного оформления заказа.

    Возвращает номер заказа, статус, дату оформления
    и итоговую стоимость покупки.
    """

    id = serializers.IntegerField()
    state = serializers.ChoiceField(
        choices=Order.Status.choices,
    )
    placed_at = serializers.DateTimeField()
    total_sum = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
    )


class OrderHistoryItemSerializer(serializers.ModelSerializer):
    """
    Представляет товарную позицию оформленного заказа.

    Использует сведения, сохранённые на момент
    оформления покупки, а не текущие данные каталога.
    """

    product_info_id = serializers.IntegerField(
        read_only=True,
    )

    product_name = serializers.CharField(
        source="product_name_at_order",
        read_only=True,
    )

    shop_name = serializers.CharField(
        source="shop_name_at_order",
        read_only=True,
    )

    price = serializers.DecimalField(
        source="price_at_order",
        max_digits=12,
        decimal_places=2,
        read_only=True,
        allow_null=True,
    )

    total = serializers.SerializerMethodField()

    class Meta:
        model = OrderItem

        fields = (
            "id",
            "product_info_id",
            "product_name",
            "shop_name",
            "price",
            "quantity",
            "total",
        )

        read_only_fields = fields

    def get_total(self, obj: OrderItem) -> str | None:
        """
        Вычисляет стоимость позиции оформленного заказа.

        Args:
            obj (OrderItem): Товарная позиция заказа.

        Returns:
            str | None: Стоимость позиции или None,
                если историческая цена отсутствует.
        """
        if obj.price_at_order is None:
            return None

        total = obj.price_at_order * obj.quantity

        return f"{total:.2f}"


class OrderHistorySerializer(serializers.ModelSerializer):
    """
    Представляет оформленный заказ пользователя.

    Возвращает статус, дату, состав заказа,
    зафиксированные реквизиты доставки и общую сумму.
    """

    ordered_items = OrderHistoryItemSerializer(
        many=True,
        read_only=True,
    )

    total_sum = serializers.SerializerMethodField()

    class Meta:
        model = Order

        fields = (
            "id",
            "state",
            "placed_at",
            "delivery_data",
            "ordered_items",
            "total_sum",
        )

        read_only_fields = fields

    def get_total_sum(self, obj: Order) -> str | None:
        """
        Вычисляет общую стоимость оформленного заказа.

        Использует зафиксированные цены позиций.

        Args:
            obj (Order): Оформленный заказ пользователя.

        Returns:
            str | None: Общая стоимость или None,
                если у позиции отсутствует историческая цена.
        """
        items = obj.ordered_items.all()

        total = Decimal("0.00")

        for item in items:
            if item.price_at_order is None:
                return None

            total += item.price_at_order * item.quantity

        return f"{total:.2f}"


class SupplierOrderSerializer(serializers.ModelSerializer):
    """
    Представляет заказ для конкретного поставщика.

    Возвращает только товарные позиции его магазина
    и сумму этих позиций. Использует зафиксированные
    при оформлении цены и реквизиты доставки.
    """

    ordered_items = OrderHistoryItemSerializer(
        source="supplier_items",
        many=True,
        read_only=True,
    )

    supplier_total = serializers.SerializerMethodField()

    class Meta:
        model = Order

        fields = (
            "id",
            "state",
            "placed_at",
            "delivery_data",
            "ordered_items",
            "supplier_total",
        )

        read_only_fields = fields

    def get_supplier_total(self, obj: Order) -> str | None:
        """
        Вычисляет стоимость позиций одного поставщика.

        Использует только предварительно отфильтрованные
        позиции и цены на момент оформления заказа.

        Args:
            obj (Order): Оформленный заказ.

        Returns:
            str | None: Сумма товаров поставщика
                или None при отсутствии сохранённой цены.
        """
        items: list[OrderItem] = getattr(
            obj,
            "supplier_items",
            [],
        )

        total = Decimal("0.00")

        for item in items:
            if item.price_at_order is None:
                return None

            total += item.price_at_order * item.quantity

        return f"{total:.2f}"


class OrderStatusUpdateSerializer(serializers.Serializer):
    """
    Проверяет запрос на изменение статуса заказа.

    Разрешает выбирать только статусы оформленного
    заказа. Статус basket исключён, поскольку корзина
    не является оформленным заказом.
    """

    state = serializers.ChoiceField(
        choices=[
            (value, label)
            for value, label in Order.Status.choices
            if value != Order.Status.BASKET
        ],
        help_text="Новый статус оформленного заказа.",
    )


class OrderListFilterSerializer(serializers.Serializer):
    """
    Проверяет параметры фильтрации списка заказов.

    Позволяет отбирать оформленные заказы
    по одному из доступных статусов.

    Если статус не указан, фильтрация
    по состоянию заказа не применяется.
    """

    state = serializers.ChoiceField(
        choices=[
            (value, label)
            for value, label in Order.Status.choices
            if value != Order.Status.BASKET
        ],
        required=False,
        help_text=(
            "Необязательный фильтр по статусу заказа. "
            "Если не указан, возвращаются все "
            "оформленные заказы."
        ),
    )
