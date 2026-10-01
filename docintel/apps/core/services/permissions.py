"""Tool permission resolution.

User-specific rows replace role rows, which replace the built-in role matrix.
Two indexed lookups at most, once per request, never per row.
"""

from __future__ import annotations

from docintel.apps.core.models import (
    ACTIONS,
    DEFAULT_ROLE_ACTIONS,
    Company,
    ToolPermission,
    User,
)


def allowed_actions(*, company: Company, user: User, role: str, tool: str) -> frozenset[str]:
    user_grant = (
        ToolPermission.objects.for_company(company)
        .filter(user=user, tool_slug=tool)
        .values_list("actions", flat=True)
        .first()
    )
    if user_grant is not None:
        return frozenset(action for action in user_grant if action in ACTIONS)
    role_grant = (
        ToolPermission.objects.for_company(company)
        .filter(user__isnull=True, role=role, tool_slug=tool)
        .values_list("actions", flat=True)
        .first()
    )
    if role_grant is not None:
        return frozenset(action for action in role_grant if action in ACTIONS)
    return DEFAULT_ROLE_ACTIONS.get(role, frozenset())


def has_tool_permission(
    *,
    company: Company,
    user: User,
    role: str,
    tool: str,
    action: str,
) -> bool:
    return action in allowed_actions(company=company, user=user, role=role, tool=tool)
