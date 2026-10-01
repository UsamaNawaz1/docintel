"""Textract payload models.

Field names are snake_case so they do not shadow the class used in the
annotation (Python refuses ``BoundingBox: BoundingBox | None``). Aliases keep
the PascalCase keys Textract sends.
"""

from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class BoundingBox(_Model):
    width: float = Field(default=0, alias="Width")
    height: float = Field(default=0, alias="Height")
    left: float = Field(default=0, alias="Left")
    top: float = Field(default=0, alias="Top")


class Geometry(_Model):
    bounding_box: BoundingBox | None = Field(default=None, alias="BoundingBox")


class ValueDetection(_Model):
    text: str = Field(default="", alias="Text")
    confidence: float = Field(default=0, alias="Confidence")
    geometry: Geometry | None = Field(default=None, alias="Geometry")


class TypeDetection(_Model):
    text: str = Field(default="", alias="Text")
    confidence: float = Field(default=0, alias="Confidence")


class SummaryField(_Model):
    type: TypeDetection | None = Field(default=None, alias="Type")
    value_detection: ValueDetection | None = Field(default=None, alias="ValueDetection")
    page_number: int | None = Field(default=None, alias="PageNumber")


class LineItemExpenseField(_Model):
    type: TypeDetection | None = Field(default=None, alias="Type")
    value_detection: ValueDetection | None = Field(default=None, alias="ValueDetection")


class ExpenseLine(_Model):
    fields: list[LineItemExpenseField] = Field(default_factory=list, alias="LineItemExpenseFields")


class LineItemGroup(_Model):
    line_items: list[ExpenseLine] = Field(default_factory=list, alias="LineItems")


class ExpenseDocument(_Model):
    summary_fields: list[SummaryField] = Field(default_factory=list, alias="SummaryFields")
    line_item_groups: list[LineItemGroup] = Field(default_factory=list, alias="LineItemGroups")


class DocumentMetadata(_Model):
    pages: int | None = Field(default=None, alias="Pages")


class ExpenseAnalysis(_Model):
    document_metadata: DocumentMetadata | None = Field(default=None, alias="DocumentMetadata")
    expense_documents: list[ExpenseDocument] = Field(default_factory=list, alias="ExpenseDocuments")
    job_status: str = Field(default="SUCCEEDED", alias="JobStatus")
