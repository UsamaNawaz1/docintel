"""Human review: corrections, approval, rejection, reprocess.

Approval emits ``document.approved`` with idempotency key
``document.approved:{id}:{version}``. Two reviewers racing on the same
``If-Match`` value serialize on the row lock; the loser sees a new version
and gets ``precondition_failed``, so exactly one outbox row is written.
"""

from __future__ import annotations

from uuid import UUID

from django.db import transaction
from django.utils import timezone

from docintel.apps.core.exceptions import InvalidTransition, NotFound, PreconditionFailed
from docintel.apps.core.models import Company, User
from docintel.apps.documents.models import Document, DocumentEvent, ExtractedField
from docintel.apps.documents.normalization import normalize_human
from docintel.apps.sync.services import emit_event

_REVIEWABLE = {Document.Status.NEEDS_REVIEW, Document.Status.EXTRACTED}
_REPROCESSABLE = {
    Document.Status.NEEDS_REVIEW,
    Document.Status.EXTRACTED,
    Document.Status.FAILED,
    Document.Status.REJECTED,
}


def correct_fields(
    *,
    company: Company,
    user: User,
    document_id: UUID,
    expected_version: int,
    corrections: list[tuple[str, str]],
) -> Document:
    with transaction.atomic():
        document = _lock(company, document_id)
        _check_version(document, expected_version)
        if document.status not in _REVIEWABLE:
            raise InvalidTransition(
                "Fields can only be corrected while the document is in review or extracted.",
                details={"from": document.status},
            )
        now = timezone.now()
        for key, value in corrections:
            ExtractedField.unscoped.update_or_create(
                document=document,
                key=key,
                defaults={
                    "company": company,
                    "value": value,
                    "normalized_value": normalize_human(key, value),
                    "confidence": "1.0000",
                    "source": ExtractedField.Source.HUMAN,
                    "corrected_by": user,
                    "corrected_at": now,
                },
            )
        _refresh_denormalized(document)
        document.version += 1
        document.save()
        _event(
            document,
            user,
            "field_corrected",
            document.status,
            document.status,
            {"keys": [key for key, _value in corrections]},
        )
    return document


def approve_document(
    *,
    company: Company,
    user: User,
    document_id: UUID,
    expected_version: int,
) -> Document:
    with transaction.atomic():
        document = _lock(company, document_id)
        if document.status == Document.Status.APPROVED:
            return document
        _check_version(document, expected_version)
        previous = document.transition_to(Document.Status.APPROVED)
        document.save(update_fields=["status", "version", "updated_at"])
        _event(document, user, "approved", previous, document.status, {})
        emit_event(
            company=company,
            event_type="document.approved",
            aggregate_type="document",
            aggregate_id=document.id,
            payload=_approved_payload(document),
            idempotency_key=f"document.approved:{document.id}:{document.version}",
        )
        transaction.on_commit(
            lambda cid=company.id, did=document.id: _publish(cid, did, Document.Status.APPROVED)
        )
    return document


def reject_document(
    *,
    company: Company,
    user: User,
    document_id: UUID,
    expected_version: int,
    reason: str,
) -> Document:
    with transaction.atomic():
        document = _lock(company, document_id)
        if document.status == Document.Status.REJECTED:
            return document
        _check_version(document, expected_version)
        previous = document.transition_to(Document.Status.REJECTED)
        document.failure_reason = reason[:80]
        document.save(update_fields=["status", "version", "failure_reason", "updated_at"])
        _event(document, user, "rejected", previous, document.status, {"reason": reason[:80]})
        transaction.on_commit(
            lambda cid=company.id, did=document.id: _publish(cid, did, Document.Status.REJECTED)
        )
    return document


def reprocess_document(*, company: Company, user: User, document_id: UUID) -> Document:
    """Send the document back through Textract.

    The client request token is the document id, so Textract returns the
    original job rather than starting a second billable analysis. Stored
    fields are replaced when that job is ingested again.
    """
    with transaction.atomic():
        document = _lock(company, document_id)
        if document.status == Document.Status.PROCESSING:
            return document
        if document.status not in _REPROCESSABLE:
            raise InvalidTransition(
                "This document cannot be reprocessed.",
                details={"from": document.status},
            )
        previous = document.transition_to(Document.Status.PROCESSING)
        document.textract_job_id = ""
        document.failure_reason = ""
        document.save(update_fields=["status", "version", "textract_job_id", "failure_reason", "updated_at"])
        _event(document, user, "reprocess_requested", previous, document.status, {})
        transaction.on_commit(lambda did=document.id: _enqueue(did))
    return document


def _approved_payload(document: Document) -> dict[str, object]:
    fields = {field.key: field.normalized_value for field in document.fields.all()}
    lines = [
        {
            "position": line.position,
            "description": line.description,
            "quantity": str(line.quantity) if line.quantity is not None else None,
            "unit_price": str(line.unit_price) if line.unit_price is not None else None,
            "amount": str(line.amount) if line.amount is not None else None,
        }
        for line in document.line_items.all()
    ]
    return {
        "id": str(document.id),
        "version": document.version,
        "vendor_id": str(document.vendor_id) if document.vendor_id else None,
        "invoice_number": document.invoice_number,
        "invoice_date": document.invoice_date.isoformat() if document.invoice_date else None,
        "currency": document.currency,
        "subtotal": str(document.subtotal) if document.subtotal is not None else None,
        "tax": str(document.tax) if document.tax is not None else None,
        "total": str(document.total) if document.total is not None else None,
        "fields": fields,
        "line_items": lines,
    }


def _refresh_denormalized(document: Document) -> None:
    from docintel.apps.documents.normalization import (
        NormalizedField,
        date_value,
        money_amount,
        text_value,
    )

    stored = {field.key: field for field in document.fields.all()}
    normalized = {
        key: NormalizedField(
            key=key,
            raw=field.value,
            normalized=field.normalized_value if isinstance(field.normalized_value, dict) else {},
            confidence=field.confidence,
            page=field.page,
            bounding_box=field.bounding_box if isinstance(field.bounding_box, dict) else None,
        )
        for key, field in stored.items()
    }
    document.invoice_number = text_value(normalized.get("invoice_number"))[:80]
    document.invoice_date = date_value(normalized.get("invoice_date"))
    document.total = money_amount(normalized.get("total"))
    document.subtotal = money_amount(normalized.get("subtotal"))
    document.tax = money_amount(normalized.get("tax"))


def _lock(company: Company, document_id: UUID) -> Document:
    try:
        return (
            Document.objects.for_company(company)
            .select_for_update()
            .select_related("vendor")
            .get(id=document_id)
        )
    except Document.DoesNotExist as exc:
        raise NotFound("Document not found.") from exc


def _check_version(document: Document, expected_version: int) -> None:
    if document.version != expected_version:
        raise PreconditionFailed(
            "The document was updated by someone else.",
            details={"version": document.version},
        )


def _event(
    document: Document,
    actor: User,
    action: str,
    from_status: str,
    to_status: str,
    metadata: dict[str, object],
) -> None:
    DocumentEvent.objects.for_company(document.company).create(
        company=document.company,
        document=document,
        actor=actor,
        action=action,
        from_status=from_status,
        to_status=to_status,
        metadata=metadata,
    )


def _publish(company_id: UUID, document_id: UUID, status: str) -> None:
    from docintel.apps.documents.notifications import publish_status

    publish_status(company_id, document_id, status)


def _enqueue(document_id: UUID) -> None:
    from docintel.apps.documents.tasks import start_expense_analysis

    start_expense_analysis.delay(str(document_id))
