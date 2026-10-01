"""Role defaults are the permission matrix. A ToolPermission row replaces them."""

from __future__ import annotations

import pytest

from docintel.apps.core.models import Membership
from docintel.tests.factories import DocumentFactory, ToolPermissionFactory


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("role", "method", "path", "expected"),
    [
        (Membership.Role.MEMBER, "get", "/api/v1/documents/", 200),
        (Membership.Role.MEMBER, "get", "/api/v1/documents/review-queue/", 403),
        (Membership.Role.MEMBER, "get", "/api/v1/documents/export.csv", 403),
        (Membership.Role.REVIEWER, "get", "/api/v1/documents/review-queue/", 200),
        (Membership.Role.REVIEWER, "post", "/api/v1/documents/uploads/", 403),
        (Membership.Role.ADMIN, "get", "/api/v1/documents/export.csv", 200),
    ],
)
def test_role_matrix(role, method, path, expected, company, user_factory, api_client) -> None:  # type: ignore[no-untyped-def]
    DocumentFactory(company=company, status="needs_review")
    client = api_client(user_factory(company=company, role=role), company)
    response = getattr(client, method)(
        path, data={"filename": "a.pdf", "content_type": "application/pdf", "size_bytes": 10}, format="json"
    )
    assert response.status_code == expected


@pytest.mark.django_db
def test_user_grant_replaces_role_default(company, user_factory, api_client) -> None:  # type: ignore[no-untyped-def]
    user = user_factory(company=company, role=Membership.Role.MEMBER)
    ToolPermissionFactory(
        company=company, user=user, role="", tool_slug="documents", actions=["view", "review"]
    )
    client = api_client(user, company)
    response = client.get("/api/v1/documents/review-queue/")
    assert response.status_code == 200
