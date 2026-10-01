"""Celery application.

Request correlation travels in task headers so a worker log line can be joined
back to the HTTP request that caused it. See ``RequestIDMiddleware``.
"""

from __future__ import annotations

import os
from typing import Any

from celery import Celery
from celery.signals import before_task_publish, task_prerun

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docintel.config.settings.local")

app = Celery("docintel")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks(
    [
        "docintel.apps.sync",
        "docintel.apps.imports",
        "docintel.apps.documents",
    ]
)
app.conf.task_default_queue = "default"
app.conf.beat_schedule = {
    "sweep-sync-outbox": {
        "task": "sync.sweep_outbox",
        "schedule": 30.0,
    },
    "poll-textract-jobs": {
        "task": "documents.poll_stuck_documents",
        "schedule": 60.0,
    },
}


@before_task_publish.connect
def _copy_request_id(
    headers: dict[str, object] | None = None,
    **_: Any,
) -> None:
    if headers is None:
        return
    import structlog

    request_id = structlog.contextvars.get_contextvars().get("request_id")
    if isinstance(request_id, str) and request_id:
        headers["request_id"] = request_id


@task_prerun.connect
def _bind_task_context(task_id: str, task: object, **_: Any) -> None:
    import structlog

    request = getattr(task, "request", None)
    header_map = getattr(request, "headers", None) or {}
    request_id = header_map.get("request_id")
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(task_id=task_id, request_id=request_id)
