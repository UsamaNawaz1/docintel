"""WSGI entrypoint."""

from __future__ import annotations

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docintel.config.settings.production")

application = get_wsgi_application()
