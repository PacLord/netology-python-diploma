from urllib.parse import urlencode

from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse

from users.models import User


def build_confirmation_url(
    *,
    email: str,
    token: str,
) -> str:
    """
    Формирует ссылку для подтверждения электронной почты.

    Использует публичный адрес приложения и именованный
    маршрут Django, добавляя email и токен в параметры URL.

    Args:
        email (str): Электронная почта пользователя.
        token (str): Исходный токен подтверждения email.

    Returns:
        str: Полная ссылка для подтверждения регистрации.
    """
    query_params = urlencode(
        {
            "email": email,
            "token": token,
        }
    )

    confirmation_path = reverse("users:register-confirm")

    return f"{settings.PUBLIC_BASE_URL}{confirmation_path}?{query_params}"


def send_confirmation_email(
    *,
    user: User,
    token: str,
) -> int:
    """
    Отправляет письмо для подтверждения электронной почты.

    Формирует письмо с персональной ссылкой активации
    и информацией о сроке её действия.

    Использует почтовый backend, настроенный в Django.

    Args:
        user (User): Пользователь, которому необходимо
            подтвердить электронную почту.
        token (str): Исходный токен подтверждения email.

    Returns:
        int: Количество писем, обработанных почтовым backend.
    """
    subject = "Подтверждение регистрации"

    confirmation_url = build_confirmation_url(
        email=user.email,
        token=token,
    )

    ttl_hours = settings.EMAIL_CONFIRMATION_TOKEN_TTL_SECONDS / 3600

    message = (
        f"Здравствуйте, {user.first_name}!\n\n"
        "Благодарим за регистрацию в системе "
        "автоматизации закупок.\n\n"
        "Для подтверждения электронной почты "
        "перейдите по следующей ссылке:\n\n"
        f"{confirmation_url}\n\n"
        f"Срок действия ссылки: {ttl_hours:g} ч.\n\n"
        "Если вы не регистрировались в нашей системе, "
        "проигнорируйте это письмо.\n\n"
    )

    return send_mail(
        subject=subject,
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )
