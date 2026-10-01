"""Map every API failure onto ``{"error": {"code", "message", "details"}}``."""

from __future__ import annotations

from typing import Any

import structlog
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from docintel.apps.core.exceptions import DomainError

logger = structlog.get_logger(__name__)

_STATUS_CODES = {
    status.HTTP_400_BAD_REQUEST: "validation_error",
    status.HTTP_401_UNAUTHORIZED: "authentication_failed",
    status.HTTP_403_FORBIDDEN: "permission_denied",
    status.HTTP_404_NOT_FOUND: "not_found",
    status.HTTP_405_METHOD_NOT_ALLOWED: "method_not_allowed",
    status.HTTP_409_CONFLICT: "conflict",
    status.HTTP_412_PRECONDITION_FAILED: "precondition_failed",
    status.HTTP_428_PRECONDITION_REQUIRED: "precondition_required",
    status.HTTP_429_TOO_MANY_REQUESTS: "rate_limited",
}


def exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    if isinstance(exc, DomainError):
        return Response(
            {"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
            status=exc.status_code,
        )
    response = drf_exception_handler(exc, context)
    if response is None:
        logger.exception("unhandled_exception")
        try:
            import sentry_sdk

            sentry_sdk.capture_exception(exc)
        except ImportError:
            logger.debug("sentry_sdk_missing")
        return Response(
            {
                "error": {
                    "code": "internal_error",
                    "message": "Internal server error.",
                    "details": {},
                }
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    code = _STATUS_CODES.get(response.status_code, "error")
    message = _message(response.data)
    details = response.data if isinstance(response.data, dict) else {"errors": response.data}
    response.data = {"error": {"code": code, "message": message, "details": details}}
    return response


def _message(data: object) -> str:
    if isinstance(data, dict):
        detail = data.get("detail")
        if detail is not None:
            return str(detail)
    if isinstance(data, list) and data:
        return str(data[0])
    return "Request failed."
