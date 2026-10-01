"""structlog configuration and the Sentry ``before_send`` scrubber."""

from __future__ import annotations

import logging
from typing import Any

import structlog

_REDACT_KEYS = frozenset(
    {
        "email",
        "password",
        "authorization",
        "tax_id",
        "secret",
        "signing_secret",
        "value",
        "normalized_value",
        "token",
        "access",
        "refresh",
        "cookie",
    }
)


def configure_logging(*, json_logs: bool, level: str) -> None:
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    shared: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer() if json_logs else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
    )
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


def scrub_event(value: object) -> object:
    """Drop PII before it leaves the process.

    Key matches are exact and case-insensitive. Redacting ``value`` also
    catches extracted invoice fields that would otherwise land in ``extra``.
    """
    if isinstance(value, dict):
        cleaned: dict[object, object] = {}
        for key, item in value.items():
            if isinstance(key, str) and key.lower() in _REDACT_KEYS:
                cleaned[key] = "[Redacted]"
            else:
                cleaned[key] = scrub_event(item)
        return cleaned
    if isinstance(value, list):
        return [scrub_event(item) for item in value]
    return value


def before_send(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
    del hint
    scrubbed = scrub_event(event)
    if isinstance(scrubbed, dict):
        return scrubbed
    return event
