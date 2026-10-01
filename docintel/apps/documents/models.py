"""Invoice documents, extracted fields, and the status machine.

Transitions are methods on the model. They check the allowed edge and bump
``version``, which is also the optimistic-concurrency token (``If-Match``).
Callers take ``select_for_update`` first so two reviewers cannot both leave
the same state. The database ``CheckConstraint`` is the backstop for anything
that bypasses the method.
"""

from __future__ import annotations

from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.db import models

from docintel.apps.core.exceptions import InvalidTransition
from docintel.apps.core.models import TenantScopedModel, User

MONEY = {"max_digits": 14, "decimal_places": 2}
QUANTITY = {"max_digits": 14, "decimal_places": 4}


class Vendor(TenantScopedModel):
    name = models.CharField(max_length=255)
    normalized_name = models.CharField(max_length=255)
    tax_id = models.CharField(max_length=40, blank=True)
    aliases = ArrayField(models.CharField(max_length=255), default=list, blank=True)
    default_gl_code = models.CharField(max_length=40, blank=True)

    class Meta:
        abstract = False
        base_manager_name = "unscoped"
        default_manager_name = "objects"
        db_table = "documents_vendor"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "normalized_name"],
                name="vendor_company_norm_name",
            ),
        ]
        indexes = [
            # Fuzzy vendor match. Created concurrently in migration 0002.
            GinIndex(
                fields=["normalized_name"],
                name="vendor_name_trgm",
                opclasses=["gin_trgm_ops"],
            ),
        ]

    def __str__(self) -> str:
        return self.name


class Document(TenantScopedModel):
    class Status(models.TextChoices):
        PENDING_UPLOAD = "pending_upload", "Pending upload"
        UPLOADED = "uploaded", "Uploaded"
        PROCESSING = "processing", "Processing"
        NEEDS_REVIEW = "needs_review", "Needs review"
        EXTRACTED = "extracted", "Extracted"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        FAILED = "failed", "Failed"

    uploaded_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="uploaded_documents",
    )
    s3_key = models.CharField(max_length=500)
    original_filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=120)
    size_bytes = models.PositiveBigIntegerField(default=0)
    sha256 = models.CharField(max_length=64, blank=True)
    page_count = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING_UPLOAD,
    )
    textract_job_id = models.CharField(max_length=80, blank=True)
    failure_reason = models.CharField(max_length=80, blank=True)
    vendor = models.ForeignKey(
        Vendor,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="documents",
    )
    vendor_match_score = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        null=True,
        blank=True,
    )
    processed_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=0)
    review_reasons = models.JSONField(default=list, blank=True)
    invoice_number = models.CharField(max_length=80, blank=True)
    invoice_date = models.DateField(null=True, blank=True)
    currency = models.CharField(max_length=3, blank=True)
    subtotal = models.DecimalField(null=True, blank=True, **MONEY)
    tax = models.DecimalField(null=True, blank=True, **MONEY)
    total = models.DecimalField(null=True, blank=True, **MONEY)
    raw_response_s3_key = models.CharField(max_length=500, blank=True)

    class Meta:
        abstract = False
        base_manager_name = "unscoped"
        default_manager_name = "objects"
        db_table = "documents_document"
        constraints = [
            models.CheckConstraint(
                name="document_status_valid",
                condition=models.Q(
                    status__in=[
                        "pending_upload",
                        "uploaded",
                        "processing",
                        "needs_review",
                        "extracted",
                        "approved",
                        "rejected",
                        "failed",
                    ]
                ),
            ),
            models.UniqueConstraint(
                fields=["company", "sha256"],
                condition=~models.Q(sha256=""),
                name="doc_company_sha256",
            ),
            models.UniqueConstraint(
                fields=["textract_job_id"],
                condition=~models.Q(textract_job_id=""),
                name="doc_unique_textract_job",
            ),
        ]
        indexes = [
            models.Index(fields=["company", "status", "created_at"], name="doc_co_status_created"),
            models.Index(fields=["company", "invoice_number"], name="doc_co_invoice_no"),
            models.Index(fields=["company", "total"], name="doc_co_total"),
            models.Index(fields=["company", "invoice_date"], name="doc_co_invoice_date"),
            # Poller hot path. Partial so the index stays small.
            models.Index(
                fields=["updated_at"],
                name="doc_processing_poll",
                condition=models.Q(status="processing"),
            ),
            # Review queue: oldest needs_review row per company.
            models.Index(
                fields=["company", "created_at"],
                name="doc_review_queue",
                condition=models.Q(status="needs_review"),
            ),
        ]

    # Edges the state machine allows. Anything else raises InvalidTransition.
    ALLOWED: dict[str, frozenset[str]] = {
        Status.PENDING_UPLOAD: frozenset({Status.UPLOADED, Status.FAILED}),
        Status.UPLOADED: frozenset({Status.PROCESSING, Status.FAILED}),
        Status.PROCESSING: frozenset({Status.NEEDS_REVIEW, Status.EXTRACTED, Status.FAILED}),
        Status.NEEDS_REVIEW: frozenset({Status.APPROVED, Status.REJECTED, Status.PROCESSING}),
        Status.EXTRACTED: frozenset({Status.APPROVED, Status.REJECTED, Status.PROCESSING}),
        Status.FAILED: frozenset({Status.PROCESSING}),
        Status.REJECTED: frozenset({Status.PROCESSING}),
        Status.APPROVED: frozenset(),
    }

    def transition_to(self, new_status: str) -> str:
        """Move to ``new_status``. The caller must already hold a row lock."""
        allowed = self.ALLOWED.get(self.status, frozenset())
        if new_status not in allowed:
            raise InvalidTransition(
                f"Cannot transition document from {self.status} to {new_status}.",
                details={"from": self.status, "to": new_status},
            )
        previous = self.status
        self.status = new_status
        self.version += 1
        return previous


