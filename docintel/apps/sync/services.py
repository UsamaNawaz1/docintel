"""Outbox write, fan-out, backoff, and dead-letter replay.

Delivery does not hold a row lock across the HTTP call. The event is marked
``processing``, the lock is released, each rule is attempted, then a second
transaction records the outcome. A duplicate worker observes ``delivered`` or
an existing success log and does nothing.
"""

from __future__ import annotations

import json
import random
from datetime import timedelta
from typing import Any
from uuid import UUID

import structlog
from django.db import transaction
from django.utils import timezone
from pydantic import ValidationError

from docintel.apps.core.models import Company
from docintel.apps.sync.http import post_json
from docintel.apps.sync.mapping import (
    DeliveryResult,
    FieldMappingConfig,
    Poster,
    apply_mapping,
    sign_body,
)
from docintel.apps.sync.models import SyncDeliveryLog, SyncEvent, SyncRule
from docintel.config.settings.tuning import get_tuning

logger = structlog.get_logger(__name__)


def full_jitter_delay(*, attempt: int, base: float, cap: float) -> float:
    """Exponential backoff with full jitter (AWS architecture blog).

    ``attempt`` is the number of failures so far, starting at 1.
    """
    ceiling = min(cap, base * (2**attempt))
    return random.uniform(0, ceiling)


def emit_event(
    *,
    company: Company,
    event_type: str,
    aggregate_type: str,
    aggregate_id: UUID,
    payload: dict[str, Any],
    idempotency_key: str,
) -> SyncEvent:
    """Insert an outbox row in the caller's transaction.

    The Celery enqueue is registered with ``on_commit``. If the caller rolls
    back, neither the row nor the task survives.
    """
    event, created = SyncEvent.unscoped.get_or_create(
        company=company,
        idempotency_key=idempotency_key,
        defaults={
            "event_type": event_type,
            "aggregate_type": aggregate_type,
            "aggregate_id": aggregate_id,
            "payload": payload,
            "status": SyncEvent.Status.PENDING,
            "next_attempt_at": timezone.now(),
        },
    )
    if created:
        event_id = event.id
        transaction.on_commit(lambda eid=event_id: _enqueue(eid))
    return event


def sweep_outbox(*, limit: int | None = None) -> int:
    """Claim due rows with ``FOR UPDATE SKIP LOCKED`` and enqueue them.

    Two beat processes can run this together. A row locked by one is invisible
    to the other, so a delivery is not started twice from the sweeper.
    """
    tuning = get_tuning()
    batch = limit if limit is not None else tuning.sync_sweep_batch
    now = timezone.now()
    with transaction.atomic():
        due = (
            SyncEvent.unscoped.select_for_update(skip_locked=True)
            .filter(status=SyncEvent.Status.PENDING, next_attempt_at__lte=now)
            .order_by("next_attempt_at")
        )
        events = list(due[:batch])
        for event in events:
            event.status = SyncEvent.Status.PROCESSING
            event.save(update_fields=["status", "updated_at"])
        claimed = [event.id for event in events]
    for event_id in claimed:
        _enqueue(event_id)
    return len(claimed)


def deliver_event(event_id: UUID, *, poster: Poster = post_json) -> None:
    event = _claim(event_id)
    if event is None:
        return
    structlog.contextvars.bind_contextvars(
        company_id=str(event.company_id),
        sync_event_id=str(event.id),
    )
    rules = list(
        SyncRule.objects.for_company(event.company).filter(
            event_type=event.event_type,
            is_active=True,
        )
    )
    if not rules:
        _mark(event.id, status=SyncEvent.Status.DELIVERED, error="", retry_in=None)
        return
    failures: list[str] = []
    for rule in rules:
        if _already_succeeded(event.id, rule.id):
            continue
        result = _attempt(event, rule, poster=poster)
        if not result.ok:
            failures.append(result.error or f"HTTP {result.status_code}")
    if failures:
        _schedule_retry(event.id, "; ".join(failures))
        return
    _mark(event.id, status=SyncEvent.Status.DELIVERED, error="", retry_in=None)


