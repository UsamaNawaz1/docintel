"""Direct-to-S3 upload sessions.

``complete_upload`` does not trust the content type the client declared. It
reads the object header, checks magic bytes, hashes the body, and only then
moves the row to ``uploaded``. A second complete call returns the same row
and does not enqueue processing again.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import structlog
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from docintel.apps.core.exceptions import DomainError, NotFound
from docintel.apps.core.models import Company, User
from docintel.apps.core.storage import (
    PresignedPost,
    Storage,
    assert_tenant_key,
    get_storage,
    tenant_prefix,
)
from docintel.apps.documents.models import Document, DocumentEvent
from docintel.config.settings.tuning import get_tuning

logger = structlog.get_logger(__name__)

_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"%PDF", "application/pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"II*\x00", "image/tiff"),
    (b"MM\x00*", "image/tiff"),
)


@dataclass(frozen=True)
class UploadSession:
    document: Document
    presigned: PresignedPost


def sanitize_filename(name: str) -> str:
    base = os.path.basename(name.replace("\\", "/")).replace("\x00", "")
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", base).strip("._")
    return (cleaned or "document")[:180]


def build_object_key(*, company_id: UUID, document_id: UUID, filename: str, when: datetime) -> str:
    safe = sanitize_filename(filename)
    return f"{tenant_prefix(company_id)}/documents/{when:%Y}/{when:%m}/{document_id}/{safe}"


def create_upload(
    *,
    company: Company,
    user: User,
    filename: str,
    content_type: str,
    size_bytes: int,
    storage: Storage | None = None,
) -> UploadSession:
    tuning = get_tuning()
    allowed = settings.ALLOWED_UPLOAD_CONTENT_TYPES
    if content_type not in allowed:
        raise DomainError(
            "Content type is not allowed.",
            code="invalid_content_type",
            details={"allowed": list(allowed)},
        )
    if size_bytes < 1 or size_bytes > tuning.max_upload_bytes:
        raise DomainError(
            "File size is outside the allowed range.",
            code="invalid_size",
            details={"max_bytes": tuning.max_upload_bytes},
        )
    now = timezone.now()
    document = Document(
        company=company,
        uploaded_by=user,
        original_filename=sanitize_filename(filename),
        content_type=content_type,
        size_bytes=0,
        status=Document.Status.PENDING_UPLOAD,
    )
    document.s3_key = build_object_key(
        company_id=company.id,
        document_id=document.id,
        filename=filename,
        when=now,
    )
    document.save()
    store = storage or get_storage()
    presigned = store.create_presigned_post(
        bucket=settings.AWS_S3_BUCKET,
        key=document.s3_key,
        content_type=content_type,
        max_bytes=tuning.max_upload_bytes,
        expires_in=tuning.upload_url_ttl_seconds,
        kms_key_id=settings.AWS_KMS_KEY_ID,
    )
    _event(document, user, "upload_requested", "", document.status, {})
    return UploadSession(document=document, presigned=presigned)


def complete_upload(
    *,
    company: Company,
    user: User,
    document_id: UUID,
    storage: Storage | None = None,
) -> Document:
    """Verify the object and enqueue extraction. Idempotent after the first success."""
    store = storage or get_storage()
    try:
        with transaction.atomic():
            document = _lock(company, document_id)
            if document.status != Document.Status.PENDING_UPLOAD:
                return document
            assert_tenant_key(company.id, document.s3_key)
            head = store.head(bucket=settings.AWS_S3_BUCKET, key=document.s3_key)
            tuning = get_tuning()
            if head.content_length < 1 or head.content_length > tuning.max_upload_bytes:
                raise DomainError("Uploaded object size is not allowed.", code="invalid_size")
            header = store.get_prefix(
                bucket=settings.AWS_S3_BUCKET,
                key=document.s3_key,
                length=16,
            )
            detected = detect_content_type(header)
            if detected is None:
                raise DomainError(
                    "File contents are not a PDF or supported image.",
                    code="invalid_content",
                )
            digest = _sha256(store, document.s3_key)
            duplicate = (
                Document.objects.for_company(company).filter(sha256=digest).exclude(id=document.id).first()
            )
            if duplicate is not None:
                raise DomainError(
                    "This file was already uploaded.",
                    code="duplicate_document",
                    status_code=409,
                    details={"existing_id": str(duplicate.id)},
                )
            previous = document.transition_to(Document.Status.UPLOADED)
            document.content_type = detected
            document.size_bytes = head.content_length
            document.sha256 = digest
            try:
                document.save()
            except IntegrityError as exc:
                raise DomainError(
                    "This file was already uploaded.",
                    code="duplicate_document",
                    status_code=409,
                ) from exc
            _event(document, user, "uploaded", previous, document.status, {"sha256": digest})
            transaction.on_commit(lambda did=document.id: _enqueue_start(did))
    except DomainError as exc:
        if exc.code in {"invalid_size", "invalid_content", "duplicate_document"}:
            _mark_failed(company, document_id, user, exc.code)
        raise
    logger.info("document_uploaded", document_id=str(document.id), company_id=str(company.id))
    return document


def detect_content_type(header: bytes) -> str | None:
    for magic, content_type in _MAGIC:
        if header.startswith(magic):
            return content_type
    return None


def _sha256(store: Storage, key: str) -> str:
    digest = hashlib.sha256()
    for chunk in store.iter_chunks(bucket=settings.AWS_S3_BUCKET, key=key, chunk_size=1024 * 1024):
        digest.update(chunk)
    return digest.hexdigest()


def _lock(company: Company, document_id: UUID) -> Document:
    try:
        return Document.objects.for_company(company).select_for_update().get(id=document_id)
    except Document.DoesNotExist as exc:
        raise NotFound("Document not found.") from exc


def _mark_failed(company: Company, document_id: UUID, user: User, reason: str) -> None:
    """Persist a terminal upload failure in its own transaction.

    The verification transaction has already rolled back, so this is the only
    write that records why complete did not succeed.
    """
    with transaction.atomic():
        document = _lock(company, document_id)
        if document.status != Document.Status.PENDING_UPLOAD:
            return
        previous = document.transition_to(Document.Status.FAILED)
        document.failure_reason = reason
        document.save(update_fields=["status", "version", "failure_reason", "updated_at"])
        _event(document, user, "failed", previous, document.status, {"reason": reason})


def _event(
    document: Document,
    actor: User | None,
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


def _enqueue_start(document_id: UUID) -> None:
    from docintel.apps.documents.tasks import start_expense_analysis

    start_expense_analysis.delay(str(document_id))
