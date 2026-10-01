"""Object storage.

Document bytes never pass through the upload view: that path returns a
presigned POST. Import files and Textract audit blobs do go through the API,
but only as a stream (``iter_chunks`` / ``put_bytes`` of an already-buffered
small CSV). Keys are always tenant-prefixed and checked again before a
presigned GET is minted.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from django.conf import settings

from docintel.apps.core.exceptions import DomainError, NotFound


@dataclass(frozen=True)
class PresignedPost:
    url: str
    fields: dict[str, str]


@dataclass(frozen=True)
class ObjectHead:
    content_length: int
    content_type: str
    server_side_encryption: str


class Storage(Protocol):
    def create_presigned_post(
        self,
        *,
        bucket: str,
        key: str,
        content_type: str,
        max_bytes: int,
        expires_in: int,
        kms_key_id: str,
    ) -> PresignedPost: ...

    def head(self, *, bucket: str, key: str) -> ObjectHead: ...

    def get_prefix(self, *, bucket: str, key: str, length: int) -> bytes: ...

    def iter_chunks(self, *, bucket: str, key: str, chunk_size: int) -> Iterator[bytes]: ...

    def put_bytes(self, *, bucket: str, key: str, body: bytes, content_type: str) -> None: ...

    def presigned_get(self, *, bucket: str, key: str, expires_in: int) -> str: ...


def tenant_prefix(company_id: UUID) -> str:
    return f"tenants/{company_id}"


def assert_tenant_key(company_id: UUID, key: str) -> None:
    prefix = tenant_prefix(company_id) + "/"
    if not key.startswith(prefix) or ".." in key.split("/"):
        raise NotFound("Document not found.")


class MemoryStorage:
    """Process-local store for tests, seed data, and laptop demos."""

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.types: dict[tuple[str, str], str] = {}

    def create_presigned_post(
        self,
        *,
        bucket: str,
        key: str,
        content_type: str,
        max_bytes: int,
        expires_in: int,
        kms_key_id: str,
    ) -> PresignedPost:
        del max_bytes, expires_in
        encryption = "aws:kms" if kms_key_id else "AES256"
        return PresignedPost(
            url=f"memory://{bucket}/{key}",
            fields={
                "key": key,
                "Content-Type": content_type,
                "x-amz-server-side-encryption": encryption,
            },
        )

    def head(self, *, bucket: str, key: str) -> ObjectHead:
        body = self._require(bucket, key)
        return ObjectHead(
            content_length=len(body),
            content_type=self.types.get((bucket, key), "application/octet-stream"),
            server_side_encryption="AES256",
        )

    def get_prefix(self, *, bucket: str, key: str, length: int) -> bytes:
        return self._require(bucket, key)[:length]

    def iter_chunks(self, *, bucket: str, key: str, chunk_size: int) -> Iterator[bytes]:
        body = self._require(bucket, key)
        for offset in range(0, len(body), chunk_size):
            yield body[offset : offset + chunk_size]

    def put_bytes(self, *, bucket: str, key: str, body: bytes, content_type: str) -> None:
        self.objects[(bucket, key)] = body
        self.types[(bucket, key)] = content_type

    def presigned_get(self, *, bucket: str, key: str, expires_in: int) -> str:
        self._require(bucket, key)
        return f"memory://{bucket}/{key}?ttl={expires_in}"

    def _require(self, bucket: str, key: str) -> bytes:
        try:
            return self.objects[(bucket, key)]
        except KeyError as exc:
            raise DomainError("Uploaded object was not found.", code="upload_incomplete") from exc


class S3Storage:
    def __init__(self) -> None:
        import boto3
        from botocore.config import Config

        kwargs: dict[str, object] = {
            "region_name": settings.AWS_DEFAULT_REGION,
            "config": Config(
                retries={"mode": "adaptive", "max_attempts": 3},
                connect_timeout=3,
                read_timeout=20,
                signature_version="s3v4",
            ),
        }
        if settings.AWS_S3_ENDPOINT_URL:
            kwargs["endpoint_url"] = settings.AWS_S3_ENDPOINT_URL
        self._client = boto3.client("s3", **kwargs)

    def create_presigned_post(
        self,
        *,
        bucket: str,
        key: str,
        content_type: str,
        max_bytes: int,
        expires_in: int,
        kms_key_id: str,
    ) -> PresignedPost:
        encryption = "aws:kms" if kms_key_id else "AES256"
        fields = {
            "Content-Type": content_type,
            "x-amz-server-side-encryption": encryption,
        }
        conditions: list[object] = [
            {"key": key},
            {"Content-Type": content_type},
            {"x-amz-server-side-encryption": encryption},
            ["content-length-range", 1, max_bytes],
        ]
        if kms_key_id:
            fields["x-amz-server-side-encryption-aws-kms-key-id"] = kms_key_id
            conditions.append({"x-amz-server-side-encryption-aws-kms-key-id": kms_key_id})
        signed = self._client.generate_presigned_post(
            Bucket=bucket,
            Key=key,
            Fields=fields,
            Conditions=conditions,
            ExpiresIn=expires_in,
        )
        return PresignedPost(
            url=str(signed["url"]), fields={str(k): str(v) for k, v in signed["fields"].items()}
        )

    def head(self, *, bucket: str, key: str) -> ObjectHead:
        try:
            response = self._client.head_object(Bucket=bucket, Key=key)
        except Exception as exc:
            raise DomainError("Uploaded object was not found.", code="upload_incomplete") from exc
        return ObjectHead(
            content_length=int(response["ContentLength"]),
            content_type=str(response.get("ContentType") or ""),
            server_side_encryption=str(response.get("ServerSideEncryption") or ""),
        )

    def get_prefix(self, *, bucket: str, key: str, length: int) -> bytes:
        response = self._client.get_object(Bucket=bucket, Key=key, Range=f"bytes=0-{length - 1}")
        return bytes(response["Body"].read())

    def iter_chunks(self, *, bucket: str, key: str, chunk_size: int) -> Iterator[bytes]:
        response = self._client.get_object(Bucket=bucket, Key=key)
        body = response["Body"]
        while True:
            chunk = body.read(chunk_size)
            if not chunk:
                break
            yield bytes(chunk)

    def put_bytes(self, *, bucket: str, key: str, body: bytes, content_type: str) -> None:
        self._client.put_object(Bucket=bucket, Key=key, Body=body, ContentType=content_type)

    def presigned_get(self, *, bucket: str, key: str, expires_in: int) -> str:
        return str(
            self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": key},
                ExpiresIn=expires_in,
            )
        )


_memory: MemoryStorage | None = None


def get_storage() -> Storage:
    if settings.STORAGE_BACKEND == "memory":
        global _memory
        if _memory is None:
            _memory = MemoryStorage()
        return _memory
    return S3Storage()


def memory_storage() -> MemoryStorage:
    storage = get_storage()
    if not isinstance(storage, MemoryStorage):
        raise RuntimeError("memory storage is not active")
    return storage
