"""SNS entrypoint. Signature first, then an idempotent ingest enqueue."""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

import structlog

from docintel.apps.core.exceptions import DomainError
from docintel.apps.documents.models import Document
from docintel.apps.documents.processing import _fail
from docintel.apps.documents.sns import (
    confirm_subscription,
    fetch_certificate,
    parse_notification,
    verify_signature,
)

logger = structlog.get_logger(__name__)


def handle_sns(payload: Mapping[str, object]) -> None:
    message = {str(key): str(value) for key, value in payload.items() if isinstance(value, str)}
    cert_url = message.get("SigningCertURL", "")
    if not cert_url:
        raise DomainError("SNS message has no signing certificate.", code="invalid_sns_message")
    certificate = fetch_certificate(cert_url)
    verify_signature(message, certificate)
    kind = message.get("Type")
    if kind == "SubscriptionConfirmation":
        confirm_subscription(message["SubscribeURL"])
        logger.info("sns_subscription_confirmed")
        return
    if kind != "Notification":
        return
    body = parse_notification(message)
    job_id = str(body.get("JobId") or "")
    status = str(body.get("Status") or "")
    if not job_id:
        return
    document = Document.unscoped.filter(textract_job_id=job_id).only("id", "status").first()
    if document is None:
        # The start call may not have stored the job id yet. The poller retries.
        logger.info("sns_job_unknown", textract_job_id=job_id, status=status)
        return
    if status == "SUCCEEDED":
        _enqueue(document.id)
        return
    if status == "FAILED" and document.status == Document.Status.PROCESSING:
        _fail(document.id, "textract_job_failed")


def _enqueue(document_id: UUID) -> None:
    from docintel.apps.documents.tasks import ingest_textract_job

    ingest_textract_job.delay(str(document_id))
