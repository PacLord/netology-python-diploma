from django.http import HttpResponse
from django.shortcuts import render
from django.utils.cache import add_never_cache_headers
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
)
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from users.serializers import (
    EmailConfirmationResponseSerializer,
    EmailConfirmationSerializer,
    UserRegistrationResponseSerializer,
    UserRegistrationSerializer,
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
