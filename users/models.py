from django.conf import settings
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
    # менеджер наследуется от BaseUserManager и использует email.
    objects: UserManager = UserManager()  # pyright: ignore[reportAssignmentType]

    class Meta:
        verbose_name = "Пользователь"
        verbose_name_plural = "Пользователи"
        ordering = ["email"]

    def __str__(self):
        return self.email


class EmailConfirmationToken(models.Model):
    """
    Токен подтверждения электронной почты пользователя.

    Используется для активации учётной записи после регистрации.

    Хранит хеш токена и срок его действия. Для каждого
    пользователя может существовать только один токен
    подтверждения электронной почты.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        verbose_name="Пользователь",
        on_delete=models.CASCADE,
        related_name="email_confirmation_token",
    )

    token_hash = models.CharField(
        verbose_name="Хеш токена",
        max_length=64,
        unique=True,
    )

    created_at = models.DateTimeField(
        verbose_name="Дата создания",
        auto_now_add=True,
    )

    expires_at = models.DateTimeField(
        verbose_name="Срок действия",
    )

    class Meta:
        verbose_name = "Токен подтверждения email"
        verbose_name_plural = "Токены подтверждения email"

    def __str__(self):
        """
        Возвращает строковое представление токена.

        Returns:
            str: Название и идентификатор токена.
        """
        return f"Токен подтверждения #{self.pk}"
