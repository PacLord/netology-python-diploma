from typing import cast

from django.db import transaction
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils.cache import add_never_cache_headers
from django_rest_passwordreset.serializers import (
    PasswordTokenSerializer,
    ResetTokenSerializer,
)
from django_rest_passwordreset.views import ResetPasswordConfirm
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
)
from rest_framework import serializers, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from users.models import Contact, User
from users.serializers import (
    ContactDeleteResponseSerializer,
    ContactDeleteSerializer,
    ContactSerializer,
    ContactUpdateSerializer,
    EmailConfirmationResponseSerializer,
    EmailConfirmationSerializer,
    UserDetailsSerializer,
    UserLoginResponseSerializer,
    UserLoginSerializer,
    UserProfileUpdateSerializer,
    UserRegistrationResponseSerializer,
    UserRegistrationSerializer,
)
from users.services.authentication import (
    InvalidCredentialsError,
    authenticate_user,
)
from users.services.email_confirmation import (
    EmailConfirmationError,
    confirm_email,
)
from users.services.registration import (
    EmailAlreadyExistsError,
    register_user_with_confirmation,
)


class UserRegistrationView(APIView):
    """
    Регистрирует нового покупателя в системе закупок.

    Проверяет входные данные, создаёт неактивного
    пользователя и инициирует отправку письма
    со ссылкой подтверждения электронной почты.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["Пользователи"],
        summary="Регистрация пользователя",
        description=(
            "Создаёт нового покупателя с неактивным статусом. "
            "На указанный email отправляется ссылка "
            "для подтверждения регистрации."
        ),
        request=UserRegistrationSerializer,
        responses={
            201: UserRegistrationResponseSerializer,
            400: OpenApiResponse(
                description="Ошибка валидации регистрационных данных.",
            ),
        },
    )
    def post(self, request: Request) -> Response:
        """
        Обрабатывает запрос регистрации пользователя.

        Args:
            request (Request): HTTP-запрос с регистрационными
                данными нового пользователя.

        Returns:
            Response: Данные созданного пользователя
                и сообщение о необходимости подтверждения email.

        Raises:
            ValidationError: Если переданы некорректные данные
                или пользователь с таким email уже существует.
        """
        serializer = UserRegistrationSerializer(
            data=request.data,
        )
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data

        if not isinstance(data, dict):
            raise RuntimeError("Данные регистрации должны быть словарём.")

        try:
            user = register_user_with_confirmation(
                email=data["email"],
                password=data["password"],
                first_name=data["first_name"],
                last_name=data["last_name"],
                company=data["company"],
                position=data["position"],
            )

        except EmailAlreadyExistsError as error:
            raise ValidationError({"email": [str(error)]}) from error

        return Response(
            {
                "id": user.pk,
                "email": user.email,
                "is_active": user.is_active,
                "detail": ("Регистрация выполнена. Подтвердите электронную почту."),
            },
            status=status.HTTP_201_CREATED,
        )


class EmailConfirmationView(APIView):
    """
    Подтверждает электронную почту пользователя.

    GET-запрос отображает HTML-страницу с формой
    подтверждения регистрации.

    POST-запрос проверяет email и одноразовый токен,
    активирует учётную запись и удаляет использованный токен.

    Поддерживает JSON-запросы и обычные HTML-формы.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def _render_confirmation_page(
        self,
        request: Request,
        *,
        email: str = "",
        token: str = "",
        message: str = "",
        success: bool = False,
        status_code: int = status.HTTP_200_OK,
    ) -> HttpResponse:
        """
        Формирует HTML-страницу подтверждения электронной почты.

        Отображает форму подтверждения, сообщение об успешной
        активации или ошибку. Запрещает кэширование страницы
        и передачу её адреса в заголовке Referer.

        Args:
            request (Request): HTTP-запрос пользователя.
            email (str): Электронная почта пользователя.
            token (str): Исходный токен подтверждения.
            message (str): Сообщение для отображения.
            success (bool): Признак успешного подтверждения.
            status_code (int): HTTP-статус ответа.

        Returns:
            HttpResponse: HTML-страница подтверждения.
        """
        response = render(
            request._request,
            "users/email_confirmation.html",
            context={
                "email": email,
                "token": token,
                "message": message,
                "success": success,
            },
            status=status_code,
        )

        add_never_cache_headers(response)
        response["Referrer-Policy"] = "strict-origin"

        return response

    @extend_schema(
        tags=["Пользователи"],
        summary="Страница подтверждения регистрации",
        description=(
            "Отображает HTML-форму подтверждения email. "
            "Не активирует учётную запись пользователя "
            "и не использует токен подтверждения."
        ),
        parameters=[
            OpenApiParameter(
                name="email",
                type=str,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Электронная почта пользователя.",
            ),
            OpenApiParameter(
                name="token",
                type=str,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Токен подтверждения из письма.",
            ),
        ],
        responses={
            (200, "text/html"): str,
            (400, "text/html"): str,
        },
    )
    def get(self, request: Request) -> HttpResponse:
        """
        Отображает страницу подтверждения регистрации.

        Получает email и токен из параметров URL,
        проверяет их формат и отображает HTML-форму.

        Не изменяет состояние пользователя и не использует
        токен подтверждения.

        Args:
            request (Request): HTTP-запрос с email и токеном
                в параметрах строки запроса.

        Returns:
            HttpResponse: HTML-страница подтверждения
                или сообщение о некорректной ссылке.
        """
        serializer = EmailConfirmationSerializer(
            data=request.query_params,
        )

        if not serializer.is_valid():
            return self._render_confirmation_page(
                request,
                message="Некорректная ссылка подтверждения.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        data = serializer.validated_data

        if not isinstance(data, dict):
            raise RuntimeError("Данные подтверждения должны быть словарём.")

        return self._render_confirmation_page(
            request,
            email=data["email"],
            token=data["token"],
        )

    @extend_schema(
        tags=["Пользователи"],
        summary="Подтверждение электронной почты",
        description=(
            "Активирует учётную запись пользователя "
            "с помощью одноразового токена, "
            "полученного в письме подтверждения регистрации. "
            "Поддерживает JSON-запросы и HTML-формы."
        ),
        request={
            "application/json": EmailConfirmationSerializer,
            "application/x-www-form-urlencoded": (EmailConfirmationSerializer),
            "multipart/form-data": EmailConfirmationSerializer,
        },
        responses={
            (200, "application/json"): (EmailConfirmationResponseSerializer),
            (200, "text/html"): str,
            (400, "application/json"): OpenApiResponse(
                response=OpenApiTypes.OBJECT,
                description=(
                    "Некорректные данные, недействительный "
                    "или просроченный токен подтверждения."
                ),
            ),
            (400, "text/html"): str,
            (403, "text/html"): OpenApiResponse(
                response=str,
                description="Ошибка проверки CSRF-токена.",
            ),
        },
    )
    def post(
        self,
        request: Request,
    ) -> Response | HttpResponse:
        """
        Обрабатывает подтверждение электронной почты.

        Принимает JSON-запросы и данные HTML-формы.
        Проверяет CSRF-токен для браузерных форм,
        активирует пользователя и возвращает результат
        в соответствующем формате.

        Args:
            request (Request): HTTP-запрос с email
                пользователя и токеном подтверждения.

        Returns:
            Response | HttpResponse: JSON-ответ для API
                или HTML-страница для браузера.

        Raises:
            ValidationError: Если входные данные или токен
                подтверждения некорректны.
        """
        content_type = (request.content_type or "").split(";")[0].strip().lower()

        is_form = content_type in (
            "application/x-www-form-urlencoded",
            "multipart/form-data",
        )

        # Для браузерной формы проверяем CSRF-токен.
        if is_form:
            try:
                SessionAuthentication().enforce_csrf(request)

            except PermissionDenied:
                return self._render_confirmation_page(
                    request,
                    message=(
                        "Не удалось проверить безопасность запроса. "
                        "Повторно откройте ссылку из письма."
                    ),
                    status_code=status.HTTP_403_FORBIDDEN,
                )

        serializer = EmailConfirmationSerializer(
            data=request.data,
        )

        if not serializer.is_valid(
            raise_exception=not is_form,
        ):
            return self._render_confirmation_page(
                request,
                message="Некорректные данные подтверждения.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        data = serializer.validated_data

        if not isinstance(data, dict):
            raise RuntimeError("Данные подтверждения должны быть словарём.")

        try:
            user = confirm_email(
                email=data["email"],
                token=data["token"],
            )

        except EmailConfirmationError as error:
            if is_form:
                return self._render_confirmation_page(
                    request,
                    message=str(error),
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            raise ValidationError({"detail": str(error)}) from error

        message = "Электронная почта успешно подтверждена."

        # Возвращаем HTML-страницу при отправке формы.
        if is_form:
            return self._render_confirmation_page(
                request,
                message=message,
                success=True,
            )

        # Возвращаем JSON при обращении через REST API.
        return Response(
            {
                "detail": message,
                "is_active": user.is_active,
            },
            status=status.HTTP_200_OK,
        )


class UserLoginView(APIView):
    """
    Авторизует пользователя в системе закупок.

    Проверяет электронную почту и пароль,
    запрещает вход неактивным пользователям
    и возвращает токен авторизации DRF.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["Пользователи"],
        summary="Авторизация пользователя",
        description=(
            "Проверяет email и пароль пользователя. "
            "При успешной авторизации возвращает токен DRF. "
            "Токен необходимо передавать в заголовке "
            "Authorization: Token <token>."
        ),
        request=UserLoginSerializer,
        responses={
            200: UserLoginResponseSerializer,
            400: OpenApiResponse(
                response=OpenApiTypes.OBJECT,
                description="Некорректные входные данные.",
            ),
            401: OpenApiResponse(
                response=OpenApiTypes.OBJECT,
                description=("Неверный email, пароль или неактивная учётная запись."),
            ),
        },
    )
    def post(self, request: Request) -> Response:
        """
        Обрабатывает запрос авторизации пользователя.

        Проверяет формат входных данных и вызывает
        сервис авторизации для получения токена.

        Args:
            request (Request): HTTP-запрос с email
                и паролем пользователя.

        Returns:
            Response: Токен при успешной авторизации,
                ошибку 400 при некорректных данных
                или ошибку 401 при неверных учётных данных.
        """
        serializer = UserLoginSerializer(
            data=request.data,
        )

        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data

        if not isinstance(data, dict):
            raise RuntimeError("Неккоректный формат данных")

        try:
            token = authenticate_user(
                email=data["email"],
                password=data["password"],
            )

        except InvalidCredentialsError:
            return Response(
                {
                    "detail": "Неверный email или пароль.",
                },
                status=status.HTTP_401_UNAUTHORIZED,
                headers={
                    "WWW-Authenticate": "Token",
                },
            )

        return Response(
            {
                "token": token,
            },
            status=status.HTTP_200_OK,
        )


class UserDetailsView(APIView):
    """
    Предоставляет данные текущего пользователя.

    Доступен только авторизованным пользователям.
    Использует стандартную токенную аутентификацию DRF.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Пользователи"],
        summary="Получение профиля пользователя",
        description=(
            "Возвращает данные текущего авторизованного "
            "пользователя. Для доступа необходимо передать "
            "токен в заголовке Authorization."
        ),
        responses={
            200: UserDetailsSerializer,
            401: OpenApiResponse(
                description=("Токен авторизации отсутствует или недействителен."),
            ),
        },
    )
    def get(self, request: Request) -> Response:
        """
        Возвращает профиль текущего пользователя.

        Использует пользователя, определённого DRF
        по токену авторизации.

        Args:
            request (Request): HTTP-запрос авторизованного
                пользователя.

        Returns:
            Response: Данные профиля текущего пользователя.
        """
        serializer = UserDetailsSerializer(
            request.user,
        )

        return Response(
            serializer.data,
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        tags=["Пользователи"],
        summary="Изменение профиля пользователя",
        request=UserProfileUpdateSerializer,
        responses={200: UserDetailsSerializer},
    )
    def post(self, request: Request) -> Response:
        """
        Обновляет профиль текущего пользователя.

        Args:
            request (Request): Запрос с изменяемыми данными.

        Returns:
            Response: Обновлённый профиль пользователя.
        """
        serializer = UserProfileUpdateSerializer(
            request.user,
            data=request.data,
            partial=True,
        )

        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        return Response(
            UserDetailsSerializer(user).data,
            status=status.HTTP_200_OK,
        )


class UserPasswordResetConfirmView(ResetPasswordConfirm):
    """
    Подтверждает восстановление пароля через API или HTML.

    GET отображает страницу ввода нового пароля.
    POST с JSON использует стандартную логику библиотеки.
    POST из HTML-формы возвращает страницу с результатом.
    """

    def _render_page(
        self,
        request: Request,
        *,
        token: str = "",
        message: str = "",
        success: bool = False,
        status_code: int = status.HTTP_200_OK,
    ) -> HttpResponse:
        """
        Формирует HTML-страницу восстановления пароля.

        Args:
            request (Request): HTTP-запрос пользователя.
            token (str): Токен восстановления пароля.
            message (str): Сообщение для пользователя.
            success (bool): Признак успешного восстановления.
            status_code (int): HTTP-статус ответа.

        Returns:
            HttpResponse: HTML-страница восстановления пароля.
        """
        response = render(
            request._request,
            "users/password_reset.html",
            context={
                "token": token,
                "message": message,
                "success": success,
            },
            status=status_code,
        )

        add_never_cache_headers(response)
        response["Referrer-Policy"] = "strict-origin"

        return response

    @extend_schema(
        tags=["Пользователи"],
        summary="Страница восстановления пароля",
        parameters=[
            OpenApiParameter(
                name="token",
                type=str,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Токен из письма восстановления.",
            ),
        ],
        responses={
            (200, "text/html"): str,
            (400, "text/html"): str,
        },
    )
    def get(self, request: Request) -> HttpResponse:
        """
        Отображает форму установки нового пароля.

        Проверяет токен, но не использует его.

        Args:
            request (Request): GET-запрос с токеном.

        Returns:
            HttpResponse: HTML-форма или сообщение об ошибке.
        """
        token = request.query_params.get("token", "")

        serializer = ResetTokenSerializer(
            data={"token": token},
        )

        try:
            serializer.is_valid(raise_exception=True)
        except (ValidationError, Http404):
            return self._render_page(
                request,
                message="Ссылка недействительна или срок её действия истёк.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        return self._render_page(
            request,
            token=token,
        )

    @extend_schema(
        tags=["Пользователи"],
        summary="Установка нового пароля",
        description=(
            "Принимает токен и новый пароль. Поддерживает JSON API и HTML-формы."
        ),
        request=PasswordTokenSerializer,
        responses={
            200: OpenApiTypes.OBJECT,
            400: OpenApiTypes.OBJECT,
            404: OpenApiTypes.OBJECT,
        },
    )
    def post(
        self,
        request: Request,
        *args: object,
        **kwargs: object,
    ) -> Response | HttpResponse:
        """
        Устанавливает новый пароль пользователя.

        Для JSON-запросов сохраняет стандартное поведение
        библиотеки django-rest-passwordreset.

        Для HTML-форм проверяет CSRF и совпадение паролей,
        после чего отображает результат восстановления.

        Args:
            request (Request): Запрос с токеном и паролем.
            *args: Дополнительные позиционные аргументы.
            **kwargs: Дополнительные именованные аргументы.

        Returns:
            Response | HttpResponse: JSON-ответ или HTML-страница.
        """
        content_type = (request.content_type or "").split(";")[0].strip().lower()

        is_form = content_type in (
            "application/x-www-form-urlencoded",
            "multipart/form-data",
        )

        # Для JSON оставляем стандартную реализацию библиотеки.
        if not is_form:
            return super().post(request, *args, **kwargs)

        # Для браузерной формы обязательно проверяем CSRF.
        try:
            SessionAuthentication().enforce_csrf(request)
        except PermissionDenied:
            return self._render_page(
                request,
                message="Ошибка безопасности. Откройте ссылку повторно.",
                status_code=status.HTTP_403_FORBIDDEN,
            )

        token = request.data.get("token", "")
        password = request.data.get("password")
        password_confirm = request.data.get("password_confirm")

        if not password or password != password_confirm:
            return self._render_page(
                request,
                token=token,
                message="Пароли не совпадают или не заполнены.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        try:
            # Используем готовую логику восстановления пароля.
            # Она же отправляет сигнал post_password_reset.
            super().post(request, *args, **kwargs)

        except Http404:
            return self._render_page(
                request,
                message="Токен недействителен или срок его действия истёк.",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        except ValidationError as error:
            details = error.detail

            if isinstance(details, dict):
                errors = details.get("password", [])
                message = " ".join(str(item) for item in errors)
            else:
                message = "Некорректный пароль."

            return self._render_page(
                request,
                token=token,
                message=message or "Некорректный пароль.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        return self._render_page(
            request,
            message="Ваш пароль успешно изменён.",
            success=True,
        )


class ContactView(APIView):
    """
    Управляет контактами и адресами доставки.

    Предоставляет доступ только к контактам
    текущего авторизованного пользователя.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Контакты"],
        summary="Получение контактов покупателя",
        description=(
            "Возвращает список контактов и адресов доставки "
            "текущего авторизованного покупателя."
        ),
        responses={
            200: ContactSerializer(many=True),
        },
    )
    def get(self, request: Request) -> Response:
        """
        Возвращает список контактов текущего покупателя.

        Фильтрует записи по идентификатору пользователя,
        полученному из токена авторизации.

        Args:
            request (Request): HTTP-запрос покупателя.

        Returns:
            Response: Список принадлежащих покупателю контактов.
        """
        contacts = Contact.objects.filter(
            user_id=request.user.pk,
        )

        serializer = ContactSerializer(
            contacts,
            many=True,
        )

        return Response(
            serializer.data,
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        tags=["Контакты"],
        summary="Добавление контакта",
        description=(
            "Создаёт контакт и адрес доставки "
            "для текущего авторизованного пользователя. "
            "Допускается не более пяти контактов."
        ),
        request=ContactSerializer,
        responses={
            201: ContactSerializer,
            400: OpenApiTypes.OBJECT,
            401: OpenApiTypes.OBJECT,
        },
    )
    def post(self, request: Request) -> Response:
        """
        Создаёт новый контакт текущего пользователя.

        Проверяет входные данные и ограничение количества
        контактов. Блокирует запись пользователя на время
        создания, чтобы параллельные API-запросы не могли
        одновременно превысить установленный лимит.

        Args:
            request (Request): HTTP-запрос с данными контакта.

        Returns:
            Response: Созданный контакт и HTTP-статус 201.

        Raises:
            ValidationError: Если данные некорректны
                или превышен лимит контактов.
        """
        with transaction.atomic():
            # Блокируем пользователя до конца транзакции.
            User.objects.select_for_update().get(
                pk=request.user.pk,
            )

            serializer = ContactSerializer(
                data=request.data,
                context={"request": request},
            )

            serializer.is_valid(raise_exception=True)

            contact = serializer.save()

        return Response(
            ContactSerializer(contact).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        tags=["Контакты"],
        summary="Редактирование контакта",
        description=(
            "Позволяет изменить отдельные поля контакта "
            "текущего пользователя. "
            "Идентификатор контакта обязателен."
        ),
        request=ContactUpdateSerializer,
        responses={
            200: ContactSerializer,
            400: OpenApiTypes.OBJECT,
            401: OpenApiTypes.OBJECT,
            404: OpenApiTypes.OBJECT,
        },
    )
    @extend_schema(
        tags=["Контакты"],
        summary="Частичное обновление контакта",
        description=(
            "Изменяет отдельные поля контакта текущего пользователя. "
            "Идентификатор контакта обязателен."
        ),
        request=ContactUpdateSerializer,
        responses={
            200: ContactSerializer,
            400: OpenApiTypes.OBJECT,
            401: OpenApiTypes.OBJECT,
            404: OpenApiTypes.OBJECT,
        },
    )
    def patch(self, request: Request) -> Response:
        """
        Частично обновляет контакт текущего пользователя.

        Находит контакт по идентификатору, проверяет
        принадлежность пользователю и обновляет только
        переданные поля.

        Args:
            request (Request): Запрос с идентификатором
                контакта и изменяемыми полями.

        Returns:
            Response: Обновлённые данные контакта.

        Raises:
            ValidationError: Если переданы некорректные данные.
            Http404: Если контакт не найден или принадлежит
                другому пользователю.
        """

        contact_id = request.data.get("id")

        if (
            not isinstance(contact_id, int)
            or isinstance(contact_id, bool)
            or contact_id < 1
        ):
            raise ValidationError(
                {"id": ["Укажите положительный целочисленный идентификатор контакта."]}
            )

        contact = get_object_or_404(
            Contact,
            pk=contact_id,
            user_id=request.user.pk,
        )

        serializer = ContactUpdateSerializer(
            contact,
            data=request.data,
            partial=True,
            context={"request": request},
        )

        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(
            ContactSerializer(contact).data,
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        tags=["Контакты"],
        summary="Удаление контактов пользователя",
        description=(
            "Удаляет один или несколько контактов текущего "
            "пользователя. Идентификаторы передаются через "
            "query-параметр items, разделённые запятыми."
        ),
        parameters=[
            OpenApiParameter(
                name="items",
                type=str,
                location=OpenApiParameter.QUERY,
                required=True,
                description=(
                    "Идентификаторы контактов через запятую. Например: 2,3,5."
                ),
            ),
        ],
        responses={
            200: ContactDeleteResponseSerializer,
            400: OpenApiTypes.OBJECT,
            401: OpenApiTypes.OBJECT,
            404: OpenApiTypes.OBJECT,
        },
    )
    @transaction.atomic
    def delete(self, request: Request) -> Response:
        """
        Удаляет выбранные контакты текущего пользователя.

        Проверяет входные данные и принадлежность всех
        контактов пользователю. Удаление выполняется
        в одной транзакции.

        Args:
            request (Request): HTTP-запрос со списком
                идентификаторов удаляемых контактов.

        Returns:
            Response: Количество удалённых контактов.

        Raises:
            ValidationError: Если передан некорректный список.
            NotFound: Если один или несколько контактов
                не существуют либо принадлежат другому пользователю.
        """

        # Получаем идентификаторы из query-параметра.
        items = request.query_params.get("items", "")

        # Преобразуем строку "2,3,5" в список ["2", "3", "5"].
        contact_ids_raw = items.split(",") if items else []

        serializer = ContactDeleteSerializer(
            data={"items": contact_ids_raw},
        )

        serializer.is_valid(raise_exception=True)

        data = cast(
            dict[str, list[int]],
            serializer.validated_data,
        )

        contact_ids = data["items"]

        # Выбираем и блокируем только собственные контакты.
        contacts = Contact.objects.filter(
            user_id=request.user.pk,
            id__in=contact_ids,
        ).select_for_update()

        existing_ids = list(contacts.values_list("id", flat=True))

        if len(existing_ids) != len(contact_ids):
            raise NotFound("Один или несколько контактов не найдены.")

        contacts.delete()

        return Response(
            {"deleted": len(existing_ids)},
            status=status.HTTP_200_OK,
        )
