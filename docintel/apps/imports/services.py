"""Upload, preview, and commit.

Commit re-reads the object and upserts in chunks inside their own
transactions. A crashed commit can be run again: ``bulk_create`` updates the
natural key instead of inserting a second row, and a job already in
``committed`` is treated as success.
"""

from __future__ import annotations

from collections.abc import Iterator
from uuid import UUID

import structlog
from django.db import transaction
from pydantic import ValidationError

from docintel.apps.core.exceptions import DomainError, NotFound
from docintel.apps.core.models import Company, User
from docintel.apps.imports.csvutil import iter_records, read_headers, template_csv
from docintel.apps.imports.models import ImportJob, ImportRowError
from docintel.apps.imports.registry import BaseImporter, RowError, get_importer
from docintel.config.settings.tuning import get_tuning

logger = structlog.get_logger(__name__)


def template_bytes(slug: str) -> tuple[str, bytes]:
    importer = get_importer(slug)
    return importer.slug, template_csv(importer.template_headers())


def create_job(
    *,
    company: Company,
    user: User,
    slug: str,
    filename: str,
    body: bytes,
) -> ImportJob:
    importer = get_importer(slug)
    from docintel.apps.core.storage import get_storage, tenant_prefix

    key = f"{tenant_prefix(company.id)}/imports/{importer.slug}/{filename}"
    get_storage().put_bytes(bucket=_bucket(), key=key, body=body, content_type="text/csv")
    return ImportJob.objects.for_company(company).create(
        company=company,
        importer_slug=importer.slug,
        s3_key=key,
        original_filename=filename,
        created_by=user,
        status=ImportJob.Status.UPLOADED,
    )


def preview_job(
    *, company: Company, job_id: UUID
) -> tuple[ImportJob, list[dict[str, object]], list[RowError]]:
    tuning = get_tuning()
    with transaction.atomic():
        job = _lock(company, job_id)
        if job.status == ImportJob.Status.COMMITTING:
            raise DomainError("Import is already committing.", code="import_busy", status_code=409)
        importer = get_importer(job.importer_slug)
        ImportRowError.objects.for_company(company).filter(job=job).delete()
        preview_rows: list[dict[str, object]] = []
        errors: list[RowError] = []
        row_count = 0
        try:
            _require_headers(importer, read_headers(_iter_file(job.s3_key)))
            for line_number, record in iter_records(_iter_file(job.s3_key)):
                row_count += 1
                parsed, error = _parse(importer, line_number, record)
                if error is not None:
                    errors.append(error)
                    continue
                if parsed is not None and len(preview_rows) < tuning.import_preview_rows:
                    preview_rows.append(parsed.model_dump(mode="json"))
        except ValueError as exc:
            job.status = ImportJob.Status.FAILED
            job.failure_reason = "invalid_csv"
            job.row_count = 0
            job.error_count = 1
            job.save(update_fields=["status", "failure_reason", "row_count", "error_count", "updated_at"])
            errors = [RowError(row_number=1, message=str(exc))]
            _store_errors(job, errors)
            return job, [], errors
        _store_errors(job, errors)
        job.row_count = row_count
        job.error_count = len(errors)
        job.status = ImportJob.Status.PREVIEWED
        job.failure_reason = ""
        job.save(update_fields=["row_count", "error_count", "status", "failure_reason", "updated_at"])
    return job, preview_rows, errors[: tuning.import_error_response_limit]


def start_commit(*, company: Company, job_id: UUID) -> ImportJob:
    with transaction.atomic():
        job = _lock(company, job_id)
        if job.status == ImportJob.Status.COMMITTED:
            return job
        if job.status == ImportJob.Status.COMMITTING:
            return job
        if job.status != ImportJob.Status.PREVIEWED:
            raise DomainError("Preview the file before committing.", code="import_not_previewed")
        if job.error_count:
            raise DomainError(
                "Fix row errors before committing.",
                code="import_has_errors",
                details={"error_count": job.error_count},
            )
        job.status = ImportJob.Status.COMMITTING
        job.save(update_fields=["status", "updated_at"])
        transaction.on_commit(lambda jid=job.id: _enqueue(jid))
    return job


def run_commit(job_id: UUID) -> None:
    """Execute a commit. Safe to call again after a partial chunk write."""
    tuning = get_tuning()
    job = ImportJob.unscoped.select_related("company").get(id=job_id)
    if job.status == ImportJob.Status.COMMITTED:
        return
    structlog.contextvars.bind_contextvars(company_id=str(job.company_id), import_job_id=str(job.id))
    importer = get_importer(job.importer_slug)
    chunk: list[object] = []
    try:
        for _line_number, record in iter_records(_iter_file(job.s3_key)):
            parsed = importer.parse_row(record)
            chunk.append(parsed)
            if len(chunk) >= tuning.import_chunk_size:
                _write_chunk(importer, job.company, chunk)
                chunk = []
        if chunk:
            _write_chunk(importer, job.company, chunk)
    except (ValueError, ValidationError) as exc:
        _fail(job.id, "invalid_csv" if isinstance(exc, ValueError) else "invalid_row")
        return
    with transaction.atomic():
        locked = ImportJob.unscoped.select_for_update().get(id=job.id)
        locked.status = ImportJob.Status.COMMITTED
        locked.save(update_fields=["status", "updated_at"])
    logger.info("import_committed", job_id=str(job.id), rows=job.row_count)


def _write_chunk(importer: BaseImporter, company: Company, chunk: list[object]) -> None:
    from pydantic import BaseModel

    rows = [row for row in chunk if isinstance(row, BaseModel)]
    with transaction.atomic():
        importer.commit_chunk(rows, company=company)


def _parse(
    importer: BaseImporter,
    line_number: int,
    record: dict[str, str],
) -> tuple[object | None, RowError | None]:
    try:
        return importer.parse_row(record), None
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = first.get("loc") or ()
        field = str(loc[0]) if loc else ""
        return None, RowError(row_number=line_number, field=field, message=first["msg"])


def _require_headers(importer: BaseImporter, actual: list[str]) -> None:
    expected = importer.template_headers()
    if [header.lower() for header in actual] != [header.lower() for header in expected]:
        raise ValueError(f"CSV headers must be {expected}. Received {actual}.")


def _store_errors(job: ImportJob, errors: list[RowError]) -> None:
    rows = [
        ImportRowError(
            company_id=job.company_id,
            job=job,
            row_number=error.row_number,
            field=error.field,
            message=error.message,
        )
        for error in errors
    ]
    if rows:
        ImportRowError.unscoped.bulk_create(rows, batch_size=1000)


def _lock(company: Company, job_id: UUID) -> ImportJob:
    try:
        return ImportJob.objects.for_company(company).select_for_update().get(id=job_id)
    except ImportJob.DoesNotExist as exc:
        raise NotFound("Import job not found.") from exc


def _iter_file(key: str) -> Iterator[bytes]:
    from docintel.apps.core.storage import get_storage

    yield from get_storage().iter_chunks(bucket=_bucket(), key=key, chunk_size=64 * 1024)


def _bucket() -> str:
    from django.conf import settings

    return str(settings.AWS_S3_BUCKET)


def _enqueue(job_id: UUID) -> None:
    from docintel.apps.imports.tasks import commit_import_job

    commit_import_job.delay(str(job_id))


def _fail(job_id: UUID, reason: str) -> None:
    with transaction.atomic():
        job = ImportJob.unscoped.select_for_update().get(id=job_id)
        job.status = ImportJob.Status.FAILED
        job.failure_reason = reason
        job.save(update_fields=["status", "failure_reason", "updated_at"])
