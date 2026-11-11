
from django.contrib.auth.base_user import BaseUserManager


class UserManager(BaseUserManager):
    """
    Менеджер пользовательской модели с авторизацией по email.

    Обеспечивает создание обычных пользователей и суперпользователей
    без использования стандартного поля username.
    """
    use_in_migrations = True

    def create_user(self, email, password=None, **extra_fields):
        """
        Создаёт и сохраняет обычного пользователя.

        Args:
            email (str): Электронная почта пользователя.
            password (str | None): Пароль в открытом виде.
                Перед сохранением преобразуется в хеш.
            **extra_fields: Дополнительные поля модели пользователя.

        Returns:
            User: Созданный экземпляр пользователя.

        Raises:
            ValueError: Если не указан email.
        """
        if not email:
            raise ValueError("Email обязателен")

        email = self.normalize_email(email)

        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)

        return user

    def create_superuser(self, email, password, **extra_fields):
        """
        Создаёт суперпользователя с административными правами.

        Args:
            email (str): Электронная почта администратора.
            password (str): Пароль администратора.
            **extra_fields: Дополнительные поля пользователя.

        Returns:
            User: Созданный суперпользователь.

        Raises:
            ValueError: Если обязательные административные флаги
                не установлены в True или не указан email.
        """
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser должен иметь is_staff=True")

        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser должен иметь is_superuser=True")

        if extra_fields.get("is_active") is not True:
            raise ValueError("Superuser должен быть активным")

        return self.create_user(email, password, **extra_fields)
