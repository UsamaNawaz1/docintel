"""Liveness and readiness.

``/healthz`` only proves the process can answer. ``/readyz`` checks the
dependencies a request actually needs, each with a short timeout, and never
includes connection strings in the body.
"""

from __future__ import annotations

from django.conf import settings
from django.db import connection
from django.http import HttpRequest, JsonResponse

from docintel.apps.core.redis import ping_redis


def healthz(_request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok"})


def readyz(_request: HttpRequest) -> JsonResponse:
    checks = {
        "db": _check_db(),
        "redis": _check_named(settings.REDIS_URL),
        "broker": _check_named(settings.CELERY_BROKER_URL),
    }
    ready = all(value == "ok" for value in checks.values())
    return JsonResponse({"ready": ready, "checks": checks}, status=200 if ready else 503)


def _check_db() -> str:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        # Readiness is a process boundary: one down dependency must be a
        # failed check, not an unhandled exception.
        return "error"
    return "ok"


def _check_named(url: str) -> str:
    try:
        ping_redis(url)
    except Exception:
        return "error"
    return "ok"
