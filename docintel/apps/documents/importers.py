"""Vendor master import. Natural key is (company, normalized name)."""

from __future__ import annotations

from collections.abc import Sequence

from django.utils import timezone
from pydantic import BaseModel, ConfigDict, Field, field_validator

from docintel.apps.core.ids import uuid7
from docintel.apps.core.models import Company
from docintel.apps.documents.models import Vendor
from docintel.apps.documents.normalization import normalize_name, normalize_tax_id
from docintel.apps.imports.registry import BaseImporter, register


class VendorRow(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=255)
    tax_id: str = ""
    aliases: str = ""
    default_gl_code: str = ""

    @field_validator("name")
    @classmethod
    def name_present(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name is required")
        return value.strip()

    def alias_list(self) -> list[str]:
        return [normalize_name(part) for part in self.aliases.split("|") if part.strip()]


@register
class VendorImporter(BaseImporter):
    slug = "vendors"
    row_schema = VendorRow

    @classmethod
    def template_headers(cls) -> list[str]:
        return ["name", "tax_id", "aliases", "default_gl_code"]

    def commit_chunk(self, rows: Sequence[BaseModel], *, company: Company) -> int:
        now = timezone.now()
        vendors: list[Vendor] = []
        seen: set[str] = set()
        for row in rows:
            if not isinstance(row, VendorRow):
                continue
            normalized = normalize_name(row.name)
            if normalized in seen:
                continue
            seen.add(normalized)
            vendors.append(
                Vendor(
                    id=uuid7(),
                    company=company,
                    name=row.name,
                    normalized_name=normalized,
                    tax_id=normalize_tax_id(row.tax_id),
                    aliases=row.alias_list(),
                    default_gl_code=row.default_gl_code[:40],
                    created_at=now,
                    updated_at=now,
                )
            )
        if not vendors:
            return 0
        Vendor.unscoped.bulk_create(
            vendors,
            update_conflicts=True,
            unique_fields=["company", "normalized_name"],
            update_fields=["name", "tax_id", "aliases", "default_gl_code", "updated_at"],
        )
        return len(vendors)
