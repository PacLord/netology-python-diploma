from django.urls import path
from django_rest_passwordreset.views import reset_password_request_token

from users.views import (
    ContactView,
    EmailConfirmationView,
    UserDetailsView,
    UserLoginView,
    UserPasswordResetConfirmView,
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
    path(
        "login",
        UserLoginView.as_view(),
        name="login",
    ),
    path(
        "details",
        UserDetailsView.as_view(),
        name="details",
    ),
    path(
        "password_reset",
        reset_password_request_token,
        name="password-reset",
    ),
    path(
        "password_reset/confirm",
        UserPasswordResetConfirmView.as_view(),
        name="password-reset-confirm",
    ),
    path(
        "contact",
        ContactView.as_view(),
        name="contact",
    ),
]
