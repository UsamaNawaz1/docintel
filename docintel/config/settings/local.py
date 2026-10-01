"""Local development defaults. Safe to boot without AWS or Redis."""

from __future__ import annotations

from docintel.config.settings.base import *
from docintel.config.settings.env import as_bool, optional

DEBUG = as_bool(optional("DJANGO_DEBUG", "true"))
STORAGE_BACKEND = optional("DOCINTEL_STORAGE_BACKEND", "memory")
TEXTRACT_BACKEND = optional("DOCINTEL_TEXTRACT_BACKEND", "fake")
REDIS_BACKEND = optional("DOCINTEL_REDIS_BACKEND", "memory")
EMAIL_BACKEND_IMPL = optional("DOCINTEL_EMAIL_BACKEND", "memory")
JSON_LOGS = as_bool(optional("JSON_LOGS", "false"))
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "docintel-local",
    }
}
