"""Generic CSV import jobs.

The file lives in object storage. Preview and commit stream it; they do not
keep a second copy in Postgres. Row errors are the only per-row persistence,
and they are replaced each time preview runs.
"""

from __future__ import annotations

from django.db import models

from docintel.apps.core.models import TenantScopedModel, User


class ImportJob(TenantScopedModel):
    class Status(models.TextChoices):
        UPLOADED = "uploaded", "Uploaded"
        PREVIEWED = "previewed", "Previewed"
        COMMITTING = "committing", "Committing"
        COMMITTED = "committed", "Committed"
        FAILED = "failed", "Failed"

    importer_slug = models.CharField(max_length=80)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.UPLOADED)
    s3_key = models.CharField(max_length=500)
    original_filename = models.CharField(max_length=255)
    row_count = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="import_jobs")
    failure_reason = models.CharField(max_length=80, blank=True)

    class Meta:
        abstract = False
        base_manager_name = "unscoped"
        default_manager_name = "objects"
        db_table = "imports_job"
        indexes = [
            models.Index(fields=["company", "status", "created_at"], name="import_job_status"),
        ]


class ImportRowError(TenantScopedModel):
    job = models.ForeignKey(ImportJob, on_delete=models.CASCADE, related_name="errors")
    row_number = models.PositiveIntegerField()
    field = models.CharField(max_length=80, blank=True)
    message = models.TextField()

    class Meta:
        abstract = False
        base_manager_name = "unscoped"
        default_manager_name = "objects"
        db_table = "imports_row_error"
        indexes = [
            models.Index(fields=["job", "row_number"], name="import_error_row"),
        ]
