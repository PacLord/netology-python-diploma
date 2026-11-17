from django.contrib.auth import authenticate
from rest_framework.authtoken.models import Token

from users.models import User


class InvalidCredentialsError(ValueError):
    """
    Ошибка авторизации пользователя.

    Возникает при неверных учётных данных
    или неактивной учётной записи.
    """


def authenticate_user(
    *,
    email: str,
    password: str,
) -> str:
    """
    Авторизует пользователя и возвращает токен DRF.

    Находит пользователя по email без учёта регистра,
    проверяет пароль через стандартный backend Django
    и получает или создаёт токен авторизации.

    Не допускает авторизацию неактивных пользователей.

    Args:
        email (str): Электронная почта пользователя.
        password (str): Пароль пользователя.

    Returns:
        str: Токен авторизации пользователя.

    Raises:
        InvalidCredentialsError: Если email или пароль
            неверны либо учётная запись неактивна.
    """
    email = email.strip().lower()

    # Находим пользователя без учёта регистра email.
    existing_user = User.objects.filter(email__iexact=email).first()

    if existing_user is None:
        raise InvalidCredentialsError("Неверный email или пароль.")

    # Проверяем пароль и активность через Django.
    user = authenticate(
        username=existing_user.email,
        password=password,
    )

    if user is None:
        raise InvalidCredentialsError("Неверный email или пароль.")

    # Получаем существующий или создаём новый токен.
    token, _ = Token.objects.get_or_create(user=user)

    return token.key
