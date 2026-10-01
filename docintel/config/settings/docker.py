"""Docker Compose settings: real Redis, tasks not eager, fake AWS by default."""

from __future__ import annotations

from docintel.config.settings.env import optional
from docintel.config.settings.local import *

CELERY_TASK_ALWAYS_EAGER = False
CELERY_TASK_EAGER_PROPAGATES = False
REDIS_BACKEND = "redis"
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
        "KEY_PREFIX": "docintel",
    }
}
STORAGE_BACKEND = optional("DOCINTEL_STORAGE_BACKEND", "memory")
TEXTRACT_BACKEND = optional("DOCINTEL_TEXTRACT_BACKEND", "fake")
EMAIL_BACKEND_IMPL = "memory"
