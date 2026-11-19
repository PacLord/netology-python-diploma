from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
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


class Contact(models.Model):
    """
    Контактные данные и адрес доставки покупателя.

    Каждый пользователь может сохранить несколько
    контактов с разными получателями и адресами.
    """

    MAX_CONTACTS_PER_USER = 5

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Пользователь",
        on_delete=models.CASCADE,
        related_name="contacts",
    )

    user_id: int | None

    last_name = models.CharField(
        verbose_name="Фамилия получателя",
        max_length=150,
    )

    first_name = models.CharField(
        verbose_name="Имя получателя",
        max_length=150,
    )

    middle_name = models.CharField(
        verbose_name="Отчество получателя",
        max_length=150,
        blank=True,
    )

    email = models.EmailField(
        verbose_name="Email получателя",
    )

    phone = models.CharField(
        verbose_name="Телефон",
        max_length=20,
    )

    city = models.CharField(
        verbose_name="Город",
        max_length=100,
    )

    street = models.CharField(
        verbose_name="Улица",
        max_length=150,
    )

    house = models.CharField(
        verbose_name="Дом",
        max_length=20,
        blank=True,
    )

    structure = models.CharField(
        verbose_name="Корпус",
        max_length=20,
        blank=True,
    )

    building = models.CharField(
        verbose_name="Строение",
        max_length=20,
        blank=True,
    )

    apartment = models.CharField(
        verbose_name="Квартира",
        max_length=20,
        blank=True,
    )

    class Meta:
        verbose_name = "Контакт"
        verbose_name_plural = "Контакты"
        ordering = ["id"]

    def clean(self) -> None:
        """
        Проверяет ограничение количества контактов пользователя.

        Разрешает хранить не более пяти адресов доставки.
        При редактировании существующего контакта
        исключает его из подсчёта.

        Raises:
            ValidationError: Если у пользователя уже
                сохранено максимальное количество контактов.
        """
        super().clean()

        if self.user_id is None:
            return

        contacts = Contact.objects.filter(
            user_id=self.user_id,
        )

        # При редактировании исключаем текущий контакт.
        if self.pk is not None:
            contacts = contacts.exclude(pk=self.pk)

        if contacts.count() >= self.MAX_CONTACTS_PER_USER:
            raise ValidationError(
                {"user": ("У пользователя может быть не более 5 адресов доставки.")}
            )

    def __str__(self) -> str:
        """
        Возвращает краткое представление контакта.

        Returns:
            str: Получатель и город доставки.
        """
        return f"{self.last_name} {self.first_name} ({self.city})"
