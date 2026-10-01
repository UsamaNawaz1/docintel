"""Behaviour knobs.

Every threshold, TTL, and retry budget lives here so a reviewer can see the
operating point of the system without hunting through services. Companies may
override the fields listed in ``COMPANY_OVERRIDABLE``.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from decimal import Decimal
from functools import lru_cache

from docintel.config.settings.env import as_decimal, as_int


@dataclass(frozen=True)
class Tuning:
    confidence_threshold: Decimal = Decimal("0.85")
    amount_tolerance: Decimal = Decimal("0.05")
    vendor_similarity_threshold: float = 0.45
    textract_poll_after_seconds: int = 120
    textract_poll_batch: int = 50
    sync_max_attempts: int = 8
    sync_backoff_base_seconds: float = 2.0
    sync_backoff_cap_seconds: float = 3600.0
    sync_sweep_batch: int = 100
    upload_url_ttl_seconds: int = 300
    download_url_ttl_seconds: int = 120
    max_upload_bytes: int = 20 * 1024 * 1024
    max_pages: int = 20
    import_chunk_size: int = 1000
    import_preview_rows: int = 20
    import_error_response_limit: int = 500
    review_digest_debounce_seconds: int = 300
    webhook_timeout_seconds: float = 10.0
    cursor_page_size: int = 25


COMPANY_OVERRIDABLE = frozenset(
    {
        "confidence_threshold",
        "amount_tolerance",
        "vendor_similarity_threshold",
    }
)

_DECIMAL_FIELDS = frozenset({"confidence_threshold", "amount_tolerance"})
_FLOAT_FIELDS = frozenset({"vendor_similarity_threshold"})


@lru_cache(maxsize=1)
def get_tuning() -> Tuning:
    return Tuning(
        confidence_threshold=as_decimal("DOCINTEL_CONFIDENCE_THRESHOLD", "0.85"),
        amount_tolerance=as_decimal("DOCINTEL_AMOUNT_TOLERANCE", "0.05"),
        vendor_similarity_threshold=float(as_decimal("DOCINTEL_VENDOR_SIMILARITY", "0.45")),
        textract_poll_after_seconds=as_int("DOCINTEL_TEXTRACT_POLL_AFTER_SECONDS", 120),
        sync_max_attempts=as_int("DOCINTEL_SYNC_MAX_ATTEMPTS", 8),
        upload_url_ttl_seconds=as_int("DOCINTEL_UPLOAD_URL_TTL_SECONDS", 300),
        download_url_ttl_seconds=as_int("DOCINTEL_DOWNLOAD_URL_TTL_SECONDS", 120),
        max_upload_bytes=as_int("DOCINTEL_MAX_UPLOAD_BYTES", 20 * 1024 * 1024),
        max_pages=as_int("DOCINTEL_MAX_PAGES", 20),
        import_chunk_size=as_int("DOCINTEL_IMPORT_CHUNK_SIZE", 1000),
        review_digest_debounce_seconds=as_int("DOCINTEL_REVIEW_DIGEST_DEBOUNCE_SECONDS", 300),
    )


def clear_tuning_cache() -> None:
    get_tuning.cache_clear()


def company_tuning(settings: dict[str, object]) -> Tuning:
    """Apply the small set of per-tenant overrides stored on ``Company.settings``."""
    overrides: dict[str, object] = {}
    for name in COMPANY_OVERRIDABLE:
        if name not in settings:
            continue
        raw = settings[name]
        if name in _DECIMAL_FIELDS:
            overrides[name] = Decimal(str(raw))
        elif name in _FLOAT_FIELDS:
            overrides[name] = float(str(raw))
        else:
            overrides[name] = raw
    known = {item.name for item in fields(Tuning)}
    unknown = set(overrides) - known
    if unknown:
        raise ValueError(f"Unknown tuning fields: {sorted(unknown)}")
    return replace(get_tuning(), **overrides)
