from urllib.parse import urlencode

from django.conf import settings
from django.core.mail import send_mail
from django.dispatch import receiver
from django.urls import reverse
from django_rest_passwordreset.models import ResetPasswordToken
from django_rest_passwordreset.signals import (
    post_password_reset,
    reset_password_token_created,
)
from rest_framework.authtoken.models import Token

from users.models import User


@receiver(
    reset_password_token_created,
    dispatch_uid="users.send_password_reset_email",
)
def send_password_reset_email(
    sender: type,
    instance: object,
    reset_password_token: ResetPasswordToken,
    **kwargs: object,
) -> None:
    """
    Отправляет письмо с токеном восстановления пароля.

    Вызывается автоматически после получения токена
    библиотекой django-rest-passwordreset.

    Args:
        sender (type): Класс, отправивший сигнал.
        instance (object): Экземпляр представления библиотеки.
        reset_password_token (ResetPasswordToken):
            Объект токена восстановления пароля.
        **kwargs: Дополнительные аргументы сигнала.
    """
    user = reset_password_token.user

    subject = "Восстановление пароля"

    # Формируем ссылку на HTML-страницу восстановления.
    reset_path = reverse("users:password-reset-confirm")

    query_params = urlencode(
        {
            "token": reset_password_token.key,
        }
    )

    reset_url = f"{settings.PUBLIC_BASE_URL}{reset_path}?{query_params}"

    message = (
        f"Здравствуйте, {user.first_name}!\n\n"
        "Вы запросили восстановление пароля "
        "в системе автоматизации закупок.\n\n"
        "Для установки нового пароля "
        "перейдите по следующей ссылке:\n\n"
        f"{reset_url}\n\n"
        "Срок действия ссылки: 24 часа.\n\n"
        "Если вы не запрашивали восстановление пароля, "
        "проигнорируйте это письмо."
    )

    send_mail(
        subject=subject,
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )


@receiver(
    post_password_reset,
    dispatch_uid="users.revoke_auth_token_after_password_reset",
)
def revoke_auth_token_after_password_reset(
    sender: type,
    user: User,
    reset_password_token: ResetPasswordToken,
    **kwargs: object,
) -> None:
    """
    Отзывает токен авторизации после восстановления пароля.

    Удаляет существующий DRF Token пользователя.
    После этого для доступа к защищённым API
    потребуется повторная авторизация.

    Args:
        sender (type): Класс, отправивший сигнал.
        user (User): Пользователь, сменивший пароль.
        reset_password_token (ResetPasswordToken):
            Использованный токен восстановления.
        **kwargs: Дополнительные аргументы сигнала.
    """
    Token.objects.filter(user=user).delete()
