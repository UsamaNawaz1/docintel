from __future__ import annotations

import pytest

from docintel.apps.core.exceptions import UnscopedQueryError
from docintel.apps.documents.models import Document
from docintel.tests.factories import DocumentFactory


@pytest.mark.django_db
def test_unscoped_manager_is_required() -> None:
    with pytest.raises(UnscopedQueryError):
        list(Document.objects.all())


@pytest.mark.django_db
def test_for_company_hides_other_tenants(company, other_company) -> None:  # type: ignore[no-untyped-def]
    own = DocumentFactory(company=company)
    DocumentFactory(company=other_company)
    found = list(Document.objects.for_company(company))
    assert [row.id for row in found] == [own.id]
