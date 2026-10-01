"""Outbox semantics: rollback, backoff, dead letter, replay, HMAC."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.db import transaction
from django.utils import timezone

from docintel.apps.sync.mapping import sign_body
from docintel.apps.sync.models import SyncDeliveryLog, SyncEvent
from docintel.apps.sync.services import (
    deliver_event,
    emit_event,
    full_jitter_delay,
    replay_event,
)
from docintel.tests.factories import CompanyFactory, SyncRuleFactory


def test_full_jitter_is_within_the_cap() -> None:
    delay = full_jitter_delay(attempt=3, base=2.0, cap=10.0)
    assert 0 <= delay <= 10.0


@pytest.mark.django_db
def test_rolled_back_transaction_does_not_keep_the_event() -> None:
    company = CompanyFactory()
    with pytest.raises(RuntimeError), transaction.atomic():
        emit_event(
            company=company,
            event_type="document.approved",
            aggregate_type="document",
            aggregate_id=company.id,
            payload={"total": "1.00"},
            idempotency_key="document.approved:rollback",
        )
        raise RuntimeError("boom")
    assert SyncEvent.unscoped.count() == 0


@pytest.mark.django_db
def test_delivery_dead_letters_and_replay_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "docintel.apps.sync.services.get_tuning",
        lambda: type(
            "T",
            (),
            {
                "sync_max_attempts": 2,
                "sync_backoff_base_seconds": 1.0,
                "sync_backoff_cap_seconds": 10.0,
                "sync_sweep_batch": 10,
            },
        )(),
    )
    company = CompanyFactory()
    SyncRuleFactory(company=company)

    def poster(**kwargs: object) -> object:
        from docintel.apps.sync.mapping import DeliveryResult

        body = kwargs["body"]
        headers = kwargs["headers"]
        assert isinstance(body, bytes)
        assert isinstance(headers, dict)
        assert headers["X-Docintel-Signature"] == sign_body("secret", body)
        assert headers["Idempotency-Key"]
        return DeliveryResult(status_code=500, body="no", latency_ms=3, error="")

    event = emit_event(
        company=company,
        event_type="document.approved",
        aggregate_type="document",
        aggregate_id=company.id,
        payload={"total": "10.00"},
        idempotency_key="document.approved:1",
    )
    deliver_event(event.id, poster=poster)  # type: ignore[arg-type]
    deliver_event(event.id, poster=poster)  # type: ignore[arg-type]
    event.refresh_from_db()
    assert event.status == SyncEvent.Status.DEAD_LETTER
    assert SyncDeliveryLog.unscoped.filter(event=event).count() == 2
    replay_event(company=company, event_id=event.id)
    event.refresh_from_db()
    assert event.status == SyncEvent.Status.PENDING
    assert event.idempotency_key == "document.approved:1"
    again = replay_event(company=company, event_id=event.id)
    assert again.status == SyncEvent.Status.PENDING


@pytest.mark.django_db
def test_successful_delivery_marks_the_event() -> None:
    company = CompanyFactory()
    SyncRuleFactory(company=company)

    def poster(**kwargs: object) -> object:
        from docintel.apps.sync.mapping import DeliveryResult

        return DeliveryResult(status_code=204, body="", latency_ms=1)

    event = emit_event(
        company=company,
        event_type="document.approved",
        aggregate_type="document",
        aggregate_id=company.id,
        payload={"total": "10.00"},
        idempotency_key="ok",
    )
    deliver_event(event.id, poster=poster)  # type: ignore[arg-type]
    event.refresh_from_db()
    assert event.status == SyncEvent.Status.DELIVERED
    assert timezone.now() - event.created_at < timedelta(minutes=5)
