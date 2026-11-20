from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import NotFound, ValidationError

from catalog.models import ProductInfo
from orders.models import Order, OrderItem
from orders.services.notifications import send_order_status_notification

# Разрешённые переходы между статусами заказа.
ALLOWED_STATUS_TRANSITIONS: dict[str, set[str]] = {
    Order.Status.NEW: {
        Order.Status.CONFIRMED,
        Order.Status.CANCELED,
    },
    Order.Status.CONFIRMED: {
        Order.Status.ASSEMBLED,
        Order.Status.CANCELED,
    },
    Order.Status.ASSEMBLED: {
        Order.Status.SENT,
        Order.Status.CANCELED,
    },
    Order.Status.SENT: {
        Order.Status.DELIVERED,
    },
    Order.Status.DELIVERED: set(),
    Order.Status.CANCELED: set(),
}


@transaction.atomic
def change_order_status(
    *,
    order_id: int,
    new_state: str,
) -> Order:
    """
    Изменяет статус оформленного заказа.

    Проверяет допустимость перехода и блокирует
    заказ на время изменения.

    При отмене заказа восстанавливает остатки товаров.
    Повторная отмена запрещена, чтобы исключить
    повторное увеличение складских остатков.

    Args:
        order_id (int): Идентификатор заказа.
        new_state (str): Новый статус заказа.

    Returns:
        Order: Заказ с обновлённым статусом.

    Raises:
        NotFound: Если заказ не найден или является корзиной.
        ValidationError: Если переход статуса запрещён
            или невозможно восстановить остатки товаров.
    """
    # Блокируем заказ от параллельных изменений.
    order = get_object_or_404(
        Order.objects.select_for_update(),
        pk=order_id,
    )

    # Корзина не является оформленным заказом.
    if order.state == Order.Status.BASKET:
        raise NotFound("Оформленный заказ не найден.")

    # Проверяем разрешённые переходы.
    allowed_states = ALLOWED_STATUS_TRANSITIONS.get(
        order.state,
        set(),
    )

    if new_state not in allowed_states:
        raise ValidationError(
            {
                "state": [
                    f"Недопустимый переход из статуса '{order.state}' в '{new_state}'."
                ]
            }
        )

    # При отмене возвращаем товары на склад.
    if new_state == Order.Status.CANCELED:
        items = list(
            OrderItem.objects.filter(
                order_id=order.pk,
            ).order_by("product_info_id")
        )

        product_ids = [item.product_info_id for item in items]

        # Блокируем предложения в постоянном порядке.
        products = (
            ProductInfo.objects.filter(pk__in=product_ids)
            .select_for_update(of=("self",))
            .order_by("pk")
            .in_bulk()
        )

        # Проверяем наличие всех предложений.
        if len(products) != len(items):
            raise ValidationError(
                {
                    "state": [
                        "Не удалось найти все товарные "
                        "предложения для восстановления остатков."
                    ]
                }
            )

        # Возвращаем ранее списанные количества.
        for item in items:
            product = products[item.product_info_id]

            product.quantity += item.quantity

            product.save(
                update_fields=["quantity"],
            )

    # Запоминаем предыдущий статус.
    old_state = order.state

    # Изменяем статус после всех проверок.
    order.state = new_state

    order.save(
        update_fields=["state"],
    )

    # Запоминаем ID для уведомления.
    saved_order_id = int(order.pk)

    def notify_after_commit() -> None:
        """
        Отправляет уведомление после сохранения статуса.

        Returns:
            None: Результат фиксируется сервисом уведомлений.
        """
        send_order_status_notification(
            order_id=saved_order_id,
            old_state=old_state,
            new_state=new_state,
        )

    transaction.on_commit(
        notify_after_commit,
        robust=True,
    )

    return order
