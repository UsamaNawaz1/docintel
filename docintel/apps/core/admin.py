"""Django admin is staff-only and reads through ``unscoped``.

Tenant roles do not grant admin access. ``is_staff`` is a separate control
plane for operators of the platform, not for tenant users.
"""

from __future__ import annotations

from django.contrib import admin

from docintel.apps.core.models import Company, Membership, ToolPermission, User


class UnscopedModelAdmin(admin.ModelAdmin):
    def get_queryset(self, request):  # type: ignore[no-untyped-def]
        return self.model.unscoped.all()


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("email", "is_staff", "is_active")
    search_fields = ("email",)
    ordering = ("email",)


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "created_at")
    search_fields = ("name", "slug")


@admin.register(Membership)
class MembershipAdmin(UnscopedModelAdmin):
    list_display = ("company", "user", "role")
    list_filter = ("role",)


@admin.register(ToolPermission)
class ToolPermissionAdmin(UnscopedModelAdmin):
    list_display = ("company", "tool_slug", "role", "user")
