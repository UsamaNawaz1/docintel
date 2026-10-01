"""Post-extraction checks. A hit sends the document to review; it does not reject it."""

from __future__ import annotations

from decimal import Decimal

from docintel.apps.documents.normalization import (
    REQUIRED_KEYS,
    Extraction,
    money_amount,
)
from docintel.config.settings.tuning import Tuning


def review_reasons(extraction: Extraction, tuning: Tuning) -> list[str]:
    reasons: list[str] = []
    fields = extraction.by_key()
    for key in REQUIRED_KEYS:
        field = fields.get(key)
        if field is None or not _present(field.normalized):
            reasons.append(f"missing:{key}")
            continue
        if field.confidence < tuning.confidence_threshold:
            reasons.append(f"low_confidence:{key}")
    subtotal = money_amount(fields.get("subtotal"))
    tax = money_amount(fields.get("tax"))
    total = money_amount(fields.get("total"))
    if subtotal is not None and extraction.lines:
        line_sum = sum((line.amount or Decimal("0") for line in extraction.lines), Decimal("0"))
        if abs(line_sum - subtotal) > tuning.amount_tolerance:
            reasons.append("line_items_unbalanced")
    if (
        subtotal is not None
        and tax is not None
        and total is not None
        and abs((subtotal + tax) - total) > tuning.amount_tolerance
    ):
        reasons.append("total_unbalanced")
    return reasons


def _present(normalized: dict[str, object]) -> bool:
    return any(value not in (None, "") for value in normalized.values())
