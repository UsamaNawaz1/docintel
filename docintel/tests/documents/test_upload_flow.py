from __future__ import annotations

import pytest
from django.conf import settings

from docintel.apps.core.exceptions import DomainError
from docintel.apps.core.storage import memory_storage
from docintel.apps.documents.adapters import TerminalTextractError, client_request_token, fake_textract
from docintel.apps.documents.models import Document
from docintel.apps.documents.processing import begin_textract, ingest_job
from docintel.apps.documents.upload import complete_upload, create_upload
from docintel.tests.factories import CompanyFactory, UserFactory

_PDF = b"%PDF-1.4\ntrailer\n%%EOF\n"


@pytest.mark.django_db
def test_complete_verifies_magic_bytes_and_is_idempotent() -> None:
    company = CompanyFactory()
    user = UserFactory()
    session = create_upload(
        company=company,
        user=user,
        filename="invoice.pdf",
        content_type="application/pdf",
        size_bytes=len(_PDF),
    )
    assert session.document.s3_key.startswith(f"tenants/{company.id}/documents/")
    memory_storage().put_bytes(
        bucket=settings.AWS_S3_BUCKET,
        key=session.document.s3_key,
        body=_PDF,
        content_type="application/pdf",
    )
    document = complete_upload(company=company, user=user, document_id=session.document.id)
    assert document.status == Document.Status.UPLOADED
    assert document.sha256
    again = complete_upload(company=company, user=user, document_id=session.document.id)
    assert again.status == Document.Status.UPLOADED
    assert again.version == document.version


@pytest.mark.django_db
def test_png_disguised_as_pdf_fails() -> None:
    company = CompanyFactory()
    user = UserFactory()
    session = create_upload(
        company=company,
        user=user,
        filename="invoice.pdf",
        content_type="application/pdf",
        size_bytes=8,
    )
    memory_storage().put_bytes(
        bucket=settings.AWS_S3_BUCKET,
        key=session.document.s3_key,
        body=b"\x89PNG\r\n\x1a\n",
        content_type="application/pdf",
    )
    with pytest.raises(DomainError) as caught:
        complete_upload(company=company, user=user, document_id=session.document.id)
    assert caught.value.code == "invalid_content"


@pytest.mark.django_db
def test_duplicate_sns_completion_is_a_no_op() -> None:
    company = CompanyFactory()
    user = UserFactory()
    session = create_upload(
        company=company,
        user=user,
        filename="invoice.pdf",
        content_type="application/pdf",
        size_bytes=len(_PDF),
    )
    memory_storage().put_bytes(
        bucket=settings.AWS_S3_BUCKET,
        key=session.document.s3_key,
        body=_PDF,
        content_type="application/pdf",
    )
    document = complete_upload(company=company, user=user, document_id=session.document.id)
    token = client_request_token(document.id)
    fake_textract().queue(
        token,
        {
            "DocumentMetadata": {"Pages": 1},
            "ExpenseDocuments": [
                {
                    "SummaryFields": [
                        {
                            "Type": {"Text": "VENDOR_NAME"},
                            "ValueDetection": {"Text": "Acme", "Confidence": 99},
                        },
                        {
                            "Type": {"Text": "INVOICE_RECEIPT_ID"},
                            "ValueDetection": {"Text": "1", "Confidence": 99},
                        },
                        {
                            "Type": {"Text": "INVOICE_RECEIPT_DATE"},
                            "ValueDetection": {"Text": "2026-01-01", "Confidence": 99},
                        },
                        {"Type": {"Text": "TOTAL"}, "ValueDetection": {"Text": "5.00", "Confidence": 99}},
                    ]
                }
            ],
        },
    )
    begin_textract(document.id)
    ingest_job(document.id)
    ingest_job(document.id)
    document.refresh_from_db()
    assert document.status == Document.Status.EXTRACTED
    assert document.fields.count() == 4


@pytest.mark.django_db
def test_terminal_textract_error_fails_the_document() -> None:
    company = CompanyFactory()
    user = UserFactory()
    session = create_upload(
        company=company,
        user=user,
        filename="bad.pdf",
        content_type="application/pdf",
        size_bytes=len(_PDF),
    )
    memory_storage().put_bytes(
        bucket=settings.AWS_S3_BUCKET,
        key=session.document.s3_key,
        body=_PDF,
        content_type="application/pdf",
    )
    document = complete_upload(company=company, user=user, document_id=session.document.id)
    fake_textract().fail(client_request_token(document.id), TerminalTextractError("bad_document", "no"))
    begin_textract(document.id)
    document.refresh_from_db()
    assert document.status == Document.Status.FAILED
    assert document.failure_reason == "bad_document"
