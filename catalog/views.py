from typing import cast

from django.db.models import Q, QuerySet
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from catalog.models import Category, ProductInfo, Shop
from catalog.permissions import IsSupplier
from catalog.serializers import (
    CategorySerializer,
    PartnerStateUpdateSerializer,
    PartnerUpdateResponseSerializer,
    PartnerUpdateSerializer,
    ProductFilterSerializer,
    ProductInfoSerializer,
    ShopSerializer,
)
from catalog.services.importer import CatalogImportError
from catalog.services.remote_catalog import import_remote_catalog
from catalog.services.remote_yaml import CatalogDownloadError


@extend_schema_view(
    get=extend_schema(
        tags=["Каталог"],
        summary="Получение списка категорий",
        description="Возвращает все категории товаров.",
        responses={200: CategorySerializer(many=True)},
    )
)
class CategoryListView(ListAPIView):
    """
    Возвращает список категорий товаров.

    Доступен без авторизации.
    Категории сортируются по названию
    согласно настройкам модели Category.
    """

    queryset = Category.objects.all()
    serializer_class = CategorySerializer

    authentication_classes = []
    permission_classes = [AllowAny]


@extend_schema_view(
    get=extend_schema(
        tags=["Каталог"],
        summary="Получение списка магазинов",
        description=("Возвращает магазины, которые принимают заказы."),
        responses={200: ShopSerializer(many=True)},
    )
)
class ShopListView(ListAPIView):
    """
    Возвращает список активных магазинов.

    В выборку включаются только магазины
    с разрешённым приёмом заказов.
    """

    queryset = Shop.objects.filter(state=True)
    serializer_class = ShopSerializer

    authentication_classes = []
    permission_classes = [AllowAny]


@extend_schema_view(
    get=extend_schema(
        tags=["Каталог"],
        summary="Получение списка товаров",
        description=(
            "Возвращает доступные товарные предложения "
            "магазинов, принимающих заказы.\n\n"
            "Поддерживает фильтрацию по магазину и категории. "
            "Фильтры можно использовать одновременно.\n\n"
            "В результат не включаются товары с нулевым "
            "остатком и предложения неактивных магазинов."
        ),
        parameters=[ProductFilterSerializer],
        responses={200: ProductInfoSerializer(many=True)},
    )
)
class ProductInfoListView(ListAPIView):
    """
    Возвращает список доступных товарных предложений.

    Поддерживает фильтрацию по магазину и категории.
    Исключает товары с нулевым остатком и предложения
    магазинов, которые не принимают заказы.
    """

    serializer_class = ProductInfoSerializer

    authentication_classes = []
    permission_classes = [AllowAny]

    def get_queryset(self) -> QuerySet[ProductInfo]:
        """
        Формирует выборку товарных предложений.

        Загружает связанные данные для предотвращения
        проблемы N+1 запросов.

        Проверяет и применяет фильтры по магазину
        и категории.

        Returns:
            QuerySet[ProductInfo]: Отфильтрованные
                товарные предложения.

        Raises:
            ValidationError: Если параметры фильтрации
                содержат некорректные значения.
        """
        # Получаем доступные товарные предложения.
        queryset = (
            ProductInfo.objects.filter(
                shop__state=True,
                quantity__gt=0,
            )
            .select_related(
                "shop",
                "product__category",
            )
            .prefetch_related(
                "product_parameters__parameter",
            )
        )

        # Проверяем параметры фильтрации.
        filters_serializer = ProductFilterSerializer(
            data=self.request.GET,
        )

        filters_serializer.is_valid(raise_exception=True)

        # Уточняем тип данных для Pylance.
        filters = cast(
            dict[str, int | str],
            filters_serializer.validated_data,
        )

        # Фильтруем по магазину.
        if "shop_id" in filters:
            queryset = queryset.filter(
                shop_id=filters["shop_id"],
            )

        # Фильтруем по категории.
        if "category_id" in filters:
            queryset = queryset.filter(
                product__category_id=filters["category_id"],
            )

        # Поиск по названию, модели и описанию товара.
        search = filters.get("search")

        if isinstance(search, str) and search:
            queryset = queryset.filter(
                Q(product__name__icontains=search)
                | Q(model__icontains=search)
                | Q(product__description__icontains=search)
            )

        return queryset


@extend_schema_view(
    get=extend_schema(
        tags=["Каталог"],
        summary="Получение информации о товаре",
        description=(
            "Возвращает подробную информацию о товарном "
            "предложении по его ID.\n\n"
            "Доступны только товары с положительным остатком "
            "из магазинов, принимающих заказы."
        ),
        responses={200: ProductInfoSerializer},
    )
)
class ProductInfoDetailView(RetrieveAPIView):
    """
    Возвращает подробную информацию о товарном предложении.

    Получает товарное предложение по внутреннему ID.
    Исключает товары с нулевым остатком и предложения
    магазинов, не принимающих заказы.

    Если предложение не найдено или недоступно,
    возвращает HTTP 404.
    """

    queryset = (
        ProductInfo.objects.filter(
            shop__state=True,
            quantity__gt=0,
        )
        .select_related(
            "shop",
            "product__category",
        )
        .prefetch_related(
            "product_parameters__parameter",
        )
    )

    serializer_class = ProductInfoSerializer

    authentication_classes = []
    permission_classes = [AllowAny]


