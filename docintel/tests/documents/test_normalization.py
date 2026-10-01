from __future__ import annotations

from docintel.apps.documents.normalization import normalize_analysis
from docintel.apps.documents.rules import review_reasons
from docintel.apps.documents.schemas import ExpenseAnalysis
from docintel.config.settings.tuning import Tuning


def _analysis(
    fields: list[tuple[str, str, float]], lines: list[tuple[str, str, str]] | None = None
) -> ExpenseAnalysis:
    summary = [
        {
            "Type": {"Text": kind, "Confidence": confidence},
            "ValueDetection": {"Text": text, "Confidence": confidence},
            "PageNumber": 1,
        }
        for kind, text, confidence in fields
    ]
    groups = []
    if lines:
        groups.append(
            {
                "LineItems": [
                    {
                        "LineItemExpenseFields": [
                            {
                                "Type": {"Text": "ITEM"},
                                "ValueDetection": {"Text": description, "Confidence": 99},
                            },
                            {"Type": {"Text": "PRICE"}, "ValueDetection": {"Text": amount, "Confidence": 99}},
                            {"Type": {"Text": "QUANTITY"}, "ValueDetection": {"Text": qty, "Confidence": 99}},
                        ]
                    }
                    for description, qty, amount in lines
                ]
            }
        )
    return ExpenseAnalysis.model_validate(
        {
            "DocumentMetadata": {"Pages": 2},
            "ExpenseDocuments": [{"SummaryFields": summary, "LineItemGroups": groups}],
        }
    )


def test_balanced_invoice_needs_no_review() -> None:
    extraction = normalize_analysis(
        _analysis(
            [
                ("VENDOR_NAME", "Acme", 99),
                ("INVOICE_RECEIPT_ID", "INV-1", 99),
                ("INVOICE_RECEIPT_DATE", "2026-01-15", 99),
                ("SUBTOTAL", "10.00", 99),
                ("TAX", "1.00", 99),
                ("TOTAL", "$11.00", 99),
            ],
            [("Widget", "2", "10.00")],
        )
    )
    fields = extraction.by_key()
    assert fields["total"].normalized["amount"] == "11.00"
    assert fields["invoice_date"].normalized["date"] == "2026-01-15"
    assert extraction.currency == "USD"
    assert extraction.page_count == 2
    assert review_reasons(extraction, Tuning()) == []


def test_low_confidence_and_unbalanced_total_request_review() -> None:
    extraction = normalize_analysis(
        _analysis(
            [
                ("VENDOR_NAME", "Acme", 10),
                ("INVOICE_RECEIPT_ID", "INV-1", 99),
                ("INVOICE_RECEIPT_DATE", "2026-01-15", 99),
                ("SUBTOTAL", "10.00", 99),
                ("TAX", "1.00", 99),
                ("TOTAL", "99.00", 99),
            ],
            [("Widget", "1", "4.00")],
        )
    )
    reasons = review_reasons(extraction, Tuning())
    assert "low_confidence:vendor_name" in reasons
    assert "line_items_unbalanced" in reasons
    assert "total_unbalanced" in reasons


def test_missing_invoice_number_requests_review() -> None:
    extraction = normalize_analysis(
        _analysis(
            [
                ("VENDOR_NAME", "Acme", 99),
                ("INVOICE_RECEIPT_DATE", "2026-01-15", 99),
                ("TOTAL", "11.00", 99),
            ]
        )
    )
    assert "missing:invoice_number" in review_reasons(extraction, Tuning())
