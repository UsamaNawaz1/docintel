"""Document API. Views validate input and call a service; they do not branch on status."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from uuid import UUID

from django.conf import settings
from django.http import StreamingHttpResponse
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from docintel.apps.core.exceptions import DomainError
from docintel.apps.core.models import TOOL_DOCUMENTS
from docintel.apps.core.pagination import CreatedAtAscCursorPagination, CreatedAtDescCursorPagination
from docintel.apps.core.permissions import HasToolPermission
from docintel.apps.core.serializers import ErrorEnvelopeSerializer
from docintel.apps.core.storage import assert_tenant_key, get_storage
from docintel.apps.core.throttling import (
    DocumentExportThrottle,
    DocumentReprocessThrottle,
    DocumentUploadThrottle,
)
from docintel.apps.documents.filters import DocumentFilter
from docintel.apps.documents.models import Document, ExtractedField, LineItem
from docintel.apps.documents.review import (
    approve_document,
    correct_fields,
    reject_document,
    reprocess_document,
)
from docintel.apps.documents.selectors import approved_export, document_list, get_document, review_queue
from docintel.apps.documents.upload import complete_upload, create_upload
from docintel.apps.imports.csvutil import csv_safe
from docintel.config.settings.tuning import get_tuning


class FieldSerializer(serializers.ModelSerializer[ExtractedField]):
    class Meta:
        model = ExtractedField
        fields = (
            "key",
            "value",
            "normalized_value",
            "confidence",
            "page",
            "bounding_box",
            "source",
            "corrected_at",
        )


class LineItemSerializer(serializers.ModelSerializer[LineItem]):
    class Meta:
        model = LineItem
        fields = ("position", "description", "quantity", "unit_price", "amount", "confidence")


class DocumentSerializer(serializers.ModelSerializer[Document]):
    class Meta:
        model = Document
        fields = (
            "id",
            "status",
            "version",
            "original_filename",
            "content_type",
            "size_bytes",
            "page_count",
            "invoice_number",
            "invoice_date",
            "currency",
            "subtotal",
            "tax",
            "total",
            "vendor",
            "vendor_match_score",
            "review_reasons",
            "failure_reason",
            "processed_at",
            "created_at",
        )


class DocumentDetailSerializer(DocumentSerializer):
    fields = FieldSerializer(many=True)
    line_items = LineItemSerializer(many=True)
    download_url = serializers.SerializerMethodField()

    class Meta(DocumentSerializer.Meta):
        fields = (*DocumentSerializer.Meta.fields, "fields", "line_items", "download_url")

    def get_download_url(self, document: Document) -> str:
        assert_tenant_key(document.company_id, document.s3_key)
        return get_storage().presigned_get(
            bucket=settings.AWS_S3_BUCKET,
            key=document.s3_key,
            expires_in=get_tuning().download_url_ttl_seconds,
        )


class UploadRequestSerializer(serializers.Serializer[dict[str, object]]):
    filename = serializers.CharField(max_length=255)
    content_type = serializers.CharField(max_length=120)
    size_bytes = serializers.IntegerField(min_value=1)


class UploadResponseSerializer(serializers.Serializer[dict[str, object]]):
    document = DocumentSerializer()
    url = serializers.URLField()
    fields = serializers.DictField(child=serializers.CharField())


class FieldCorrectionSerializer(serializers.Serializer[dict[str, str]]):
    key = serializers.CharField(max_length=80)
    value = serializers.CharField(allow_blank=True)


class FieldCorrectionRequestSerializer(serializers.Serializer[dict[str, object]]):
    fields = FieldCorrectionSerializer(many=True)


class RejectSerializer(serializers.Serializer[dict[str, str]]):
    reason = serializers.CharField(max_length=200, required=False, allow_blank=True)


class DocumentToolView(APIView):
    permission_classes = [IsAuthenticated, HasToolPermission]
    tool_slug = TOOL_DOCUMENTS
    required_action = "view"


def _version(request: Request) -> int:
    header = request.headers.get("If-Match", "").strip().strip('"')
    if not header:
        raise DomainError(
            "If-Match header is required.",
            code="precondition_required",
            status_code=428,
        )
    try:
        return int(header)
    except ValueError as exc:
        raise DomainError(
            "If-Match must be the document version.", code="precondition_failed", status_code=412
        ) from exc


class DocumentListView(DocumentToolView):
    filter_backends = [DjangoFilterBackend]
    filterset_class = DocumentFilter

    @extend_schema(
        parameters=[
            OpenApiParameter("status", str),
            OpenApiParameter("vendor", str),
            OpenApiParameter("search", str),
            OpenApiParameter("invoice_date_after", str),
            OpenApiParameter("invoice_date_before", str),
            OpenApiParameter("total_min", str),
            OpenApiParameter("total_max", str),
        ],
        responses={200: DocumentSerializer(many=True), 403: ErrorEnvelopeSerializer},
    )
    def get(self, request: Request) -> Response:
        queryset = document_list(request.company)  # type: ignore[attr-defined]
        queryset = DocumentFilter(request.query_params, queryset=queryset).qs
        paginator = CreatedAtDescCursorPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response(DocumentSerializer(page, many=True).data)


class DocumentDetailView(DocumentToolView):
    @extend_schema(responses={200: DocumentDetailSerializer, 404: ErrorEnvelopeSerializer})
    def get(self, request: Request, document_id: UUID) -> Response:
        document = get_document(request.company, document_id)  # type: ignore[attr-defined]
        return Response(DocumentDetailSerializer(document).data)


class DocumentUploadView(DocumentToolView):
    required_action = "create"
    throttle_classes = [DocumentUploadThrottle]

    @extend_schema(request=UploadRequestSerializer, responses={201: UploadResponseSerializer})
    def post(self, request: Request) -> Response:
        serializer = UploadRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session = create_upload(
            company=request.company,  # type: ignore[attr-defined]
            user=request.user,  # type: ignore[arg-type]
            filename=str(serializer.validated_data["filename"]),
            content_type=str(serializer.validated_data["content_type"]),
            size_bytes=int(serializer.validated_data["size_bytes"]),
        )
        return Response(
            {
                "document": DocumentSerializer(session.document).data,
                "url": session.presigned.url,
                "fields": session.presigned.fields,
            },
            status=status.HTTP_201_CREATED,
        )


class DocumentCompleteView(DocumentToolView):
    required_action = "create"

    @extend_schema(
        responses={200: DocumentSerializer, 404: ErrorEnvelopeSerializer, 409: ErrorEnvelopeSerializer}
    )
    def post(self, request: Request, document_id: UUID) -> Response:
        document = complete_upload(
            company=request.company,  # type: ignore[attr-defined]
            user=request.user,  # type: ignore[arg-type]
            document_id=document_id,
        )
        return Response(DocumentSerializer(document).data)


class ReviewQueueView(DocumentToolView):
    required_action = "review"

    @extend_schema(responses={200: DocumentSerializer(many=True)})
    def get(self, request: Request) -> Response:
        paginator = CreatedAtAscCursorPagination()
        page = paginator.paginate_queryset(
            review_queue(request.company),  # type: ignore[attr-defined]
            request,
            view=self,
        )
        return paginator.get_paginated_response(DocumentSerializer(page, many=True).data)


class DocumentFieldsView(DocumentToolView):
    required_action = "review"

    @extend_schema(
        request=FieldCorrectionRequestSerializer,
        responses={200: DocumentDetailSerializer, 412: ErrorEnvelopeSerializer},
        parameters=[OpenApiParameter("If-Match", str, OpenApiParameter.HEADER)],
    )
    def patch(self, request: Request, document_id: UUID) -> Response:
        serializer = FieldCorrectionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        corrections = [(str(item["key"]), str(item["value"])) for item in serializer.validated_data["fields"]]
        correct_fields(
            company=request.company,  # type: ignore[attr-defined]
            user=request.user,  # type: ignore[arg-type]
            document_id=document_id,
            expected_version=_version(request),
            corrections=corrections,
        )
        document = get_document(request.company, document_id)  # type: ignore[attr-defined]
        return Response(DocumentDetailSerializer(document).data)


class DocumentApproveView(DocumentToolView):
    required_action = "review"

    @extend_schema(
        responses={200: DocumentSerializer, 409: ErrorEnvelopeSerializer, 412: ErrorEnvelopeSerializer},
        parameters=[OpenApiParameter("If-Match", str, OpenApiParameter.HEADER)],
    )
    def post(self, request: Request, document_id: UUID) -> Response:
        document = approve_document(
            company=request.company,  # type: ignore[attr-defined]
            user=request.user,  # type: ignore[arg-type]
            document_id=document_id,
            expected_version=_version(request),
        )
        return Response(DocumentSerializer(document).data)


class DocumentRejectView(DocumentToolView):
    required_action = "review"

    @extend_schema(
        request=RejectSerializer,
        responses={200: DocumentSerializer, 412: ErrorEnvelopeSerializer},
        parameters=[OpenApiParameter("If-Match", str, OpenApiParameter.HEADER)],
    )
    def post(self, request: Request, document_id: UUID) -> Response:
        serializer = RejectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        document = reject_document(
            company=request.company,  # type: ignore[attr-defined]
            user=request.user,  # type: ignore[arg-type]
            document_id=document_id,
            expected_version=_version(request),
            reason=str(serializer.validated_data.get("reason", "")),
        )
        return Response(DocumentSerializer(document).data)


class DocumentReprocessView(DocumentToolView):
    required_action = "admin"
    throttle_classes = [DocumentReprocessThrottle]

    @extend_schema(responses={202: DocumentSerializer, 409: ErrorEnvelopeSerializer})
    def post(self, request: Request, document_id: UUID) -> Response:
        document = reprocess_document(
            company=request.company,  # type: ignore[attr-defined]
            user=request.user,  # type: ignore[arg-type]
            document_id=document_id,
        )
        return Response(DocumentSerializer(document).data, status=status.HTTP_202_ACCEPTED)


class DocumentExportView(DocumentToolView):
    required_action = "export"
    throttle_classes = [DocumentExportThrottle]

    @extend_schema(responses={(200, "text/csv"): OpenApiResponse(description="Approved documents")})
    def get(self, request: Request) -> StreamingHttpResponse:
        response = StreamingHttpResponse(
            _export_rows(request.company),  # type: ignore[attr-defined]
            content_type="text/csv",
        )
        response["Content-Disposition"] = 'attachment; filename="documents.csv"'
        return response


class TextractWebhookView(APIView):
    authentication_classes: list[object] = []
    permission_classes = [AllowAny]

    @extend_schema(exclude=True)
    def post(self, request: Request) -> Response:
        import json

        from docintel.apps.documents.webhooks import handle_sns

        try:
            payload = json.loads(request.body)
        except json.JSONDecodeError as exc:
            raise DomainError("SNS body is not JSON.", code="invalid_sns_message") from exc
        if not isinstance(payload, dict):
            raise DomainError("SNS body is not an object.", code="invalid_sns_message")
        handle_sns(payload)
        return Response({"ok": True})


_EXPORT_HEADER = [
    "id",
    "invoice_number",
    "vendor",
    "invoice_date",
    "currency",
    "subtotal",
    "tax",
    "total",
    "status",
]


def _export_rows(company: object) -> Iterator[str]:
    from docintel.apps.core.models import Company

    if not isinstance(company, Company):
        return
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(_EXPORT_HEADER)
    yield buffer.getvalue()
    buffer.seek(0)
    buffer.truncate(0)
    queryset = approved_export(company).iterator(chunk_size=500)
    for document in queryset:
        vendor_name = document.vendor.name if document.vendor_id and document.vendor else ""
        writer.writerow(
            [
                csv_safe(document.id),
                csv_safe(document.invoice_number),
                csv_safe(vendor_name),
                csv_safe(document.invoice_date or ""),
                csv_safe(document.currency),
                csv_safe(document.subtotal if document.subtotal is not None else ""),
                csv_safe(document.tax if document.tax is not None else ""),
                csv_safe(document.total if document.total is not None else ""),
                csv_safe(document.status),
            ]
        )
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)
