"""Read-side querysets.

List, detail, and the review queue each run one filtered query plus two
prefetches, independent of page size. The comments name the index that
serves the filter.
"""

from __future__ import annotations

from uuid import UUID

from django.db.models import Prefetch, QuerySet

from docintel.apps.core.exceptions import NotFound
from docintel.apps.core.models import Company
from docintel.apps.documents.models import Document, ExtractedField, LineItem


def with_children(queryset: QuerySet[Document], company: Company) -> QuerySet[Document]:
    return queryset.select_related("vendor", "uploaded_by").prefetch_related(
        Prefetch(
            "fields",
            queryset=ExtractedField.objects.for_company(company).order_by("key"),
        ),
        Prefetch(
            "line_items",
            queryset=LineItem.objects.for_company(company).order_by("position"),
        ),
    )


def document_list(company: Company) -> QuerySet[Document]:
    # Index: doc_co_status_created (company, status, created_at) once filtered.
    return with_children(Document.objects.for_company(company), company).order_by(
        "-created_at",
        "-id",
    )


def review_queue(company: Company) -> QuerySet[Document]:
    # Partial index doc_review_queue (company, created_at) WHERE needs_review.
    return with_children(
        Document.objects.for_company(company).filter(status=Document.Status.NEEDS_REVIEW),
        company,
    ).order_by("created_at", "id")


def get_document(company: Company, document_id: UUID) -> Document:
    try:
        return with_children(Document.objects.for_company(company), company).get(id=document_id)
    except Document.DoesNotExist as exc:
        raise NotFound("Document not found.") from exc


def approved_export(company: Company) -> QuerySet[Document]:
    # Same company/status index as the list, streamed with iterator().
    return (
        Document.objects.for_company(company)
        .filter(status=Document.Status.APPROVED)
        .select_related("vendor")
        .order_by("created_at", "id")
    )
