"""Textract start and completion.

Both the SNS webhook and the beat poller call ``ingest_job``. The row lock
makes a double completion a no-op once the document has left ``processing``.
Raw Textract JSON is gzipped into the tenant prefix; it is not stored in
Postgres.
"""

from __future__ import annotations

import gzip
import json
from datetime import timedelta
from uuid import UUID

import structlog
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from docintel.apps.core.models import Company
from docintel.apps.core.storage import assert_tenant_key, get_storage, tenant_prefix
from docintel.apps.documents.adapters import (
    JobInProgress,
    TerminalTextractError,
    TextractAdapter,
    client_request_token,
    get_textract,
    merge_pages,
)
from docintel.apps.documents.matching import match_vendor
from docintel.apps.documents.models import Document, DocumentEvent, ExtractedField, LineItem
from docintel.apps.documents.normalization import (
    Extraction,
    date_value,
    money_amount,
    normalize_analysis,
    text_value,
)
from docintel.apps.documents.rules import review_reasons
from docintel.apps.documents.schemas import ExpenseAnalysis
from docintel.config.settings.tuning import company_tuning, get_tuning

logger = structlog.get_logger(__name__)


def begin_textract(document_id: UUID, *, adapter: TextractAdapter | None = None) -> None:
    document = _prepare_start(document_id)
    if document is None:
        return
    textract = adapter or get_textract()
    token = client_request_token(document.id)
    assert_tenant_key(document.company_id, document.s3_key)
    try:
        job_id = textract.start_expense_analysis(
            bucket=settings.AWS_S3_BUCKET,
            key=document.s3_key,
            client_request_token=token,
            sns_topic_arn=settings.AWS_TEXTRACT_SNS_TOPIC_ARN,
            sns_role_arn=settings.AWS_TEXTRACT_SNS_ROLE_ARN,
        )
    except TerminalTextractError as exc:
        _fail(document.id, exc.code)
        return
    with transaction.atomic():
        locked = Document.unscoped.select_for_update().get(id=document.id)
        if locked.status != Document.Status.PROCESSING:
            return
        locked.textract_job_id = job_id
        locked.save(update_fields=["textract_job_id", "updated_at"])
    logger.info("textract_started", document_id=str(document.id), textract_job_id=job_id)


def ingest_job(document_id: UUID, *, adapter: TextractAdapter | None = None) -> None:
    document = Document.unscoped.filter(id=document_id).first()
    if document is None or document.status != Document.Status.PROCESSING:
        return
    if not document.textract_job_id:
        return
    textract = adapter or get_textract()
    try:
        pages = textract.get_expense_analysis(document.textract_job_id)
        analysis = merge_pages(pages)
    except JobInProgress:
        return
    except TerminalTextractError as exc:
        _fail(document.id, exc.code)
        return
    raw = analysis.model_dump(mode="json", by_alias=True)
    key = _store_raw(document, raw)
    _persist(document.id, analysis, raw_key=key)


def poll_stuck_documents() -> int:
    """Enqueue ingest for jobs that have been processing longer than the threshold.

    Uses partial index ``doc_processing_poll`` (``updated_at`` WHERE status is
    processing). This is the fallback when an SNS message is lost.
    """
    cutoff = timezone.now() - timedelta(seconds=get_tuning().textract_poll_after_seconds)
    ids = list(
        Document.unscoped.filter(status=Document.Status.PROCESSING, updated_at__lt=cutoff)
        .order_by("updated_at")
        .values_list("id", flat=True)[: get_tuning().textract_poll_batch]
    )
    for document_id in ids:
        _enqueue_ingest(document_id)
    return len(ids)


def _prepare_start(document_id: UUID) -> Document | None:
    with transaction.atomic():
        document = Document.unscoped.select_for_update().select_related("company").get(id=document_id)
        structlog.contextvars.bind_contextvars(
            company_id=str(document.company_id),
            document_id=str(document.id),
        )
        if document.status == Document.Status.UPLOADED:
            previous = document.transition_to(Document.Status.PROCESSING)
            document.failure_reason = ""
            document.save(update_fields=["status", "version", "failure_reason", "updated_at"])
            _event(document, None, "processing_started", previous, document.status, {})
            return document
        if document.status == Document.Status.PROCESSING and not document.textract_job_id:
            return document
        return None


