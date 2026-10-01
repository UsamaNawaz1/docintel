"""Typed environment access.

Production calls ``required`` so a missing secret fails at boot, not on the
first request that happens to need it.
"""

from __future__ import annotations

import os
from decimal import Decimal
from urllib.parse import unquote, urlparse

from django.core.exceptions import ImproperlyConfigured


def optional(name: str, default: str) -> str:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value


def required(name: str) -> str:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        raise ImproperlyConfigured(f"Missing required environment variable: {name}")
    return value


def as_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def as_int(name: str, default: int) -> int:
    raw = optional(name, str(default))
    try:
        return int(raw)
    except ValueError as exc:
        raise ImproperlyConfigured(f"{name} must be an integer") from exc


def as_decimal(name: str, default: str) -> Decimal:
    raw = optional(name, default)
    try:
        return Decimal(raw)
    except ArithmeticError as exc:
        raise ImproperlyConfigured(f"{name} must be a decimal") from exc


def database_from_url(url: str, *, conn_max_age: int = 60) -> dict[str, object]:
    """Parse a ``postgres://`` URL into Django's DATABASES entry."""
    parsed = urlparse(url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ImproperlyConfigured("DATABASE_URL must use the postgres scheme")
    name = parsed.path.lstrip("/")
    if not name:
        raise ImproperlyConfigured("DATABASE_URL is missing a database name")
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": name,
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname or "",
        "PORT": "" if parsed.port is None else str(parsed.port),
        "CONN_MAX_AGE": conn_max_age,
        "OPTIONS": {"connect_timeout": 3},
    }


def csv_list(name: str, default: str) -> list[str]:
    raw = optional(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]
