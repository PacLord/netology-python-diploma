from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    """
    Настраивает административный интерфейс модели пользователя.

    Позволяет создавать и редактировать пользователей с авторизацией
    по email, управлять ролями, активностью и правами доступа.
    """

    list_display = (
        "id",
        "email",
        "first_name",
        "last_name",
        "type",
        "is_active",
        "is_staff",
    )

    list_display_links = ("id", "email")

    list_filter = (
        "type",
        "is_active",
        "is_staff",
        "is_superuser",
    )

    search_fields = (
        "email",
        "first_name",
        "last_name",
        "company",
    )

    ordering = ("email",)

    fieldsets = (
        (
            None,
            {
                "fields": ("email", "password"),
            },
        ),
        (
            "Личная информация",
            {
                "fields": (
                    "first_name",
                    "last_name",
                    "type",
                    "company",
                    "position",
                ),
            },
        ),
        (
            "Права доступа",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
        (
            "Важные даты",
            {
                "fields": (
                    "last_login",
                    "date_joined",
                ),
            },
        ),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "password1",
                    "password2",
                ),
            },
        ),
    )
