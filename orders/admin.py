from django.contrib import admin, messages
from django.db.models import QuerySet
from django.http import HttpRequest
from rest_framework.exceptions import NotFound, ValidationError

from orders.models import Order, OrderItem
from orders.services.statuses import change_order_status


class OrderItemInline(admin.TabularInline):
    """
    Отображает товарные позиции внутри заказа.

    Позволяет администратору просматривать
    состав заказа непосредственно на его странице.
    """

    model = OrderItem
    extra = 0

    raw_id_fields = ("product_info",)

    fields = (
        "product_info",
        "quantity",
        "price_at_order",
        "product_name_at_order",
        "shop_name_at_order",
    )

    # Показываем только сохранённые позиции.
    can_delete = False

    # Поля позиций доступны только для просмотра.
    readonly_fields = (
        "product_info",
        "quantity",
        "price_at_order",
        "product_name_at_order",
        "shop_name_at_order",
    )

    def has_add_permission(
        self,
        request: HttpRequest,
        obj: Order | None = None,
    ) -> bool:
        """
        Запрещает добавление позиций через Django Admin.

        Args:
            request (HttpRequest): HTTP-запрос администратора.
            obj (Order | None): Родительский заказ.

        Returns:
            bool: Всегда False.
        """
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    """
    Настраивает административный интерфейс заказов.

    Предоставляет список заказов, фильтрацию по статусу
    и возможность просмотра товарных позиций.
    """

    list_display = (
        "id",
        "user",
        "state",
        "created_at",
        "placed_at",
        "contact",
    )

    list_display_links = ("id",)

    list_filter = (
        "state",
        "created_at",
    )

    search_fields = ("user__email",)

    list_select_related = (
        "user",
        "contact",
    )

    readonly_fields = ("created_at",)

    inlines = (OrderItemInline,)

    actions = (
        "confirm_orders",
        "assemble_orders",
        "send_orders",
        "deliver_orders",
        "cancel_orders",
    )

    def get_readonly_fields(
        self,
        request: HttpRequest,
        obj: Order | None = None,
    ) -> tuple[str, ...]:
        """
        Запрещает прямое редактирование оформленного заказа.

        Сохраняет возможность просмотра данных
        и изменения статуса через административные действия.

        Args:
            request (HttpRequest): HTTP-запрос администратора.
            obj (Order | None): Редактируемый заказ.

        Returns:
            tuple[str, ...]: Поля только для чтения.
        """
        fields = tuple(super().get_readonly_fields(request, obj))

        if obj is not None:
            protected_fields = (
                "user",
                "state",
                "contact",
                "delivery_data",
                "placed_at",
            )

            return tuple(dict.fromkeys((*fields, *protected_fields)))

        return fields

    def has_add_permission(
        self,
        request: HttpRequest,
    ) -> bool:
        """
        Запрещает ручное создание заказов через админку.

        Args:
            request (HttpRequest): HTTP-запрос администратора.

        Returns:
            bool: Всегда False.
        """
        return False

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: Order | None = None,
    ) -> bool:
        """
        Запрещает удаление заказов через админку.

        Args:
            request (HttpRequest): HTTP-запрос администратора.
            obj (Order | None): Заказ.

        Returns:
            bool: Всегда False.
        """
        return False

    def _change_selected_orders_status(
        self,
        request: HttpRequest,
        queryset: QuerySet[Order],
        new_state: str,
    ) -> None:
        """
        Изменяет статус выбранных заказов через сервис.

        Обрабатывает каждый заказ отдельно, проверяет
        допустимость перехода и сообщает результат
        администратору.

        Args:
            request (HttpRequest): Запрос администратора.
            queryset (QuerySet[Order]): Выбранные заказы.
            new_state (str): Новый статус заказов.

        Returns:
            None: Результаты выводятся в Django Admin.
        """
        updated_count = 0

        for order in queryset.order_by("pk"):
            try:
                change_order_status(
                    order_id=int(order.pk),
                    new_state=new_state,
                )

            except (ValidationError, NotFound) as error:
                self.message_user(
                    request,
                    f"Заказ №{order.pk}: {error}",
                    level=messages.WARNING,
                )

            else:
                updated_count += 1

        if updated_count:
            state_label = Order.Status(new_state).label

            self.message_user(
                request,
                (f"Статус «{state_label}» установлен для заказов: {updated_count}."),
                level=messages.SUCCESS,
            )

    @admin.action(
        description="Подтвердить выбранные заказы",
        permissions=["change"],
    )
    def confirm_orders(
        self,
        request: HttpRequest,
        queryset: QuerySet[Order],
    ) -> None:
        """Переводит новые заказы в подтверждённые."""
        self._change_selected_orders_status(
            request,
            queryset,
            Order.Status.CONFIRMED,
        )

    @admin.action(
        description="Отметить заказы как собранные",
        permissions=["change"],
    )
    def assemble_orders(
        self,
        request: HttpRequest,
        queryset: QuerySet[Order],
    ) -> None:
        """Отмечает подтверждённые заказы как собранные."""
        self._change_selected_orders_status(
            request,
            queryset,
            Order.Status.ASSEMBLED,
        )

    @admin.action(
        description="Отметить заказы как отправленные",
        permissions=["change"],
    )
    def send_orders(
        self,
        request: HttpRequest,
        queryset: QuerySet[Order],
    ) -> None:
        """Отмечает собранные заказы как отправленные."""
        self._change_selected_orders_status(
            request,
            queryset,
            Order.Status.SENT,
        )

    @admin.action(
        description="Отметить заказы как доставленные",
        permissions=["change"],
    )
    def deliver_orders(
        self,
        request: HttpRequest,
        queryset: QuerySet[Order],
    ) -> None:
        """Отмечает отправленные заказы как доставленные."""
        self._change_selected_orders_status(
            request,
            queryset,
            Order.Status.DELIVERED,
        )

    @admin.action(
        description="Отменить выбранные заказы",
        permissions=["change"],
    )
    def cancel_orders(
        self,
        request: HttpRequest,
        queryset: QuerySet[Order],
    ) -> None:
        """Отменяет заказы с восстановлением остатков."""
        self._change_selected_orders_status(
            request,
            queryset,
            Order.Status.CANCELED,
        )


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    """
    Настраивает административный интерфейс позиций заказа.

    Позволяет просматривать товарные предложения,
    их количество и зафиксированную стоимость.
    """

    list_display = (
        "id",
        "order",
        "product_info",
        "quantity",
        "price_at_order",
    )

    list_display_links = ("id",)

    list_select_related = (
        "order",
        "product_info",
    )

    search_fields = (
        "order__user__email",
        "product_info__product__name",
    )

    raw_id_fields = (
        "order",
        "product_info",
    )

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Запрещает ручное создание позиций заказа."""
        return False

    def has_change_permission(
        self,
        request: HttpRequest,
        obj: OrderItem | None = None,
    ) -> bool:
        """Запрещает ручное изменение позиций заказа."""
        return False

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: OrderItem | None = None,
    ) -> bool:
        """Запрещает ручное удаление позиций заказа."""
        return False
