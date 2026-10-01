"""Demo data for two tenants, including one extracted invoice and one review item.

The command calls the same services the workers call, with the fake Textract
adapter, so a reviewer can explore the API without AWS or a running worker.
"""

from __future__ import annotations

import json
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from docintel.apps.core.models import Company, Membership, User
from docintel.apps.core.storage import get_storage
from docintel.apps.documents.adapters import client_request_token, fake_textract
from docintel.apps.documents.importers import VendorImporter, VendorRow
from docintel.apps.documents.models import Document
from docintel.apps.documents.processing import begin_textract, ingest_job
from docintel.apps.documents.upload import complete_upload, create_upload
from docintel.apps.sync.models import SyncRule

_PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def _field(kind: str, text: str, confidence: float) -> dict[str, Any]:
    return {
        "Type": {"Text": kind, "Confidence": confidence},
        "ValueDetection": {"Text": text, "Confidence": confidence},
        "PageNumber": 1,
    }


def _line(kind: str, text: str, confidence: float) -> dict[str, Any]:
    return {
        "Type": {"Text": kind, "Confidence": confidence},
        "ValueDetection": {"Text": text, "Confidence": confidence},
    }


_HAPPY: dict[str, Any] = {
    "JobStatus": "SUCCEEDED",
    "DocumentMetadata": {"Pages": 2},
    "ExpenseDocuments": [
        {
            "SummaryFields": [
                _field("VENDOR_NAME", "Acme Supplies", 99),
                _field("INVOICE_RECEIPT_ID", "INV-1001", 98),
                _field("INVOICE_RECEIPT_DATE", "2026-03-01", 97),
                _field("SUBTOTAL", "100.00", 96),
                _field("TAX", "8.00", 95),
                _field("TOTAL", "$108.00", 99),
            ],
            "LineItemGroups": [
                {
                    "LineItems": [
                        {
                            "LineItemExpenseFields": [
                                _line("ITEM", "Widgets", 99),
                                _line("QUANTITY", "4", 99),
                                _line("UNIT_PRICE", "25.00", 99),
                                _line("PRICE", "100.00", 99),
                            ]
                        }
                    ]
                }
            ],
        }
    ],
}

_LOW: dict[str, Any] = {
    "JobStatus": "SUCCEEDED",
    "DocumentMetadata": {"Pages": 1},
    "ExpenseDocuments": [
        {
            "SummaryFields": [
                _field("VENDOR_NAME", "Unknown Cafe", 40),
                _field("INVOICE_RECEIPT_ID", "R-9", 50),
                _field("INVOICE_RECEIPT_DATE", "2026-04-02", 42),
                _field("TOTAL", "12.00", 40),
            ],
            "LineItemGroups": [],
        }
    ],
}


class Command(BaseCommand):
    help = "Create two demo tenants and run sample invoices through fake Textract."

    def handle(self, *args: object, **options: object) -> None:
        del args, options
        if settings.TEXTRACT_BACKEND != "fake" or settings.STORAGE_BACKEND != "memory":
            self.stdout.write(
                "Seed uses the memory storage and fake Textract backends. "
                "Set DOCINTEL_STORAGE_BACKEND=memory and DOCINTEL_TEXTRACT_BACKEND=fake."
            )
        password = settings.__dict__.get("SEED_PASSWORD") or "demo-password-not-for-production"
        from os import environ

        password = environ.get("SEED_PASSWORD", "demo-password-not-for-production")
        northwind = self._tenant("Northwind", "northwind", password)
        acme = self._tenant("Acme", "acme", password)
        VendorImporter().commit_chunk(
            [
                VendorRow(
                    name="Acme Supplies",
                    tax_id="12-3456789",
                    aliases="acme|acme supply",
                    default_gl_code="5000",
                )
            ],
            company=northwind,
        )
        self._document(northwind, "owner", "invoice-happy.pdf", _HAPPY)
        self._document(northwind, "owner", "receipt-low.pdf", _LOW)
        SyncRule.objects.for_company(northwind).get_or_create(
            event_type="document.approved",
            destination_url="https://example.com/hooks/docintel",
            defaults={
                "company": northwind,
                "signing_secret": "demo-signing-secret",
                "field_mapping": {
                    "mappings": [
                        {"source": "invoice_number", "target": "number"},
                        {"source": "total", "target": "amount"},
                    ]
                },
                "is_active": True,
            },
        )
        self.stdout.write(self.style.SUCCESS(f"Seeded northwind ({northwind.id}) and acme ({acme.id})."))
        self.stdout.write(f"Password for every demo user: {password}")

    def _tenant(self, name: str, slug: str, password: str) -> Company:
        company, _created = Company.objects.get_or_create(slug=slug, defaults={"name": name})
        for role in Membership.Role.values:
            email = f"{role}@{slug}.test"
            user, created = User.objects.get_or_create(email=email, defaults={"name": role.title()})
            if created:
                user.set_password(password)
                user.save(update_fields=["password"])
            Membership.objects.for_company(company).get_or_create(
                user=user,
                defaults={"company": company, "role": role},
            )
        return company

    def _document(self, company: Company, role: str, filename: str, payload: dict[str, Any]) -> None:
        if Document.unscoped.filter(company=company, original_filename=filename).exists():
            self.stdout.write(f"{company.slug} {filename} already seeded")
            return
        user = User.objects.get(email=f"{role}@{company.slug}.test")
        session = create_upload(
            company=company,
            user=user,
            filename=filename,
            content_type="application/pdf",
            size_bytes=len(_PDF),
        )
        get_storage().put_bytes(
            bucket=settings.AWS_S3_BUCKET,
            key=session.document.s3_key,
            body=_PDF,
            content_type="application/pdf",
        )
        token = client_request_token(session.document.id)
        fake_textract().queue(token, payload)
        with transaction.atomic():
            complete_upload(company=company, user=user, document_id=session.document.id)
        begin_textract(session.document.id)
        ingest_job(session.document.id)
        self.stdout.write(f"{company.slug} {filename} -> {session.document.id}")
        self.stdout.write(json.dumps({"token": token[:12]}))
