"""DRF permission that reads ``tool_slug`` and ``get_required_action`` from the view."""

from __future__ import annotations

from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from docintel.apps.core.services.permissions import has_tool_permission


class HasToolPermission(BasePermission):
    message = "You do not have permission to perform this action."

    def has_permission(self, request: Request, view: APIView) -> bool:
        user = request.user
        if user is None or not getattr(user, "is_authenticated", False):
            return False
        company = getattr(request, "company", None)
        membership = getattr(request, "membership", None)
        tool = getattr(view, "tool_slug", None)
        if company is None or membership is None or not isinstance(tool, str):
            return False
        action = _required_action(view)
        if action is None:
            return False
        allowed = has_tool_permission(
            company=company,
            user=user,  # type: ignore[arg-type]
            role=membership.role,
            tool=tool,
            action=action,
        )
        if allowed:
            return True
        self.message = "You do not have permission to perform this action."
        return False


def _required_action(view: APIView) -> str | None:
    getter = getattr(view, "get_required_action", None)
    if callable(getter):
        action = getter()
        return action if isinstance(action, str) else None
    action = getattr(view, "required_action", None)
    return action if isinstance(action, str) else None
