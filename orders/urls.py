from django.urls import path

from orders.views import (
    BasketView,
    OrderDetailView,
    OrderStatusUpdateView,
    OrderView,
    OrdersListView,
    PartnerOrdersView,
)

app_name = "orders"

urlpatterns = [
    path("basket", BasketView.as_view(), name="basket"),
    path("order", OrderView.as_view(), name="order"),
    path(
        "order/<int:order_id>",
        OrderDetailView.as_view(),
        name="order-detail",
    ),
    path(
        "order/<int:order_id>/status",
        OrderStatusUpdateView.as_view(),
        name="order-status-update",
    ),
    path(
        "orders",
        OrdersListView.as_view(),
        name="orders-list",
    ),
    path(
        "partner/orders",
        PartnerOrdersView.as_view(),
        name="partner-orders",
    ),
]
