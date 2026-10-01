"""Celery entrypoints for the outbox. Business rules live in ``services``."""

from __future__ import annotations

from uuid import UUID

from celery import Task, shared_task

from docintel.apps.sync.services import deliver_event, sweep_outbox


class SyncTask(Task):
    abstract = True
    acks_late = True
    reject_on_worker_lost = True


@shared_task(base=SyncTask, name="sync.deliver_event", queue="default")
def deliver_sync_event(event_id: str) -> None:
    deliver_event(UUID(event_id))


@shared_task(base=SyncTask, name="sync.sweep_outbox", queue="default")
def sweep_outbox_task() -> int:
    return sweep_outbox()
