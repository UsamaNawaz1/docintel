"""Shared Django settings.

Environment-specific modules (local, test, production) import this and
override secrets, debug, and backends. Nothing here should crash when a
production-only variable is absent.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from docintel.config.settings.env import csv_list, database_from_url, optional

BASE_DIR = Path(__file__).resolve().parents[3]

SECRET_KEY = optional("SECRET_KEY", "dev-only-change-me")
DEBUG = False
ALLOWED_HOSTS = csv_list("ALLOWED_HOSTS", "localhost,127.0.0.1")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "rest_framework",
    "django_filters",
    "drf_spectacular",
    "docintel.apps.core",
    "docintel.apps.sync",
    "docintel.apps.imports",
    "docintel.apps.documents",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "docintel.apps.core.middleware.RequestIDMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "docintel.apps.core.middleware.AccessLogMiddleware",
]

ROOT_URLCONF = "docintel.config.urls"
WSGI_APPLICATION = "docintel.config.wsgi.application"
ASGI_APPLICATION = "docintel.config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

DATABASES = {
    "default": database_from_url(
        optional("DATABASE_URL", "postgres://docintel:docintel@localhost:5432/docintel")
    )
}

AUTH_USER_MODEL = "core.User"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

REDIS_URL = optional("REDIS_URL", "redis://localhost:6379/0")
CELERY_BROKER_URL = optional("CELERY_BROKER_URL", REDIS_URL)
CELERY_RESULT_BACKEND = optional("CELERY_RESULT_BACKEND", REDIS_URL)
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_TASK_TRACK_STARTED = True
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_RESULT_EXPIRES = 60 * 60
CELERY_TASK_ALWAYS_EAGER = False
CELERY_TASK_EAGER_PROPAGATES = False

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
        "KEY_PREFIX": "docintel",
        "TIMEOUT": 300,
    }
}

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "docintel.apps.core.authentication.CompanyJWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "docintel.apps.core.exception_handler.exception_handler",
    "DEFAULT_THROTTLE_RATES": {
        "document_upload": "30/hour",
        "document_export": "10/hour",
        "document_reprocess": "5/hour",
    },
    "UNAUTHENTICATED_USER": None,
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ALGORITHM": "HS256",
    "SIGNING_KEY": SECRET_KEY,
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "AUTH_HEADER_TYPES": ("Bearer",),
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Docintel API",
    "DESCRIPTION": "Multi-tenant document intelligence: upload, extract, review, sync.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "ENUM_NAME_OVERRIDES": {
        "DocumentStatusEnum": "docintel.apps.documents.models.Document.Status",
        "ImportJobStatusEnum": "docintel.apps.imports.models.ImportJob.Status",
        "SyncEventStatusEnum": "docintel.apps.sync.models.SyncEvent.Status",
        "MembershipRoleEnum": "docintel.apps.core.models.Membership.Role",
        "FieldSourceEnum": "docintel.apps.documents.models.ExtractedField.Source",
    },
}

AWS_ACCESS_KEY_ID = optional("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = optional("AWS_SECRET_ACCESS_KEY", "")
AWS_DEFAULT_REGION = optional("AWS_DEFAULT_REGION", "us-east-1")
AWS_S3_BUCKET = optional("AWS_S3_BUCKET", "docintel-local")
AWS_S3_ENDPOINT_URL = optional("AWS_S3_ENDPOINT_URL", "")
AWS_TEXTRACT_SNS_TOPIC_ARN = optional("AWS_TEXTRACT_SNS_TOPIC_ARN", "")
AWS_TEXTRACT_SNS_ROLE_ARN = optional("AWS_TEXTRACT_SNS_ROLE_ARN", "")
AWS_KMS_KEY_ID = optional("AWS_KMS_KEY_ID", "")
AWS_SES_SENDER = optional("AWS_SES_SENDER", "reviews@docintel.invalid")

STORAGE_BACKEND = optional("DOCINTEL_STORAGE_BACKEND", "s3")
TEXTRACT_BACKEND = optional("DOCINTEL_TEXTRACT_BACKEND", "boto3")
REDIS_BACKEND = optional("DOCINTEL_REDIS_BACKEND", "redis")
EMAIL_BACKEND_IMPL = optional("DOCINTEL_EMAIL_BACKEND", "ses")

SENTRY_DSN = optional("SENTRY_DSN", "")
SENTRY_ENVIRONMENT = optional("SENTRY_ENVIRONMENT", "local")
LOG_LEVEL = optional("LOG_LEVEL", "INFO")
JSON_LOGS = True

ALLOWED_UPLOAD_CONTENT_TYPES = (
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/tiff",
)
