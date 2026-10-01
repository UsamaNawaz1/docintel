"""Textract adapter.

``ClientRequestToken`` is a hash of the document id, so a retry of
``StartExpenseAnalysis`` returns the original job instead of billing a second
one. Transient API errors are a dedicated exception type so the Celery task
can autoretry only those. Everything else fails the document.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator, Mapping
from typing import Protocol
from uuid import UUID

from django.conf import settings

from docintel.apps.documents.schemas import ExpenseAnalysis

_TRANSIENT_CODES = frozenset(
    {
        "ThrottlingException",
        "ProvisionedThroughputExceededException",
        "InternalServerError",
        "ServiceUnavailableException",
        "RequestTimeout",
    }
)

_TERMINAL_REASONS = {
    "UnsupportedDocumentException": "unsupported_document",
    "BadDocumentException": "bad_document",
    "DocumentTooLargeException": "document_too_large",
    "InvalidS3ObjectException": "invalid_s3_object",
    "InvalidParameterException": "invalid_parameter",
    "AccessDeniedException": "access_denied",
}


class TextractError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class TransientTextractError(TextractError):
    """Retryable. The task uses this class in ``autoretry_for``."""


class TerminalTextractError(TextractError):
    """Not retryable. The document moves to ``failed`` with ``code`` as the reason."""


class JobInProgress(Exception):
    """Textract has accepted the job and has not finished. The poller will return."""


class TextractAdapter(Protocol):
    def start_expense_analysis(
        self,
        *,
        bucket: str,
        key: str,
        client_request_token: str,
        sns_topic_arn: str,
        sns_role_arn: str,
    ) -> str: ...

    def get_expense_analysis(self, job_id: str) -> Iterator[Mapping[str, object]]: ...


def client_request_token(document_id: UUID) -> str:
    return hashlib.sha256(str(document_id).encode("utf-8")).hexdigest()[:64]


def translate_client_error(code: str, message: str) -> TextractError:
    if code in _TRANSIENT_CODES:
        return TransientTextractError(code, message)
    reason = _TERMINAL_REASONS.get(code, "textract_rejected")
    return TerminalTextractError(reason, message)


class FakeTextractAdapter:
    """Deterministic stand-in. Tests and ``seed_demo`` register a payload per token."""

    def __init__(self) -> None:
        self.jobs: dict[str, str] = {}
        self.payloads: dict[str, dict[str, object]] = {}
        self.failures: dict[str, TextractError] = {}

    def queue(self, token: str, payload: dict[str, object]) -> None:
        self.payloads[token] = payload

    def fail(self, token: str, error: TextractError) -> None:
        self.failures[token] = error

    def start_expense_analysis(
        self,
        *,
        bucket: str,
        key: str,
        client_request_token: str,
        sns_topic_arn: str,
        sns_role_arn: str,
    ) -> str:
        del bucket, key, sns_topic_arn, sns_role_arn
        error = self.failures.get(client_request_token)
        if error is not None:
            raise error
        job_id = f"fake-{client_request_token[:24]}"
        self.jobs[job_id] = client_request_token
        return job_id

    def get_expense_analysis(self, job_id: str) -> Iterator[Mapping[str, object]]:
        token = self.jobs.get(job_id, "")
        payload = self.payloads.get(token)
        if payload is None:
            payload = {
                "JobStatus": "SUCCEEDED",
                "DocumentMetadata": {"Pages": 1},
                "ExpenseDocuments": [],
            }
        yield payload


class BotoTextractAdapter:
    def __init__(self) -> None:
        import boto3
        from botocore.config import Config

        self._client = boto3.client(
            "textract",
            region_name=settings.AWS_DEFAULT_REGION,
            config=Config(
                retries={"mode": "adaptive", "max_attempts": 3},
                connect_timeout=5,
                read_timeout=30,
            ),
        )

    def start_expense_analysis(
        self,
        *,
        bucket: str,
        key: str,
        client_request_token: str,
        sns_topic_arn: str,
        sns_role_arn: str,
    ) -> str:
        kwargs: dict[str, object] = {
            "DocumentLocation": {"S3Object": {"Bucket": bucket, "Name": key}},
            "ClientRequestToken": client_request_token,
        }
        if sns_topic_arn and sns_role_arn:
            kwargs["NotificationChannel"] = {"SNSTopicArn": sns_topic_arn, "RoleArn": sns_role_arn}
        try:
            response = self._client.start_expense_analysis(**kwargs)
        except Exception as exc:
            _reraise(exc)
        return str(response["JobId"])

    def get_expense_analysis(self, job_id: str) -> Iterator[Mapping[str, object]]:
        token: str | None = None
        while True:
            kwargs: dict[str, object] = {"JobId": job_id}
            if token:
                kwargs["NextToken"] = token
            try:
                page = self._client.get_expense_analysis(**kwargs)
            except Exception as exc:
                _reraise(exc)
            status = str(page.get("JobStatus", ""))
            if status == "IN_PROGRESS":
                raise JobInProgress(job_id)
            if status == "FAILED":
                raise TerminalTextractError(
                    "textract_job_failed",
                    str(page.get("StatusMessage") or "Textract job failed"),
                )
            yield page
            next_token = page.get("NextToken")
            if not next_token:
                break
            token = str(next_token)


def merge_pages(pages: Iterator[Mapping[str, object]]) -> ExpenseAnalysis:
    documents: list[object] = []
    metadata: object = None
    for page in pages:
        if metadata is None and page.get("DocumentMetadata") is not None:
            metadata = page["DocumentMetadata"]
        batch = page.get("ExpenseDocuments")
        if isinstance(batch, list):
            documents.extend(batch)
    return ExpenseAnalysis.model_validate(
        {"DocumentMetadata": metadata, "ExpenseDocuments": documents, "JobStatus": "SUCCEEDED"}
    )


def _reraise(exc: Exception) -> None:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        error = response.get("Error", {})
        if isinstance(error, dict):
            raise translate_client_error(
                str(error.get("Code", "unknown")),
                str(error.get("Message", exc)),
            ) from exc
    raise TerminalTextractError("textract_rejected", str(exc)) from exc


_fake: FakeTextractAdapter | None = None


def get_textract() -> TextractAdapter:
    if settings.TEXTRACT_BACKEND == "fake":
        global _fake
        if _fake is None:
            _fake = FakeTextractAdapter()
        return _fake
    return BotoTextractAdapter()


def fake_textract() -> FakeTextractAdapter:
    adapter = get_textract()
    if not isinstance(adapter, FakeTextractAdapter):
        raise RuntimeError("fake textract is not active")
    return adapter
