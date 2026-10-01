"""CSV pipeline: BOM, encoding fallback, row errors, idempotent commit, streaming."""

from __future__ import annotations

import tracemalloc

import pytest
from django.conf import settings
from pydantic import ValidationError

from docintel.apps.core.storage import memory_storage
from docintel.apps.documents.importers import VendorImporter, VendorRow
from docintel.apps.documents.models import Vendor
from docintel.apps.imports.csvutil import iter_records, read_headers
from docintel.apps.imports.services import create_job, preview_job, run_commit, start_commit
from docintel.tests.factories import CompanyFactory, MembershipFactory, UserFactory


def _chunks(payload: bytes, size: int = 64):
    for offset in range(0, len(payload), size):
        yield payload[offset : offset + size]


def test_bom_header_is_stripped() -> None:
    payload = "\ufeffname,tax_id,aliases,default_gl_code\nAcme,1,a|b,5000\n".encode("utf-8")
    assert read_headers(_chunks(payload)) == ["name", "tax_id", "aliases", "default_gl_code"]
    rows = list(iter_records(_chunks(payload)))
    assert rows[0][0] == 2
    assert rows[0][1]["name"] == "Acme"


def test_cp1252_fallback() -> None:
    text = "name,tax_id,aliases,default_gl_code\nCaf\xe9,1,,5000\n"
    headers = read_headers(_chunks(text.encode("cp1252")))
    assert headers[0] == "name"
    rows = list(iter_records(_chunks(text.encode("cp1252"))))
    assert "Caf" in rows[0][1]["name"]


def test_streaming_50k_rows_stays_bounded() -> None:
    header = b"name,tax_id,aliases,default_gl_code\n"
    line = b"Vendor,1,alias,5000\n"

    def chunks():
        yield header
        for _ in range(50_000):
            yield line

    tracemalloc.start()
    baseline = tracemalloc.get_traced_memory()[0]
    count = 0
    for _row in iter_records(chunks()):
        count += 1
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert count == 50_000
    assert peak - baseline < 8 * 1024 * 1024


@pytest.mark.django_db
def test_preview_reports_row_numbers_and_commit_is_idempotent() -> None:
    company = CompanyFactory()
    user = UserFactory()
    MembershipFactory(company=company, user=user, role="admin")
    body = b"name,tax_id,aliases,default_gl_code\nAcme,12-3,acme|acme inc,5000\n,,,\n"
    job = create_job(company=company, user=user, slug="vendors", filename="vendors.csv", body=body)
    _job, rows, errors = preview_job(company=company, job_id=job.id)
    assert rows[0]["name"] == "Acme"
    assert errors[0].row_number == 3
    job.refresh_from_db()
    assert job.error_count == 1

    good = b"name,tax_id,aliases,default_gl_code\nAcme,12-3,acme|acme inc,5000\n"
    memory_storage().put_bytes(
        bucket=settings.AWS_S3_BUCKET,
        key=job.s3_key,
        body=good,
        content_type="text/csv",
    )
    preview_job(company=company, job_id=job.id)
    start_commit(company=company, job_id=job.id)
    run_commit(job.id)
    run_commit(job.id)
    assert Vendor.objects.for_company(company).count() == 1
    vendor = Vendor.objects.for_company(company).get()
    assert vendor.tax_id == "123"
    assert "acme inc" in vendor.aliases


def test_vendor_row_schema_rejects_blank_name() -> None:
    with pytest.raises(ValidationError):
        VendorImporter().parse_row({"name": "  ", "tax_id": "", "aliases": "", "default_gl_code": ""})
    parsed = VendorImporter().parse_row({"name": "Acme", "tax_id": "", "aliases": "", "default_gl_code": ""})
    assert isinstance(parsed, VendorRow)
