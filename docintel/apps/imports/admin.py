from django.contrib import admin

from docintel.apps.core.admin import UnscopedModelAdmin
from docintel.apps.imports.models import ImportJob


@admin.register(ImportJob)
class ImportJobAdmin(UnscopedModelAdmin):
    list_display = ("company", "importer_slug", "status", "row_count", "error_count")
    list_filter = ("status", "importer_slug")
