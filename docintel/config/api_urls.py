"""HTTP routes."""

from __future__ import annotations

from django.urls import path

from docintel.apps.core.auth_views import CompanyTokenRefreshView, TokenObtainView
from docintel.apps.documents.views import (
    DocumentApproveView,
    DocumentCompleteView,
    DocumentDetailView,
    DocumentExportView,
    DocumentFieldsView,
    DocumentListView,
    DocumentRejectView,
    DocumentReprocessView,
    DocumentUploadView,
    ReviewQueueView,
    TextractWebhookView,
)
from docintel.apps.imports.views import (
    ImportCommitView,
    ImportPreviewView,
    ImportTemplateView,
    ImportUploadView,
)

urlpatterns = [
    path("auth/token/", TokenObtainView.as_view(), name="token-obtain"),
    path("auth/token/refresh/", CompanyTokenRefreshView.as_view(), name="token-refresh"),
    path("documents/", DocumentListView.as_view(), name="document-list"),
    path("documents/uploads/", DocumentUploadView.as_view(), name="document-upload"),
    path("documents/export.csv", DocumentExportView.as_view(), name="document-export"),
    path("documents/review-queue/", ReviewQueueView.as_view(), name="document-review-queue"),
    path("documents/<uuid:document_id>/", DocumentDetailView.as_view(), name="document-detail"),
    path(
        "documents/<uuid:document_id>/complete/",
        DocumentCompleteView.as_view(),
        name="document-complete",
    ),
    path(
        "documents/<uuid:document_id>/fields/",
        DocumentFieldsView.as_view(),
        name="document-fields",
    ),
    path(
        "documents/<uuid:document_id>/approve/",
        DocumentApproveView.as_view(),
        name="document-approve",
    ),
    path(
        "documents/<uuid:document_id>/reject/",
        DocumentRejectView.as_view(),
        name="document-reject",
    ),
    path(
        "documents/<uuid:document_id>/reprocess/",
        DocumentReprocessView.as_view(),
        name="document-reprocess",
    ),
    path("imports/<slug:slug>/template/", ImportTemplateView.as_view(), name="import-template"),
    path("imports/<slug:slug>/upload/", ImportUploadView.as_view(), name="import-upload"),
    path("imports/<uuid:job_id>/preview/", ImportPreviewView.as_view(), name="import-preview"),
    path("imports/<uuid:job_id>/commit/", ImportCommitView.as_view(), name="import-commit"),
    path("webhooks/textract/", TextractWebhookView.as_view(), name="textract-webhook"),
]
