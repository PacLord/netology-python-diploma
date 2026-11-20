from decimal import Decimal
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from users.models import Contact


class Order(models.Model):
    """
    Корзина или оформленный заказ пользователя.

    Корзина хранится как заказ со статусом basket.
    После оформления заказ получает статус new.

    Сохраняет дату оформления и копию реквизитов доставки,
    чтобы изменения или удаление контакта не влияли
    на историю заказов.
    """

    class Status(models.TextChoices):
        BASKET = "basket", "Корзина"
        NEW = "new", "Новый"
        CONFIRMED = "confirmed", "Подтверждён"
        ASSEMBLED = "assembled", "Собран"
        SENT = "sent", "Отправлен"
        DELIVERED = "delivered", "Доставлен"
        CANCELED = "canceled", "Отменён"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Пользователь",
        on_delete=models.CASCADE,
        related_name="orders",
    )

    user_id: int | None

    state = models.CharField(
        verbose_name="Статус заказа",
        max_length=15,
        choices=Status.choices,
        default=Status.BASKET,
        db_index=True,
    )

    created_at = models.DateTimeField(
        verbose_name="Дата создания",
        auto_now_add=True,
    )

    placed_at = models.DateTimeField(
        verbose_name="Дата оформления заказа",
        null=True,
        blank=True,
    )

    contact = models.ForeignKey(
        "users.Contact",
        verbose_name="Контакт доставки",
        on_delete=models.SET_NULL,
        related_name="orders",
        null=True,
        blank=True,
    )

    contact_id: int | None

    delivery_data = models.JSONField(
        verbose_name="Данные доставки на момент оформления",
        default=dict,
        blank=True,
    )

    if TYPE_CHECKING:
        ordered_items: models.Manager["OrderItem"]

    class Meta:
        verbose_name = "Заказ"
        verbose_name_plural = "Заказы"
        ordering = ["-created_at"]

        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(state="basket"),
                name="unique_user_active_basket",
            ),
        ]

    def clean(self) -> None:
        """
        Проверяет принадлежность контакта владельцу заказа.

        Контакт доставки должен принадлежать пользователю,
        который создаёт заказ. Отсутствие контакта разрешено
        для корзины и ранее оформленных заказов.

        Raises:
            ValidationError: Если контакт доставки
                принадлежит другому пользователю.
        """
        super().clean()

        if self.user_id is None or self.contact_id is None:
            return

        contact_exists = Contact.objects.filter(
            pk=self.contact_id,
            user_id=self.user_id,
        ).exists()

        if not contact_exists:
            raise ValidationError(
                {"contact": ("Контакт доставки должен принадлежать владельцу заказа.")}
            )

    def __str__(self) -> str:
        """
        Возвращает строковое представление заказа.

        Returns:
            str: Номер заказа и название его статуса.
        """
        return f"Заказ №{self.pk} — {self.Status(self.state).label}"


class OrderItem(models.Model):
    """
    Товарная позиция корзины или оформленного заказа.

    Ссылается на предложение конкретного магазина.
    При оформлении заказа сохраняет цену и названия
    товара и магазина для неизменяемой истории покупки.
    """

    order = models.ForeignKey(
        Order,
        verbose_name="Заказ",
        on_delete=models.CASCADE,
        related_name="ordered_items",
    )

    order_id: int | None

    product_info = models.ForeignKey(
        "catalog.ProductInfo",
        verbose_name="Товарное предложение",
        on_delete=models.PROTECT,
        related_name="order_items",
    )

    product_info_id: int | None

    quantity = models.PositiveIntegerField(
        verbose_name="Количество",
        validators=[MinValueValidator(1)],
    )

    price_at_order = models.DecimalField(
        verbose_name="Цена на момент оформления",
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
        null=True,
        blank=True,
    )

    product_name_at_order = models.CharField(
        verbose_name="Название товара при оформлении",
        max_length=255,
        blank=True,
    )

    shop_name_at_order = models.CharField(
        verbose_name="Название магазина при оформлении",
        max_length=100,
        blank=True,
    )

    class Meta:
        verbose_name = "Позиция заказа"
        verbose_name_plural = "Позиции заказов"

        constraints = [
            models.UniqueConstraint(
                fields=["order", "product_info"],
                name="unique_order_product_info",
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gte=1),
                name="order_item_quantity_gte_1",
            ),
        ]

    def __str__(self) -> str:
        """
        Возвращает строковое представление позиции.

        Returns:
            str: Номер заказа и идентификатор предложения.
        """
        return f"Заказ №{self.order_id}, предложение №{self.product_info_id}"
