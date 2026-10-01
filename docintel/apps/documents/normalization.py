"""Turn Textract summary fields into our field keys.

The mapping table is the whole policy. Adding a Textract type is a new row,
not another branch. Confidence is stored on a 0-1 scale; Textract reports
0-100, and values already on the unit interval are left alone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Literal

from docintel.apps.documents.schemas import ExpenseAnalysis, ExpenseLine, SummaryField

NormalizerName = Literal["text", "date", "money", "tax_id"]
TWOPLACES = Decimal("0.01")
FOURPLACES = Decimal("0.0001")

_CURRENCY_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY"}
_DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%m/%d/%Y",
    "%m-%d-%Y",
    "%d/%m/%Y",
    "%B %d, %Y",
    "%b %d, %Y",
    "%d %B %Y",
    "%d %b %Y",
)


@dataclass(frozen=True)
class FieldSpec:
    key: str
    normalizer: NormalizerName


# Textract Type.Text -> our key. Unknown types are ignored on purpose.
SUMMARY_FIELDS: dict[str, FieldSpec] = {
    "VENDOR_NAME": FieldSpec("vendor_name", "text"),
    "NAME": FieldSpec("vendor_name", "text"),
    "VENDOR_TAX_ID": FieldSpec("vendor_tax_id", "tax_id"),
    "TAX_PAYER_ID": FieldSpec("vendor_tax_id", "tax_id"),
    "INVOICE_RECEIPT_ID": FieldSpec("invoice_number", "text"),
    "INVOICE_RECEIPT_DATE": FieldSpec("invoice_date", "date"),
    "DUE_DATE": FieldSpec("due_date", "date"),
    "PO_NUMBER": FieldSpec("po_number", "text"),
    "SUBTOTAL": FieldSpec("subtotal", "money"),
    "TAX": FieldSpec("tax", "money"),
    "TOTAL": FieldSpec("total", "money"),
    "AMOUNT_DUE": FieldSpec("amount_due", "money"),
    "CURRENCY": FieldSpec("currency", "text"),
}

LINE_FIELDS = {
    "ITEM": "description",
    "EXPENSE_ROW": "description",
    "QUANTITY": "quantity",
    "UNIT_PRICE": "unit_price",
    "PRICE": "amount",
}

REQUIRED_KEYS = ("vendor_name", "invoice_number", "invoice_date", "total")


@dataclass(frozen=True)
class NormalizedField:
    key: str
    raw: str
    normalized: dict[str, object]
    confidence: Decimal
    page: int | None
    bounding_box: dict[str, float] | None


@dataclass(frozen=True)
class NormalizedLine:
    position: int
    description: str
    quantity: Decimal | None
    unit_price: Decimal | None
    amount: Decimal | None
    confidence: Decimal


@dataclass(frozen=True)
class Extraction:
    fields: list[NormalizedField]
    lines: list[NormalizedLine]
    page_count: int | None
    currency: str

    def by_key(self) -> dict[str, NormalizedField]:
        return {item.key: item for item in self.fields}


def normalize_analysis(payload: ExpenseAnalysis) -> Extraction:
    fields: dict[str, NormalizedField] = {}
    currency_hint = ""
    for document in payload.expense_documents:
        for summary in document.summary_fields:
            spec = _spec_for(summary)
            if spec is None or summary.value_detection is None:
                continue
            raw = summary.value_detection.text
            if spec.key == "currency":
                currency_hint = raw
            if spec.key in fields and fields[spec.key].confidence >= _confidence(summary):
                continue
            fields[spec.key] = NormalizedField(
                key=spec.key,
                raw=raw,
                normalized=_normalize(spec.normalizer, raw),
                confidence=_confidence(summary),
                page=summary.page_number,
                bounding_box=_box(summary),
            )
    currency = _currency(currency_hint, fields.get("total"))
    lines: list[NormalizedLine] = []
    position = 1
    for document in payload.expense_documents:
        for group in document.line_item_groups:
            for line in group.line_items:
                lines.append(_line(position, line))
                position += 1
    pages = payload.document_metadata.pages if payload.document_metadata else None
    return Extraction(fields=list(fields.values()), lines=lines, page_count=pages, currency=currency)


def normalize_human(key: str, raw: str) -> dict[str, object]:
    spec = next((item for item in SUMMARY_FIELDS.values() if item.key == key), None)
    if spec is None:
        return {"text": raw.strip()}
    return _normalize(spec.normalizer, raw)


def quantize_money(value: Decimal) -> Decimal:
    return value.quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def confidence_unit(value: float) -> Decimal:
    raw = Decimal(str(value))
    if raw > 1:
        raw = raw / Decimal("100")
    if raw < 0:
        raw = Decimal("0")
    if raw > 1:
        raw = Decimal("1")
    return raw.quantize(FOURPLACES)


def normalize_name(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", " ", value.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def normalize_tax_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", value).upper()


def money_amount(field: NormalizedField | None) -> Decimal | None:
    if field is None:
        return None
    amount = field.normalized.get("amount")
    if isinstance(amount, str):
        return Decimal(amount)
    return None


def date_value(field: NormalizedField | None) -> date | None:
    if field is None:
        return None
    raw = field.normalized.get("date")
    if isinstance(raw, str) and raw:
        return date.fromisoformat(raw)
    return None


def text_value(field: NormalizedField | None) -> str:
    if field is None:
        return ""
    raw = field.normalized.get("text")
    if isinstance(raw, str):
        return raw
    return field.raw


def _spec_for(summary: SummaryField) -> FieldSpec | None:
    if summary.type is None:
        return None
    return SUMMARY_FIELDS.get(summary.type.text)


def _confidence(summary: SummaryField) -> Decimal:
    if summary.value_detection is None:
        return Decimal("0")
    return confidence_unit(summary.value_detection.confidence)


def _box(summary: SummaryField) -> dict[str, float] | None:
    detection = summary.value_detection
    if detection is None or detection.geometry is None or detection.geometry.bounding_box is None:
        return None
    box = detection.geometry.bounding_box
    return {"width": box.width, "height": box.height, "left": box.left, "top": box.top}


def _normalize(kind: NormalizerName, raw: str) -> dict[str, object]:
    if kind == "date":
        parsed = _parse_date(raw)
        return {"date": parsed.isoformat() if parsed else None, "text": raw.strip()}
    if kind == "money":
        parsed = _parse_money(raw)
        return {"amount": str(parsed) if parsed is not None else None, "text": raw.strip()}
    if kind == "tax_id":
        return {"tax_id": normalize_tax_id(raw), "text": raw.strip()}
    return {"text": raw.strip()}


def _parse_date(value: str) -> date | None:
    text = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _parse_money(value: str) -> Decimal | None:
    text = value.strip()
    negative = text.startswith("(") and text.endswith(")")
    cleaned = re.sub(r"[^0-9.\-]", "", text)
    if cleaned.count(".") > 1 or cleaned in {"", "-", ".", "-."}:
        return None
    try:
        amount = Decimal(cleaned)
    except InvalidOperation:
        return None
    if negative:
        amount = -amount
    return quantize_money(amount)


def _currency(hint: str, total: NormalizedField | None) -> str:
    candidate = hint.strip().upper()
    if re.fullmatch(r"[A-Z]{3}", candidate):
        return candidate
    blob = f"{hint} {total.raw if total else ''}"
    for symbol, code in _CURRENCY_SYMBOLS.items():
        if symbol in blob:
            return code
    return "USD"


def _line(position: int, line: ExpenseLine) -> NormalizedLine:
    values: dict[str, tuple[str, float]] = {}
    for item in line.fields:
        if item.type is None or item.value_detection is None:
            continue
        slot = LINE_FIELDS.get(item.type.text)
        if slot is None:
            continue
        values[slot] = (item.value_detection.text, item.value_detection.confidence)
    confidences = [confidence_unit(score) for _text, score in values.values()] or [Decimal("0")]
    quantity = _parse_money(values["quantity"][0]) if "quantity" in values else None
    unit_price = _parse_money(values["unit_price"][0]) if "unit_price" in values else None
    amount = _parse_money(values["amount"][0]) if "amount" in values else None
    if quantity is not None:
        quantity = quantity.quantize(FOURPLACES)
    if unit_price is not None:
        unit_price = unit_price.quantize(FOURPLACES)
    return NormalizedLine(
        position=position,
        description=values.get("description", ("", 0))[0],
        quantity=quantity,
        unit_price=unit_price,
        amount=amount,
        confidence=min(confidences),
    )