class PartnerStateView(APIView):
    """
    Предоставляет информацию о состоянии магазина поставщика.

    Доступ разрешён только авторизованным
    пользователям с ролью shop.
    """

    permission_classes = [IsAuthenticated, IsSupplier]

    @extend_schema(
        tags=["Поставщики"],
        summary="Получение состояния магазина",
        description=(
            "Возвращает данные магазина, принадлежащего "
            "текущему авторизованному поставщику."
        ),
        responses={
            200: ShopSerializer,
            403: OpenApiTypes.OBJECT,
            404: OpenApiTypes.OBJECT,
        },
    )
    def get(self, request: Request) -> Response:
        """
        Возвращает информацию о магазине поставщика.

        Находит магазин по идентификатору
        текущего авторизованного пользователя.

        Args:
            request (Request): HTTP-запрос поставщика.

        Returns:
            Response: Данные собственного магазина.

        Raises:
            Http404: Если магазин не найден.
        """
        shop = get_object_or_404(
            Shop,
            user_id=request.user.pk,
        )

        serializer = ShopSerializer(shop)

        return Response(
            serializer.data,
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        tags=["Поставщики"],
        summary="Изменение состояния магазина",
        description=(
            "Позволяет поставщику включать или отключать "
            "приём заказов собственного магазина."
        ),
        request=PartnerStateUpdateSerializer,
        responses={
            200: ShopSerializer,
            400: OpenApiTypes.OBJECT,
            403: OpenApiTypes.OBJECT,
            404: OpenApiTypes.OBJECT,
        },
    )
    def post(self, request: Request) -> Response:
        """
        Изменяет состояние магазина текущего поставщика.

        Проверяет входные данные и находит магазин
        по текущему авторизованному пользователю.

        Args:
            request (Request): HTTP-запрос с параметром state.

        Returns:
            Response: Обновлённые данные магазина.

        Raises:
            ValidationError: Если передано некорректное состояние.
            Http404: Если у поставщика отсутствует магазин.
        """
        serializer = PartnerStateUpdateSerializer(
            data=request.data,
        )

        serializer.is_valid(raise_exception=True)

        data = cast(
            dict[str, bool],
            serializer.validated_data,
        )

        shop = get_object_or_404(
            Shop,
            user_id=request.user.pk,
        )

        shop.state = data["state"]
        shop.save(update_fields=["state"])

        return Response(
            ShopSerializer(shop).data,
            status=status.HTTP_200_OK,
        )


class PartnerUpdateView(APIView):
    """
    Обновляет каталог товаров авторизованного поставщика.

    Принимает URL YAML-файла, скачивает прайс-лист
    и синхронизирует его с базой данных.

    Разрешает обновлять только собственный магазин.
    """

    permission_classes = [IsAuthenticated, IsSupplier]

    @extend_schema(
        tags=["Поставщики"],
        summary="Обновление прайс-листа поставщика",
        description=(
            "Загружает YAML-файл по указанному URL "
            "и обновляет каталог текущего поставщика.\n\n"
            "Название магазина в YAML должно совпадать "
            "с названием магазина авторизованного пользователя."
        ),
        request=PartnerUpdateSerializer,
        responses={
            200: PartnerUpdateResponseSerializer,
            400: OpenApiTypes.OBJECT,
            401: OpenApiTypes.OBJECT,
            403: OpenApiTypes.OBJECT,
            404: OpenApiTypes.OBJECT,
        },
    )
    def post(self, request: Request) -> Response:
        """
        Выполняет импорт прайс-листа текущего поставщика.

        Проверяет URL, определяет магазин по авторизованному
        пользователю и запускает сервис удалённого импорта.

        Args:
            request (Request): HTTP-запрос с URL YAML-файла.

        Returns:
            Response: Статистика успешного импорта.

        Raises:
            ValidationError: Если URL, загрузка файла
                или содержимое каталога некорректны.
            Http404: Если у поставщика отсутствует магазин.
        """
        serializer = PartnerUpdateSerializer(
            data=request.data,
        )

        serializer.is_valid(raise_exception=True)

        data = cast(
            dict[str, str],
            serializer.validated_data,
        )

        # Получаем только магазин текущего поставщика.
        shop = get_object_or_404(
            Shop,
            user_id=request.user.pk,
        )

        try:
            statistics = import_remote_catalog(
                shop=shop,
                url=data["url"],
            )

        except CatalogDownloadError as error:
            raise ValidationError({"url": [str(error)]}) from error

        except CatalogImportError as error:
            raise ValidationError({"detail": [str(error)]}) from error

        return Response(
            {
                "detail": "Каталог успешно обновлён.",
                **statistics,
            },
            status=status.HTTP_200_OK,
        )
