"""List and detail query counts stay flat as the page grows."""

from __future__ import annotations

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from docintel.apps.core.models import Membership
from docintel.tests.factories import DocumentFactory


@pytest.fixture
def _children():  # type: ignore[no-untyped-def]
    def build(document) -> None:  # type: ignore[no-untyped-def]
        from docintel.apps.documents.models import ExtractedField, LineItem

        ExtractedField.unscoped.create(
            company=document.company,
            document=document,
            key="total",
            value="1.00",
            normalized_value={"amount": "1.00"},
            confidence="0.9900",
            source="textract",
        )
        LineItem.unscoped.create(
            company=document.company,
            document=document,
            position=1,
            description="Item",
            quantity="1",
            unit_price="1",
            amount="1.00",
            confidence="0.9900",
        )

    return build


@pytest.mark.django_db
def test_list_query_count_is_stable(company, user_factory, api_client, _children) -> None:  # type: ignore[no-untyped-def]
    client = api_client(user_factory(company=company, role=Membership.Role.MEMBER), company)
    first = DocumentFactory(company=company)
    _children(first)
    with CaptureQueriesContext(connection) as small:
        assert client.get("/api/v1/documents/").status_code == 200
    for index in range(49):
        document = DocumentFactory(company=company, sha256=f"{index + 1:064x}")
        _children(document)
    with CaptureQueriesContext(connection) as large:
        body = client.get("/api/v1/documents/")
    assert body.status_code == 200
    assert len(body.json()["results"]) == 50
    assert len(small) == len(large)


@pytest.mark.django_db
def test_detail_query_count_is_stable(company, user_factory, api_client, _children) -> None:  # type: ignore[no-untyped-def]
    client = api_client(user_factory(company=company, role=Membership.Role.MEMBER), company)
    documents = []
    for index in range(2):
        document = DocumentFactory(company=company, sha256=f"{index + 10:064x}")
        _children(document)
        documents.append(document)
    with CaptureQueriesContext(connection) as first:
        client.get(f"/api/v1/documents/{documents[0].id}/")
    with CaptureQueriesContext(connection) as second:
        client.get(f"/api/v1/documents/{documents[1].id}/")
    assert len(first) == len(second)