class ExtractedField(TenantScopedModel):
    class Source(models.TextChoices):
        TEXTRACT = "textract", "Textract"
        HUMAN = "human", "Human"

    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="fields")
    key = models.CharField(max_length=80)
    value = models.TextField(blank=True)
    normalized_value = models.JSONField(default=dict, blank=True)
    confidence = models.DecimalField(max_digits=5, decimal_places=4, default=0)
    page = models.PositiveIntegerField(null=True, blank=True)
    bounding_box = models.JSONField(null=True, blank=True)
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.TEXTRACT)
    corrected_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="field_corrections",
    )
    corrected_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = False
        base_manager_name = "unscoped"
        default_manager_name = "objects"
        db_table = "documents_extracted_field"
        constraints = [
            models.UniqueConstraint(fields=["document", "key"], name="field_document_key"),
        ]


class LineItem(TenantScopedModel):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="line_items")
    position = models.PositiveIntegerField()
    description = models.TextField(blank=True)
    quantity = models.DecimalField(null=True, blank=True, **QUANTITY)
    unit_price = models.DecimalField(null=True, blank=True, **QUANTITY)
    amount = models.DecimalField(null=True, blank=True, **MONEY)
    confidence = models.DecimalField(max_digits=5, decimal_places=4, default=0)

    class Meta:
        abstract = False
        base_manager_name = "unscoped"
        default_manager_name = "objects"
        db_table = "documents_line_item"
        constraints = [
            models.UniqueConstraint(fields=["document", "position"], name="line_document_position"),
        ]
        ordering = ["position"]


class DocumentEvent(TenantScopedModel):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="events")
    actor = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=40)
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        abstract = False
        base_manager_name = "unscoped"
        default_manager_name = "objects"
        db_table = "documents_event"
        indexes = [
            models.Index(fields=["document", "created_at"], name="doc_event_timeline"),
        ]
