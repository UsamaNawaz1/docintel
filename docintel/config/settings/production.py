"""Production settings. Missing secrets abort process start."""

from __future__ import annotations

from docintel.config.settings.base import *
from docintel.config.settings.env import csv_list, database_from_url, required

DEBUG = False
SECRET_KEY = required("SECRET_KEY")
ALLOWED_HOSTS = csv_list("ALLOWED_HOSTS", "")
if not ALLOWED_HOSTS:
    raise RuntimeError("ALLOWED_HOSTS is required in production")

DATABASES = {"default": database_from_url(required("DATABASE_URL"))}
REDIS_URL = required("REDIS_URL")
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
        "KEY_PREFIX": "docintel",
        "TIMEOUT": 300,
    }
}

AWS_ACCESS_KEY_ID = required("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = required("AWS_SECRET_ACCESS_KEY")
AWS_S3_BUCKET = required("AWS_S3_BUCKET")
AWS_DEFAULT_REGION = required("AWS_DEFAULT_REGION")
AWS_TEXTRACT_SNS_TOPIC_ARN = required("AWS_TEXTRACT_SNS_TOPIC_ARN")
AWS_TEXTRACT_SNS_ROLE_ARN = required("AWS_TEXTRACT_SNS_ROLE_ARN")
SENTRY_DSN = required("SENTRY_DSN")
SENTRY_ENVIRONMENT = required("SENTRY_ENVIRONMENT")

STORAGE_BACKEND = "s3"
TEXTRACT_BACKEND = "boto3"
REDIS_BACKEND = "redis"
EMAIL_BACKEND_IMPL = "ses"
JSON_LOGS = True

SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SECURE_HSTS_SECONDS = 31_536_000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# Re-bind JWT signing to the production secret after base was imported.
SIMPLE_JWT["SIGNING_KEY"] = SECRET_KEY  # type: ignore[index]
