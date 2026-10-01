"""Domain errors.

Services raise these. The DRF exception handler turns them into the stable
error envelope. Programmer mistakes (unscoped queries) stay as ``RuntimeError``
so they surface as 500s instead of looking like client errors.
"""

from __future__ import annotations


class DomainError(Exception):
    code = "domain_error"
    status_code = 400

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.details: dict[str, object] = dict(details or {})


class NotFound(DomainError):
    code = "not_found"
    status_code = 404


class InvalidTransition(DomainError):
    code = "invalid_transition"
    status_code = 409


class PreconditionFailed(DomainError):
    code = "precondition_failed"
    status_code = 412


class UnscopedQueryError(RuntimeError):
    """Application code evaluated a tenant model without ``for_company``."""
