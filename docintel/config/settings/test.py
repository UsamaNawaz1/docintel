"""Fast, deterministic test settings. No network and no real AWS."""

from __future__ import annotations

from docintel.config.settings.base import *

DEBUG = False
SECRET_KEY = "test-secret-key"
STORAGE_BACKEND = "memory"
TEXTRACT_BACKEND = "fake"
REDIS_BACKEND = "memory"
EMAIL_BACKEND_IMPL = "memory"
JSON_LOGS = False
SENTRY_DSN = ""

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "docintel-test",
    }
}

DATABASES["default"]["CONN_MAX_AGE"] = 0  # type: ignore[index]
