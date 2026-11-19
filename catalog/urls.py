from django.urls import path

from catalog.views import (
    CategoryListView,
    PartnerStateView,
    PartnerUpdateView,
    ProductInfoDetailView,
    ProductInfoListView,
    ShopListView,
)

app_name = "catalog"

urlpatterns = [
    path(
        "categories",
        CategoryListView.as_view(),
        name="categories",
    ),
    path(
        "shops",
        ShopListView.as_view(),
        name="shops",
    ),
    path(
        "products",
        ProductInfoListView.as_view(),
        name="products",
    ),
    path(
        "products/<int:pk>",
        ProductInfoDetailView.as_view(),
        name="product-detail",
    ),
    path(
        "partner/state",
        PartnerStateView.as_view(),
        name="partner-state",
    ),
    path(
        "partner/update",
        PartnerUpdateView.as_view(),
        name="partner-update",
    ),
]
