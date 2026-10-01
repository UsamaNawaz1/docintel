"""Root URLconf. Health checks stay outside the versioned API."""

from __future__ import annotations

from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from docintel.apps.core.views import healthz, readyz

urlpatterns = [
    path("healthz", healthz, name="healthz"),
    path("readyz", readyz, name="readyz"),
    path("admin/", admin.site.urls),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger"),
    path("api/v1/", include("docintel.config.api_urls")),
]
