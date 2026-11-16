from django.urls import path

from users.views import (
    EmailConfirmationView,
    UserRegistrationView,
)

app_name = "users"

urlpatterns = [
    path(
        "register",
        UserRegistrationView.as_view(),
        name="register",
    ),
    path(
        "register/confirm",
        EmailConfirmationView.as_view(),
        name="register-confirm",
    ),
]
