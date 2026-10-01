"""Reviewer digest and the realtime status fan-out.

The digest is debounced with a Redis ``SET NX`` key. Fifty documents landing
in review inside the TTL produce one countdown task and therefore one email.
The pub/sub channel ``tenant:{company_id}`` is what a Socket.IO process would
subscribe to; this service only publishes.
"""

from __future__ import annotations

import json
from uuid import UUID

import structlog

from docintel.apps.core.redis import get_redis
from docintel.config.settings.tuning import get_tuning

logger = structlog.get_logger(__name__)


def publish_status(company_id: UUID, document_id: UUID, status: str) -> None:
    message = json.dumps(
        {
            "type": "document.status_changed",
            "document_id": str(document_id),
            "status": status,
        }
    )
    get_redis().publish(f"tenant:{company_id}", message)


def schedule_review_digest(company_id: UUID) -> None:
    ttl = get_tuning().review_digest_debounce_seconds
    key = f"review-digest:{company_id}"
    created = get_redis().set(key, "1", nx=True, ex=ttl)
    if not created:
        return
    _enqueue_digest(company_id, countdown=ttl)


def send_review_digest(company_id: UUID) -> None:
    from django.conf import settings

    from docintel.apps.core.models import Company, Membership
    from docintel.apps.documents.emails import send_email
    from docintel.apps.documents.models import Document

    company = Company.objects.filter(id=company_id).first()
    if company is None:
        return
    pending = (
        Document.objects.for_company(company)
        .filter(status=Document.Status.NEEDS_REVIEW)
        .order_by("created_at")
        .values_list("id", "original_filename")[:50]
    )
    rows = list(pending)
    if not rows:
        return
    recipients = list(
        Membership.objects.for_company(company)
        .filter(role__in=[Membership.Role.OWNER, Membership.Role.ADMIN, Membership.Role.REVIEWER])
        .select_related("user")
        .values_list("user__email", flat=True)
    )
    if not recipients:
        return
    lines = "\n".join(f"- {filename} ({document_id})" for document_id, filename in rows)
    send_email(
        sender=settings.AWS_SES_SENDER,
        recipients=recipients,
        subject=f"{len(rows)} document(s) need review",
        body=f"The following documents are waiting for review:\n{lines}\n",
    )
    logger.info("review_digest_sent", company_id=str(company_id), documents=len(rows))


def _enqueue_digest(company_id: UUID, *, countdown: int) -> None:
    from docintel.apps.documents.tasks import send_review_digest_task

    send_review_digest_task.apply_async((str(company_id),), countdown=countdown)
