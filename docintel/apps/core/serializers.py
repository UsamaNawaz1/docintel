"""Shared OpenAPI error envelope serializer."""

from __future__ import annotations

from rest_framework import serializers


class ErrorBodySerializer(serializers.Serializer[dict[str, object]]):
    code = serializers.CharField()
    message = serializers.CharField()
    details = serializers.DictField()


class ErrorEnvelopeSerializer(serializers.Serializer[dict[str, object]]):
    error = ErrorBodySerializer()