def _persist(document_id: UUID, analysis: ExpenseAnalysis, *, raw_key: str) -> None:
    extraction = normalize_analysis(analysis)
    with transaction.atomic():
        document = Document.unscoped.select_for_update().select_related("company").get(id=document_id)
        if document.status != Document.Status.PROCESSING:
            return
        tuning = company_tuning(document.company.settings)
        if extraction.page_count is not None and extraction.page_count > tuning.max_pages:
            _fail_locked(document, "too_many_pages")
            return
        reasons = review_reasons(extraction, tuning)
        matched = match_vendor(
            company=document.company,
            vendor_name=text_value(extraction.by_key().get("vendor_name")),
            tax_id=_tax_id(extraction),
            tuning=tuning,
        )
        if extraction.by_key().get("vendor_name") is not None and matched is None:
            reasons.append("vendor_unmatched")
        ExtractedField.unscoped.filter(document=document).delete()
        LineItem.unscoped.filter(document=document).delete()
        ExtractedField.unscoped.bulk_create(
            [
                ExtractedField(
                    company_id=document.company_id,
                    document=document,
                    key=field.key,
                    value=field.raw,
                    normalized_value=field.normalized,
                    confidence=field.confidence,
                    page=field.page,
                    bounding_box=field.bounding_box,
                    source=ExtractedField.Source.TEXTRACT,
                )
                for field in extraction.fields
            ]
        )
        LineItem.unscoped.bulk_create(
            [
                LineItem(
                    company_id=document.company_id,
                    document=document,
                    position=line.position,
                    description=line.description,
                    quantity=line.quantity,
                    unit_price=line.unit_price,
                    amount=line.amount,
                    confidence=line.confidence,
                )
                for line in extraction.lines
            ]
        )
        _denormalize(document, extraction)
        target = Document.Status.NEEDS_REVIEW if reasons else Document.Status.EXTRACTED
        previous = document.transition_to(target)
        document.review_reasons = reasons
        document.processed_at = timezone.now()
        document.raw_response_s3_key = raw_key
        document.page_count = extraction.page_count
        if matched is not None:
            document.vendor = matched.vendor
            document.vendor_match_score = matched.score
        document.save()
        _event(
            document,
            None,
            "extracted",
            previous,
            document.status,
            {"reasons": reasons},
        )
        company_id = document.company_id
        status = document.status
        transaction.on_commit(lambda cid=company_id, did=document.id, st=status: _after_extract(cid, did, st))


def _denormalize(document: Document, extraction: Extraction) -> None:
    fields = extraction.by_key()
    document.invoice_number = text_value(fields.get("invoice_number"))[:80]
    document.invoice_date = date_value(fields.get("invoice_date"))
    document.currency = extraction.currency
    document.subtotal = money_amount(fields.get("subtotal"))
    document.tax = money_amount(fields.get("tax"))
    document.total = money_amount(fields.get("total"))


def _tax_id(extraction: Extraction) -> str:
    field = extraction.by_key().get("vendor_tax_id")
    if field is None:
        return ""
    value = field.normalized.get("tax_id")
    return value if isinstance(value, str) else ""


def _store_raw(document: Document, payload: dict[str, object]) -> str:
    key = f"{tenant_prefix(document.company_id)}/textract/{document.id}.json.gz"
    body = gzip.compress(json.dumps(payload).encode("utf-8"))
    get_storage().put_bytes(
        bucket=settings.AWS_S3_BUCKET,
        key=key,
        body=body,
        content_type="application/gzip",
    )
    return key


def _fail(document_id: UUID, reason: str) -> None:
    with transaction.atomic():
        document = Document.unscoped.select_for_update().get(id=document_id)
        if document.status != Document.Status.PROCESSING:
            return
        _fail_locked(document, reason)


def _fail_locked(document: Document, reason: str) -> None:
    previous = document.transition_to(Document.Status.FAILED)
    document.failure_reason = reason
    document.processed_at = timezone.now()
    document.save(update_fields=["status", "version", "failure_reason", "processed_at", "updated_at"])
    _event(document, None, "failed", previous, document.status, {"reason": reason})


def _event(
    document: Document,
    actor: object,
    action: str,
    from_status: str,
    to_status: str,
    metadata: dict[str, object],
) -> None:
    from docintel.apps.core.models import User

    DocumentEvent.objects.for_company(document.company).create(
        company=document.company,
        document=document,
        actor=actor if isinstance(actor, User) else None,
        action=action,
        from_status=from_status,
        to_status=to_status,
        metadata=metadata,
    )


def _after_extract(company_id: UUID, document_id: UUID, status: str) -> None:
    from docintel.apps.documents.notifications import publish_status, schedule_review_digest

    publish_status(company_id, document_id, status)
    if status == Document.Status.NEEDS_REVIEW:
        schedule_review_digest(company_id)


def _enqueue_ingest(document_id: UUID) -> None:
    from docintel.apps.documents.tasks import ingest_textract_job

    ingest_textract_job.delay(str(document_id))


def company_for(document_id: UUID) -> Company | None:
    row = Document.unscoped.filter(id=document_id).select_related("company").first()
    if row is None:
        return None
    return row.company
