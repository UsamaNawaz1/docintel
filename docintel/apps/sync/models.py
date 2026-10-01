"""Transactional outbox and delivery log.

``emit_event`` inserts in the caller's transaction. Dispatch is scheduled with
``transaction.on_commit``, so a rolled-back business transaction cannot leave
a row behind or a task in the queue. The sweeper is the backstop for a
process that died after commit and before the broker accepted the message.
"""

from __future__ import annotations

from django.db import models

from docintel.apps.core.models import TenantScopedModel


class SyncEvent(TenantScopedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        DELIVERED = "delivered", "Delivered"
        DEAD_LETTER = "dead_letter", "Dead letter"

    event_type = models.CharField(max_length=80)
    aggregate_type = models.CharField(max_length=80)
    aggregate_id = models.UUIDField()
    payload = models.JSONField()
    idempotency_key = models.CharField(max_length=200)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField()
    last_error = models.TextField(blank=True)

    class Meta:
        abstract = False
        base_manager_name = "unscoped"
        default_manager_name = "objects"
        db_table = "sync_event"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "idempotency_key"],
                name="sync_event_idempotency",
            ),
        ]
        indexes = [
            # Sweeper: pending rows whose next attempt is due.
            models.Index(
                fields=["status", "next_attempt_at"],
                name="sync_event_due",
            ),
        ]


class SyncRule(TenantScopedModel):
    """One destination for an event type.

    ``field_mapping`` is ``{"mappings": [{"source": "a.b", "target": "c"}]}``.
    It is validated with pydantic before a rule is saved and again before send.
    """

    event_type = models.CharField(max_length=80)
    destination_url = models.URLField(max_length=500)
    signing_secret = models.CharField(max_length=200)
    field_mapping = models.JSONField(default=dict)
    is_active = models.BooleanField(default=True)
    timeout_seconds = models.PositiveSmallIntegerField(default=10)

    class Meta:
        abstract = False
        base_manager_name = "unscoped"
        default_manager_name = "objects"
        db_table = "sync_rule"
        indexes = [
            models.Index(fields=["company", "event_type", "is_active"], name="sync_rule_lookup"),
        ]


class SyncDeliveryLog(TenantScopedModel):
    """One row per HTTP attempt. The response body is truncated on write."""

    event = models.ForeignKey(SyncEvent, on_delete=models.CASCADE, related_name="deliveries")
    rule = models.ForeignKey(SyncRule, on_delete=models.PROTECT, related_name="deliveries")
    attempt = models.PositiveIntegerField()
    status_code = models.PositiveIntegerField(default=0)
    latency_ms = models.PositiveIntegerField(default=0)
    response_body = models.TextField(blank=True)
    error = models.TextField(blank=True)
    succeeded = models.BooleanField(default=False)

    class Meta:
        abstract = False
        base_manager_name = "unscoped"
        default_manager_name = "objects"
        db_table = "sync_delivery_log"
        indexes = [
            models.Index(fields=["event", "rule", "succeeded"], name="sync_delivery_success"),
        ]
