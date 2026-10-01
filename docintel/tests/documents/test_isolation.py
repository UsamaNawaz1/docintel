"""Cross-tenant access is a 404, including list endpoints."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from docintel.apps.core.models import Membership
from docintel.tests.factories import DocumentFactory


@pytest.mark.django_db
@pytest.mark.parametrize(
    "path_for",
    [
        lambda document: f"/api/v1/documents/{document.id}/",
        lambda document: f"/api/v1/documents/{document.id}/complete/",
        lambda document: f"/api/v1/documents/{document.id}/approve/",
        lambda document: f"/api/v1/documents/{document.id}/fields/",
    ],
)
def test_other_tenant_document_is_not_found(
    path_for, user_factory, api_client, company, other_company
) -> None:  # type: ignore[no-untyped-def]
    document = DocumentFactory(company=other_company, status="needs_review", version=1)
    client: APIClient = api_client(
        user_factory(company=company, role=Membership.Role.ADMIN),
        company,
    )
    response = client.get(path_for(document))
    if response.status_code == 405:
        response = client.post(path_for(document), data={}, format="json", HTTP_IF_MATCH="1")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


@pytest.mark.django_db
def test_list_does_not_leak(user_factory, api_client, company, other_company) -> None:  # type: ignore[no-untyped-def]
    DocumentFactory(company=company, invoice_number="OURS")
    DocumentFactory(company=other_company, invoice_number="THEIRS")
    client = api_client(user_factory(company=company, role=Membership.Role.MEMBER), company)
    response = client.get("/api/v1/documents/")
    assert response.status_code == 200
    numbers = [row["invoice_number"] for row in response.json()["results"]]
    assert numbers == ["OURS"]
