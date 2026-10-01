"""Thin import endpoints: validate, call the service, serialize."""

from __future__ import annotations

from uuid import UUID

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from docintel.apps.core.models import TOOL_IMPORTS
from docintel.apps.core.permissions import HasToolPermission
from docintel.apps.core.serializers import ErrorEnvelopeSerializer
from docintel.apps.imports.models import ImportJob
from docintel.apps.imports.services import create_job, preview_job, start_commit, template_bytes


class ImportJobSerializer(serializers.ModelSerializer[ImportJob]):
    class Meta:
        model = ImportJob
        fields = (
            "id",
            "importer_slug",
            "status",
            "original_filename",
            "row_count",
            "error_count",
            "failure_reason",
            "created_at",
        )


class ImportUploadSerializer(serializers.Serializer[dict[str, object]]):
    file = serializers.FileField()


class RowErrorSerializer(serializers.Serializer[dict[str, object]]):
    row_number = serializers.IntegerField()
    field = serializers.CharField()
    message = serializers.CharField()


class ImportPreviewSerializer(serializers.Serializer[dict[str, object]]):
    job = ImportJobSerializer()
    rows = serializers.ListField(child=serializers.DictField())
    errors = RowErrorSerializer(many=True)


class ImportToolView(APIView):
    permission_classes = [IsAuthenticated, HasToolPermission]
    tool_slug = TOOL_IMPORTS
    required_action = "view"
    module_name = "imports"


class ImportTemplateView(ImportToolView):
    @extend_schema(responses={(200, "text/csv"): OpenApiResponse(description="CSV template")})
    def get(self, request: Request, slug: str) -> Response:
        del request
        name, payload = template_bytes(slug)
        response = Response(payload, content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{name}-template.csv"'
        return response


class ImportUploadView(ImportToolView):
    required_action = "create"

    @extend_schema(request=ImportUploadSerializer, responses={201: ImportJobSerializer})
    def post(self, request: Request, slug: str) -> Response:
        serializer = ImportUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        upload = serializer.validated_data["file"]
        job = create_job(
            company=request.company,  # type: ignore[attr-defined]
            user=request.user,  # type: ignore[arg-type]
            slug=slug,
            filename=upload.name,
            body=upload.read(),
        )
        return Response(ImportJobSerializer(job).data, status=status.HTTP_201_CREATED)


class ImportPreviewView(ImportToolView):
    required_action = "create"

    @extend_schema(
        responses={200: ImportPreviewSerializer, 404: ErrorEnvelopeSerializer},
        examples=[],
    )
    def post(self, request: Request, job_id: UUID) -> Response:
        job, rows, errors = preview_job(company=request.company, job_id=job_id)  # type: ignore[attr-defined]
        return Response(
            {
                "job": ImportJobSerializer(job).data,
                "rows": rows,
                "errors": [error.model_dump() for error in errors],
            }
        )


class ImportCommitView(ImportToolView):
    required_action = "create"

    @extend_schema(responses={202: ImportJobSerializer, 404: ErrorEnvelopeSerializer})
    def post(self, request: Request, job_id: UUID) -> Response:
        job = start_commit(company=request.company, job_id=job_id)  # type: ignore[attr-defined]
        return Response(ImportJobSerializer(job).data, status=status.HTTP_202_ACCEPTED)
