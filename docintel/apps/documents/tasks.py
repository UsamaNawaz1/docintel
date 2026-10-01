"""OCR queue. Transient Textract errors retry; terminal errors are recorded on the document."""

from __future__ import annotations

import time
from uuid import UUID

import structlog
from celery import Task, shared_task

from docintel.apps.documents.adapters import TransientTextractError
from docintel.apps.documents.processing import begin_textract, ingest_job, poll_stuck_documents

logger = structlog.get_logger(__name__)


class OcrTask(Task):
    abstract = True
    acks_late = True
    reject_on_worker_lost = True
    autoretry_for = (TransientTextractError,)
    retry_backoff = True
    retry_backoff_max = 600
    retry_jitter = True
    max_retries = 5
    soft_time_limit = 60
    time_limit = 90

    def __call__(self, *args: object, **kwargs: object) -> object:
        started = time.perf_counter()
        try:
            result = super().__call__(*args, **kwargs)
        except Exception:
            logger.exception(
                "celery_task_failed",
                task=self.name,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            raise
        logger.info(
            "celery_task_finished",
            task=self.name,
            outcome="success",
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return result


@shared_task(base=OcrTask, name="documents.start_expense_analysis", queue="ocr")
def start_expense_analysis(document_id: str) -> None:
    begin_textract(UUID(document_id))


@shared_task(base=OcrTask, name="documents.ingest_textract_job", queue="ocr")
def ingest_textract_job(document_id: str) -> None:
    ingest_job(UUID(document_id))


@shared_task(base=OcrTask, name="documents.poll_stuck_documents", queue="ocr")
def poll_stuck_documents_task() -> int:
    return poll_stuck_documents()


@shared_task(name="documents.send_review_digest", queue="default")
def send_review_digest_task(company_id: str) -> None:
    from docintel.apps.documents.notifications import send_review_digest

    send_review_digest(UUID(company_id))
