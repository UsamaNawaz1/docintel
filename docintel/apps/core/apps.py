"""Core application config."""

from __future__ import annotations

from django.apps import AppConfig
from django.conf import settings


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "docintel.apps.core"
    label = "core"

    def ready(self) -> None:
        from docintel.apps.core.logging import before_send, configure_logging

        configure_logging(json_logs=settings.JSON_LOGS, level=settings.LOG_LEVEL)
        if settings.SENTRY_DSN:
            import sentry_sdk
            from sentry_sdk.integrations.celery import CeleryIntegration
            from sentry_sdk.integrations.django import DjangoIntegration

            sentry_sdk.init(
                dsn=settings.SENTRY_DSN,
                environment=settings.SENTRY_ENVIRONMENT,
                integrations=[DjangoIntegration(), CeleryIntegration()],
                send_default_pii=False,
                before_send=before_send,
            )
