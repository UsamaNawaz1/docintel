"""Throttles keyed by the active company, not by user or IP.

A member and an admin in the same tenant share the upload budget. That matches
how Textract and export load actually scale.
"""

from __future__ import annotations

from rest_framework.request import Request
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView


class CompanyRateThrottle(SimpleRateThrottle):
    scope = "company"

    def get_cache_key(self, request: Request, view: APIView) -> str | None:
        company = getattr(request, "company", None)
        if company is None:
            return None
        return self.cache_format % {"scope": self.scope, "ident": str(company.id)}


class DocumentUploadThrottle(CompanyRateThrottle):
    scope = "document_upload"


class DocumentExportThrottle(CompanyRateThrottle):
    scope = "document_export"


class DocumentReprocessThrottle(CompanyRateThrottle):
    scope = "document_reprocess"