def replay_event(*, company: Company, event_id: UUID) -> SyncEvent:
    """Move a dead-lettered event back to pending.

    The idempotency key is unchanged, so a destination that already applied
    the event can no-op on the ``Idempotency-Key`` header. Replaying a row
    that is not dead-lettered is a no-op.
    """
    with transaction.atomic():
        event = SyncEvent.objects.for_company(company).select_for_update().get(id=event_id)
        if event.status != SyncEvent.Status.DEAD_LETTER:
            return event
        event.status = SyncEvent.Status.PENDING
        event.attempts = 0
        event.next_attempt_at = timezone.now()
        event.last_error = ""
        event.save(update_fields=["status", "attempts", "next_attempt_at", "last_error", "updated_at"])
        transaction.on_commit(lambda eid=event.id: _enqueue(eid))
    return event


def _enqueue(event_id: UUID) -> None:
    from docintel.apps.sync.tasks import deliver_sync_event

    deliver_sync_event.delay(str(event_id))


def _claim(event_id: UUID) -> SyncEvent | None:
    with transaction.atomic():
        try:
            event = SyncEvent.unscoped.select_for_update().select_related("company").get(id=event_id)
        except SyncEvent.DoesNotExist:
            return None
        if event.status in {SyncEvent.Status.DELIVERED, SyncEvent.Status.DEAD_LETTER}:
            return None
        event.status = SyncEvent.Status.PROCESSING
        event.save(update_fields=["status", "updated_at"])
        return event


def _already_succeeded(event_id: UUID, rule_id: UUID) -> bool:
    return SyncDeliveryLog.unscoped.filter(
        event_id=event_id,
        rule_id=rule_id,
        succeeded=True,
    ).exists()


def _attempt(event: SyncEvent, rule: SyncRule, *, poster: Poster) -> DeliveryResult:
    try:
        config = FieldMappingConfig.model_validate(rule.field_mapping)
    except ValidationError as exc:
        result = DeliveryResult(status_code=0, body="", latency_ms=0, error=f"mapping: {exc}")
        _log(event, rule, result)
        return result
    mapped = apply_mapping(event.payload, config)
    body = json.dumps(mapped, separators=(",", ":"), default=str).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Idempotency-Key": event.idempotency_key,
        "X-Docintel-Signature": sign_body(rule.signing_secret, body),
    }
    result = poster(
        url=rule.destination_url,
        body=body,
        headers=headers,
        timeout=float(rule.timeout_seconds),
    )
    _log(event, rule, result)
    return result


def _log(event: SyncEvent, rule: SyncRule, result: DeliveryResult) -> None:
    SyncDeliveryLog.unscoped.create(
        company_id=event.company_id,
        event=event,
        rule=rule,
        attempt=event.attempts + 1,
        status_code=result.status_code,
        latency_ms=result.latency_ms,
        response_body=result.body,
        error=result.error,
        succeeded=result.ok,
    )


def _schedule_retry(event_id: UUID, error: str) -> None:
    tuning = get_tuning()
    with transaction.atomic():
        event = SyncEvent.unscoped.select_for_update().get(id=event_id)
        event.attempts += 1
        event.last_error = error[:2_000]
        if event.attempts >= tuning.sync_max_attempts:
            event.status = SyncEvent.Status.DEAD_LETTER
            event.save(update_fields=["attempts", "last_error", "status", "updated_at"])
            logger.warning("sync_dead_letter", event_id=str(event_id), attempts=event.attempts)
            return
        delay = full_jitter_delay(
            attempt=event.attempts,
            base=tuning.sync_backoff_base_seconds,
            cap=tuning.sync_backoff_cap_seconds,
        )
        event.status = SyncEvent.Status.PENDING
        event.next_attempt_at = timezone.now() + timedelta(seconds=delay)
        event.save(
            update_fields=[
                "attempts",
                "last_error",
                "status",
                "next_attempt_at",
                "updated_at",
            ]
        )


def _mark(event_id: UUID, *, status: str, error: str, retry_in: float | None) -> None:
    del retry_in
    with transaction.atomic():
        event = SyncEvent.unscoped.select_for_update().get(id=event_id)
        event.status = status
        event.last_error = error
        event.save(update_fields=["status", "last_error", "updated_at"])
