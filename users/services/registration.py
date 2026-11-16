from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from users.models import EmailConfirmationToken, User

from .email_confirmation import generate_email_confirmation_token
from .emails import send_confirmation_email


class EmailAlreadyExistsError(ValueError):
    """
    Ошибка регистрации пользователя с существующим email.

    Возникает, когда указанный адрес электронной почты
    уже принадлежит зарегистрированному пользователю.
    """


def register_user(
    *,
    email: str,
    password: str,
    first_name: str,
    last_name: str,
    company: str = "",
    position: str = "",
) -> User:
    """
    Создаёт нового пользователя системы закупок.

    Сохраняет покупателя с хешированным паролем
    и неактивным статусом до подтверждения email.

    Принимает данные, предварительно проверенные
    сериализатором регистрации.

    Args:
        email (str): Электронная почта пользователя.
        password (str): Пароль в открытом виде.
        first_name (str): Имя пользователя.
        last_name (str): Фамилия пользователя.
        company (str): Название компании.
        position (str): Должность пользователя.

    Returns:
        User: Созданный экземпляр пользователя.

    Raises:
        EmailAlreadyExistsError: Если пользователь с таким
            email уже зарегистрирован.
        IntegrityError: При других нарушениях ограничений
            целостности базы данных.
    """
    email = email.strip().lower()

    try:
        with transaction.atomic():
            if User.objects.filter(email__iexact=email).exists():
                raise EmailAlreadyExistsError(
                    "Пользователь с таким email уже существует."
                )

            user = User.objects.create_user(
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
                company=company,
                position=position,
                type=User.UserType.BUYER,
                is_active=False,
            )

    except IntegrityError as error:
        if User.objects.filter(email__iexact=email).exists():
            raise EmailAlreadyExistsError(
                "Пользователь с таким email уже существует."
            ) from error

        raise

    return user


def _send_registration_confirmation(
    *,
    user: User,
    token: str,
) -> None:
    """
    Отправляет письмо подтверждения после регистрации.

    Проверяет, что почтовый backend обработал письмо.

    Args:
        user (User): Зарегистрированный пользователь.
        token (str): Исходный токен подтверждения email.

    Raises:
        RuntimeError: Если почтовый backend не обработал письмо.
    """
    sent_count = send_confirmation_email(
        user=user,
        token=token,
    )

    if sent_count != 1:
        raise RuntimeError("Не удалось отправить письмо подтверждения.")


@transaction.atomic
def register_user_with_confirmation(
    *,
    email: str,
    password: str,
    first_name: str,
    last_name: str,
    company: str = "",
    position: str = "",
) -> User:
    """
    Регистрирует пользователя и инициирует подтверждение email.

    Создаёт неактивного пользователя, генерирует токен
    подтверждения и сохраняет его хеш в базе данных.

    Письмо отправляется только после успешного завершения
    транзакции. При ошибке сохранения пользователь и токен
    не сохраняются, а письмо не отправляется.

    Args:
        email (str): Электронная почта пользователя.
        password (str): Пароль в открытом виде.
        first_name (str): Имя пользователя.
        last_name (str): Фамилия пользователя.
        company (str): Название компании.
        position (str): Должность пользователя.

    Returns:
        User: Зарегистрированный неактивный пользователь.

    Raises:
        EmailAlreadyExistsError: Если указанный email
            уже зарегистрирован.
        EmailConfirmationError: Если невозможно создать
            токен подтверждения.
        IntegrityError: При нарушении ограничений базы данных.
    """
    # Создаём неактивного пользователя.
    user = register_user(
        email=email,
        password=password,
        first_name=first_name,
        last_name=last_name,
        company=company,
        position=position,
    )

    # Генерируем токен и сохраняем его хеш.
    token = generate_email_confirmation_token(user)

    def send_email_after_commit() -> None:
        """
        Отправляет письмо после сохранения пользователя и токена.
        """
        _send_registration_confirmation(
            user=user,
            token=token,
        )

    transaction.on_commit(
        send_email_after_commit,
        robust=True,
    )

    return user


@transaction.atomic
def resend_confirmation_email(*, email: str) -> None:
    """
    Повторно отправляет письмо подтверждения регистрации.

    Генерирует новый токен для существующего неактивного
    пользователя, если с момента предыдущей генерации
    прошло достаточно времени.

    Не сообщает о существовании или состоянии учётной
    записи, чтобы предотвратить перебор email-адресов.

    Письмо отправляется после успешного завершения
    транзакции.

    Args:
        email (str): Электронная почта пользователя.
    """
    email = email.strip().lower()

    # Блокируем пользователя на время операции.
    user = User.objects.select_for_update().filter(email=email).first()

    # Не отправляем письмо неизвестным или активным
    # пользователям.
    if user is None or user.is_active:
        return

    # Получаем существующий токен подтверждения.
    token_record = EmailConfirmationToken.objects.filter(
        user=user,
    ).first()

    # Ограничиваем частоту повторной отправки.
    if token_record is not None:
        next_allowed_at = token_record.created_at + timedelta(
            seconds=(settings.EMAIL_CONFIRMATION_RESEND_INTERVAL_SECONDS),
        )

        if timezone.now() < next_allowed_at:
            return

    # Генерируем новый токен.
    # Предыдущий токен становится недействительным.
    token = generate_email_confirmation_token(user)

    def send_email_after_commit() -> None:
        """
        Отправляет новое письмо после сохранения токена.
        """
        _send_registration_confirmation(
            user=user,
            token=token,
        )

    transaction.on_commit(
        send_email_after_commit,
        robust=True,
    )
