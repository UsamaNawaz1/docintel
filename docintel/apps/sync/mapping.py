"""Field mapping and webhook signing."""

from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Mapping
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FieldMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=120)
    target: str = Field(min_length=1, max_length=120)

    @field_validator("source", "target")
    @classmethod
    def dotted_identifier(cls, value: str) -> str:
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*", value) is None:
            raise ValueError("path must be a dotted identifier")
        return value


class FieldMappingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mappings: list[FieldMapping] = Field(default_factory=list)


def apply_mapping(payload: Mapping[str, object], config: FieldMappingConfig) -> dict[str, object]:
    return {item.target: dig(payload, item.source) for item in config.mappings}


def dig(payload: Mapping[str, object], path: str) -> object:
    current: object = payload
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def sign_body(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


class DeliveryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status_code: int
    body: str
    latency_ms: int
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.error == "" and 200 <= self.status_code < 300


class Poster(Protocol):
    def __call__(
        self,
        *,
        url: str,
        body: bytes,
        headers: Mapping[str, str],
        timeout: float,
    ) -> DeliveryResult: ...
