"""Commit task. The service owns idempotency; this module only draws the boundary."""

from __future__ import annotations

from uuid import UUID

import structlog
from celery import Task, shared_task
from django.db import InterfaceError, OperationalError

from docintel.apps.imports.services import run_commit

logger = structlog.get_logger(__name__)


class ImportTask(Task):
    abstract = True
    acks_late = True
    reject_on_worker_lost = True
    autoretry_for = (OperationalError, InterfaceError)
    retry_backoff = True
    retry_jitter = True
    max_retries = 4


@shared_task(
    base=ImportTask,
    name="imports.commit_job",
    queue="default",
    soft_time_limit=300,
    time_limit=360,
)
def commit_import_job(job_id: str) -> None:
    try:
        run_commit(UUID(job_id))
    except (OperationalError, InterfaceError):
        raise
    except Exception:
        logger.exception("import_commit_failed", job_id=job_id)
        raise
