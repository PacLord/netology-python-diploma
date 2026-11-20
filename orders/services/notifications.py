import logging
from decimal import Decimal

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from orders.models import Order, OrderItem

logger = logging.getLogger(__name__)


def send_order_notifications(order_id: int) -> None:
    """
    Отправляет уведомления об оформленном заказе.

    Покупателю отправляет подтверждение покупки,
    администратору — накладную с товарами и адресом.

    Для расчётов использует цены и данные доставки,
    сохранённые на момент оформления заказа.

    Ошибки отправки записывает в журнал и не
    прерывает отправку второго письма.

    Args:
        order_id (int): Идентификатор оформленного заказа.

    Returns:
        None: Результат отправки фиксируется в журнале.
    """
    order = Order.objects.select_related("user").get(pk=order_id)

    if order.state == Order.Status.BASKET:
        logger.error(
            "Нельзя отправить уведомление о корзине №%s.",
            order_id,
        )
        return

    if order.placed_at is None:
        logger.error(
            "У заказа №%s отсутствует дата оформления.",
            order_id,
        )
        return

    items = OrderItem.objects.filter(
        order_id=order_id,
    ).order_by("pk")

    delivery = order.delivery_data

    recipient = " ".join(
        str(delivery.get(field, ""))
        for field in ("last_name", "first_name", "middle_name")
        if delivery.get(field)
    )

    address = ", ".join(
        str(delivery.get(field, ""))
        for field in (
            "city",
            "street",
            "house",
            "structure",
            "building",
            "apartment",
        )
        if delivery.get(field)
    )

    lines = [
        f"Заказ №{order.pk}",
        (f"Дата оформления: {timezone.localtime(order.placed_at):%d.%m.%Y %H:%M}"),
        "",
        f"Получатель: {recipient}",
        f"Телефон: {delivery.get('phone', '')}",
        f"Email: {delivery.get('email', '')}",
        f"Адрес доставки: {address}",
        "",
        "Состав заказа:",
    ]

    total_sum = Decimal("0.00")

    for index, item in enumerate(items, start=1):
        price = item.price_at_order

        if price is None:
            logger.error(
                "У позиции №%s заказа №%s не сохранена цена.",
                item.pk,
                order_id,
            )
            return

        item_total = price * item.quantity
        total_sum += item_total

        lines.extend(
            [
                (f"{index}. {item.product_name_at_order} ({item.shop_name_at_order})"),
                (f"   {item.quantity} × {price:.2f} = {item_total:.2f} руб."),
            ]
        )

    lines.extend(
        [
            "",
            f"Итого: {total_sum:.2f} руб.",
        ]
    )

    order_details = "\n".join(lines)

    messages = [
        (
            f"Подтверждение заказа №{order.pk}",
            (f"Ваш заказ успешно оформлен.\n\n{order_details}\n\nСпасибо за покупку!"),
            order.user.email,
        ),
        (
            f"Накладная по заказу №{order.pk}",
            (f"Поступил новый заказ для исполнения.\n\n{order_details}"),
            settings.ORDER_NOTIFICATION_EMAIL,
        ),
    ]

    for subject, body, email in messages:
        if not email:
            logger.error(
                "Не указан адрес получателя письма по заказу №%s: %s",
                order_id,
                subject,
            )
            continue

        try:
            sent_count = send_mail(
                subject=subject,
                message=body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[email],
                fail_silently=False,
            )

            if sent_count != 1:
                logger.error(
                    "Письмо по заказу №%s не отправлено: %s",
                    order_id,
                    subject,
                )

        except Exception:
            logger.exception(
                "Ошибка отправки письма по заказу №%s: %s",
                order_id,
                subject,
            )


def send_order_status_notification(
    *,
    order_id: int,
    old_state: str,
    new_state: str,
) -> None:
    """
    Отправляет покупателю уведомление об изменении статуса.

    Получает сведения о заказе из базы данных
    и отправляет письмо владельцу заказа.

    Ошибки отправки записываются в журнал и
    не влияют на уже сохранённое изменение статуса.

    Args:
        order_id (int): Идентификатор заказа.
        old_state (str): Предыдущий статус заказа.
        new_state (str): Новый статус заказа.

    Returns:
        None: Результат отправки фиксируется в журнале.
    """
    try:
        order = Order.objects.select_related("user").get(pk=order_id)

        old_label = Order.Status(old_state).label
        new_label = Order.Status(new_state).label

        subject = f"Изменение статуса заказа №{order_id}"

        message = (
            f"Здравствуйте!\n\n"
            f"Статус вашего заказа №{order_id} изменён.\n\n"
            f"Предыдущий статус: {old_label}\n"
            f"Текущий статус: {new_label}\n\n"
            f"Спасибо за покупку!"
        )

        sent_count = send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[order.user.email],
            fail_silently=False,
        )

        if sent_count != 1:
            logger.error(
                "Не удалось отправить уведомление об изменении статуса заказа №%s.",
                order_id,
            )

    except Exception:
        logger.exception(
            "Ошибка отправки уведомления об изменении статуса заказа №%s.",
            order_id,
        )
