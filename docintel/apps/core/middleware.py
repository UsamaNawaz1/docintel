"""Request correlation and access logs."""

from __future__ import annotations

import time
import uuid

import structlog
from django.http import HttpRequest, HttpResponse

logger = structlog.get_logger(__name__)


class RequestIDMiddleware:
    """Accept ``X-Request-ID`` or mint one, and bind it for the whole request."""

    def __init__(self, get_response):  # type: ignore[no-untyped-def]
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        incoming = request.headers.get("X-Request-ID", "").strip()
        request_id = incoming or str(uuid.uuid4())
        request.request_id = request_id  # type: ignore[attr-defined]
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        try:
            import sentry_sdk

            sentry_sdk.set_tag("request_id", request_id)
        except Exception:
            # Sentry is optional in local and test. A missing SDK must not
            # fail the request, and this is the process boundary for that SDK.
            logger.debug("sentry_unavailable")
        response = self.get_response(request)
        response["X-Request-ID"] = request_id
        return response


class AccessLogMiddleware:
    """One line per request. Bodies are never logged."""

    def __init__(self, get_response):  # type: ignore[no-untyped-def]
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        started = time.perf_counter()
        response = self.get_response(request)
        logger.info(
            "http_request",
            method=request.method,
            path=request.path,
            status=response.status_code,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return response
