from django.contrib.auth.models import AbstractUser
from django.db import models

from .managers import UserManager


class User(AbstractUser):
    """
    Пользователь системы автоматизации закупок.

    Поддерживает покупателей и поставщиков.
    Использует уникальный email вместо username для авторизации.
    Новые учётные записи требуют подтверждения электронной почты.
    """

    class UserType(models.TextChoices):
        BUYER = "buyer", "Покупатель"
        SHOP = "shop", "Поставщик"

    username = None

    email = models.EmailField(
        verbose_name="Email",
        unique=True,
    )

    type = models.CharField(
        verbose_name="Тип пользователя",
        max_length=5,
        choices=UserType.choices,
        default=UserType.BUYER,
    )

    company = models.CharField(
        verbose_name="Компания",
        max_length=100,
        blank=True,
    )

    position = models.CharField(
        verbose_name="Должность",
        max_length=100,
        blank=True,
    )

    is_active = models.BooleanField(
        verbose_name="Активен",
        default=False,
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    # AbstractUser типизирован под стандартный менеджер Django.
    # Наш менеджер наследуется от BaseUserManager и использует email.
    objects = UserManager()  # pyright: ignore[reportAssignmentType]

    class Meta:
        verbose_name = "Пользователь"
        verbose_name_plural = "Пользователи"
        ordering = ["email"]

    def __str__(self):
        return self.email
