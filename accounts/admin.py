from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Email-based admin (Django's UserAdmin is hardwired to ``username``, §3.16)."""

    ordering = ("email",)
    list_display = ("email", "display_name", "is_staff", "is_superuser", "email_confirmed", "subscription_bypass")
    list_filter = ("subscription_bypass", "is_staff", "is_superuser", "is_active")
    search_fields = ("email", "display_name", "first_name", "last_name")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("display_name", "first_name", "last_name")}),
        ("Status", {"fields": ("email_confirmed",)}),
        ("Billing", {"fields": ("subscription_bypass", "bypass_note", "bypass_granted_at")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "password1", "password2")}),
    )
