import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from users.models import EmailConfirmationToken, User


class EmailConfirmationError(ValueError):
    """
    Ошибка подтверждения электронной почты пользователя.

    Используется при невозможности создания или
    подтверждения токена активации учётной записи.
    """


def hash_confirmation_token(token: str) -> str:
    """
    Вычисляет SHA-256-хеш токена подтверждения email.

    Args:
        token (str): Исходный токен подтверждения.

    Returns:
        str: SHA-256-хеш токена в шестнадцатеричном формате.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@transaction.atomic
def generate_email_confirmation_token(user: User) -> str:
    """
    Генерирует токен подтверждения электронной почты.

    Создаёт случайный токен и сохраняет его хеш в базе данных.

    Если у пользователя уже существует токен,
    заменяет его новым и обновляет срок действия.

    Args:
        user (User): Неактивный пользователь, которому
            необходимо подтвердить электронную почту.

    Returns:
        str: Исходный токен для отправки пользователю.

    Raises:
        EmailConfirmationError: Если пользователь не сохранён
            или его учётная запись уже активирована.
    """
    if user.pk is None:
        raise EmailConfirmationError("Пользователь должен быть сохранён в базе данных.")

    # Блокируем запись пользователя на время операции.
    locked_user = User.objects.select_for_update().get(
        pk=user.pk,
    )

    if locked_user.is_active:
        raise EmailConfirmationError("Электронная почта пользователя уже подтверждена.")

    # Генерируем случайный токен.
    token = secrets.token_urlsafe(32)

    # Вычисляем хеш для хранения в базе данных.
    token_hash = hash_confirmation_token(token)

    now = timezone.now()

    expires_at = now + timedelta(
        seconds=settings.EMAIL_CONFIRMATION_TOKEN_TTL_SECONDS,
    )

    # Создаём новый токен или заменяем существующий.
    EmailConfirmationToken.objects.update_or_create(
        user=locked_user,
        defaults={
            "token_hash": token_hash,
            "created_at": now,
            "expires_at": expires_at,
        },
    )

    # Исходный токен нужен для отправки по email.
    return token


@transaction.atomic
def confirm_email(
    *,
    email: str,
    token: str,
) -> User:
    """
    Подтверждает электронную почту пользователя.

    Проверяет существование пользователя, соответствие
    токена сохранённому хешу и срок его действия.

    При успешной проверке активирует учётную запись
    и удаляет использованный токен подтверждения.

    Args:
        email (str): Электронная почта пользователя.
        token (str): Исходный токен подтверждения,
            полученный пользователем по email.

    Returns:
        User: Активированный экземпляр пользователя.

    Raises:
        EmailConfirmationError: Если пользователь или
            токен не найдены, токен недействителен,
            срок его действия истёк или учётная запись
            уже активирована.
    """
    email = email.strip().lower()

    # Блокируем пользователя на время подтверждения.
    user = User.objects.select_for_update().filter(email=email).first()

    if user is None or user.is_active:
        raise EmailConfirmationError("Недействительный токен подтверждения.")

    # Получаем сохранённый токен пользователя.
    token_record = EmailConfirmationToken.objects.filter(user=user).first()

    if token_record is None:
        raise EmailConfirmationError("Недействительный токен подтверждения.")

    # Проверяем соответствие токена сохранённому хешу.
    token_hash = hash_confirmation_token(token)

    if not secrets.compare_digest(
        token_hash,
        token_record.token_hash,
    ):
        raise EmailConfirmationError("Недействительный токен подтверждения.")

    # Проверяем срок действия токена.
    if token_record.expires_at <= timezone.now():
        raise EmailConfirmationError("Срок действия токена подтверждения истёк.")

    # Активируем учётную запись.
    user.is_active = True
    user.save(update_fields=["is_active"])

    # Использованный токен больше не нужен.
    token_record.delete()

    return user
