from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from users.models import User


class UserRegistrationSerializer(serializers.Serializer):
    """
    Проверяет данные для регистрации нового пользователя.

    Контролирует корректность электронной почты,
    уникальность пользователя и безопасность пароля.
    """

    email = serializers.EmailField(max_length=254)

    password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
    )

    first_name = serializers.CharField(max_length=150)

    last_name = serializers.CharField(max_length=150)

    company = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
        default="",
    )

    position = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
        default="",
    )

    def validate_email(self, value: str) -> str:
        """
        Проверяет уникальность электронной почты пользователя.

        Приводит email к нижнему регистру и проверяет,
        не зарегистрирован ли пользователь с таким адресом.

        Args:
            value (str): Электронная почта пользователя.

        Returns:
            str: Нормализованный адрес электронной почты.

        Raises:
            serializers.ValidationError: Если пользователь
                с таким адресом уже существует.
        """
        email = value.strip().lower()

        if User.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError(
                "Пользователь с таким email уже существует."
            )

        return email

    def validate(self, attrs):
        """
        Проверяет безопасность пароля с учётом данных пользователя.

        Использует стандартные валидаторы паролей Django,
        настроенные в AUTH_PASSWORD_VALIDATORS.

        Args:
            attrs (dict): Проверенные поля регистрации.

        Returns:
            dict: Данные пользователя после валидации.

        Raises:
            serializers.ValidationError: Если пароль
                не соответствует требованиям безопасности.
        """
        user = User(
            email=attrs["email"],
            first_name=attrs["first_name"],
            last_name=attrs["last_name"],
        )

        try:
            validate_password(
                password=attrs["password"],
                user=user,
            )

        except DjangoValidationError as error:
            raise serializers.ValidationError({"password": error.messages}) from error

        return attrs


class UserRegistrationResponseSerializer(serializers.Serializer):
    """
    Описывает результат успешной регистрации пользователя.

    Содержит публичные сведения о созданной учётной записи
    и сообщение о необходимости подтверждения email.
    """

    id = serializers.IntegerField()
    email = serializers.EmailField()
    is_active = serializers.BooleanField()
    detail = serializers.CharField()


class EmailConfirmationSerializer(serializers.Serializer):
    """
    Проверяет данные для подтверждения электронной почты.

    Принимает email пользователя и исходный токен,
    полученный в письме подтверждения регистрации.
    """

    email = serializers.EmailField(
        max_length=254,
    )

    token = serializers.CharField(
        max_length=128,
        trim_whitespace=False,
        write_only=True,
    )


class EmailConfirmationResponseSerializer(serializers.Serializer):
    """
    Описывает результат подтверждения электронной почты.

    Содержит сообщение об успешной активации
    и текущий статус учётной записи пользователя.
    """

    detail = serializers.CharField()
    is_active = serializers.BooleanField()


class UserLoginSerializer(serializers.Serializer):
    """
    Проверяет входные данные для авторизации пользователя.

    Принимает электронную почту и пароль, необходимые
    для проверки учётных данных пользователя.
    """

    email = serializers.EmailField(
        max_length=254,
    )

    password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
    )

    def validate_email(self, value: str) -> str:
        """
        Нормализует электронную почту пользователя.

        Удаляет пробелы по краям и приводит адрес
        к нижнему регистру.

        Args:
            value (str): Электронная почта пользователя.

        Returns:
            str: Нормализованный адрес электронной почты.
        """
        return value.strip().lower()


class UserLoginResponseSerializer(serializers.Serializer):
    """
    Описывает результат успешной авторизации.

    Содержит токен, который клиент должен использовать
    для последующих запросов к защищённым эндпоинтам API.
    """

    token = serializers.CharField()


class UserDetailsSerializer(serializers.ModelSerializer):
    """
    Представляет публичные данные профиля пользователя.

    Используется для получения информации о текущем
    авторизованном пользователе через REST API.

    Не включает пароль, административные права
    и другие служебные поля модели.
    """

    class Meta:
        model = User

        fields = (
            "id",
            "email",
            "first_name",
            "last_name",
            "company",
            "position",
            "type",
            "is_active",
        )

        read_only_fields = fields


class UserProfileUpdateSerializer(serializers.ModelSerializer):
    """
    Обновляет данные профиля авторизованного пользователя.

    Позволяет изменять персональные данные, email
    и пароль. Пароль сохраняется только в виде хеша.
    """

    password = serializers.CharField(
        write_only=True,
        required=False,
        trim_whitespace=False,
    )

    class Meta:
        model = User
        fields = (
            "first_name",
            "last_name",
            "email",
            "company",
            "position",
            "password",
        )
        extra_kwargs = {
            "email": {"required": False},
        }

    def validate_email(self, value: str) -> str:
        """
        Проверяет уникальность нового email.

        Исключает текущего пользователя из проверки,
        чтобы разрешить сохранение своего email без изменений.

        Args:
            value (str): Новый электронный адрес.

        Returns:
            str: Нормализованный email.

        Raises:
            serializers.ValidationError: Если адрес занят
                другим пользователем.
        """
        email = value.strip().lower()

        queryset = User.objects.filter(email__iexact=email)

        # Исключаем текущего пользователя, если он существует.
        if isinstance(self.instance, User):
            queryset = queryset.exclude(pk=self.instance.pk)

        if queryset.exists():
            raise serializers.ValidationError("Пользователь с таким email уже существует.")

        return email

    def validate_password(self, value: str) -> str:
        """
        Проверяет сложность нового пароля.

        Args:
            value (str): Новый пароль.

        Returns:
            str: Проверенный пароль.

        Raises:
            serializers.ValidationError: Если пароль слабый.
        """
        try:
            validate_password(value, user=self.instance)
        except DjangoValidationError as error:
            raise serializers.ValidationError(error.messages) from error

        return value

    def update(
        self,
        instance: User,
        validated_data: dict,
    ) -> User:
        """
        Сохраняет изменения профиля и пароля.

        Args:
            instance (User): Текущий пользователь.
            validated_data (dict): Проверенные данные.

        Returns:
            User: Обновлённый пользователь.
        """
        password = validated_data.pop("password", None)

        for field, value in validated_data.items():
            setattr(instance, field, value)

        if password is not None:
            instance.set_password(password)

        instance.save()
        return instance
