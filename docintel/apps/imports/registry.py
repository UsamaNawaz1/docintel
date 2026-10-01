"""Importer registry.

Apps register a subclass at import time (usually from ``AppConfig.ready``).
The pipeline depends on this registry, never on a concrete importer, so a new
CSV type is a new class rather than a new set of endpoints.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import ClassVar

from pydantic import BaseModel

from docintel.apps.core.models import Company


class RowError(BaseModel):
    row_number: int
    field: str = ""
    message: str


class BaseImporter(ABC):
    slug: ClassVar[str]
    row_schema: ClassVar[type[BaseModel]]

    @classmethod
    @abstractmethod
    def template_headers(cls) -> list[str]:
        """Column names, in order, for the downloadable template."""

    def parse_row(self, data: dict[str, str]) -> BaseModel:
        return self.row_schema.model_validate(data)

    @abstractmethod
    def commit_chunk(self, rows: Sequence[BaseModel], *, company: Company) -> int:
        """Upsert one chunk. Re-running the same rows must not create duplicates."""


_REGISTRY: dict[str, type[BaseImporter]] = {}


def register(importer: type[BaseImporter]) -> type[BaseImporter]:
    if not importer.slug:
        raise ValueError("importer slug is required")
    _REGISTRY[importer.slug] = importer
    return importer


def get_importer(slug: str) -> BaseImporter:
    try:
        return _REGISTRY[slug]()
    except KeyError as exc:
        from docintel.apps.core.exceptions import NotFound

        raise NotFound(f"Unknown importer '{slug}'.") from exc


def registered_slugs() -> list[str]:
    return sorted(_REGISTRY)
