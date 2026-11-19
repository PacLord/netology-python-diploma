from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from users.models import User


class IsSupplier(BasePermission):
    """
    Разрешает доступ только пользователям-поставщикам.

    Проверяет, что пользователь авторизован
    и имеет тип учётной записи shop.
    """

    message = "Доступ разрешён только поставщикам."

    def has_permission(
        self,
        request: Request,
        view: APIView,
    ) -> bool:
        """
        Проверяет право пользователя на доступ к API поставщика.

        Args:
            request (Request): Текущий HTTP-запрос.
            view (APIView): Представление, для которого
                выполняется проверка разрешений.

        Returns:
            bool: True для авторизованного поставщика,
                False для остальных пользователей.
        """
        return (
            request.user.is_authenticated
            and getattr(request.user, "type", None) == User.UserType.SHOP
        )
