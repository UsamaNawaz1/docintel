from django.contrib import admin

from docintel.apps.core.admin import UnscopedModelAdmin
from docintel.apps.documents.models import Document, Vendor


@admin.register(Vendor)
class VendorAdmin(UnscopedModelAdmin):
    list_display = ("company", "name", "tax_id", "default_gl_code")
    search_fields = ("name", "normalized_name", "tax_id")


@admin.register(Document)
class DocumentAdmin(UnscopedModelAdmin):
    list_display = ("company", "original_filename", "status", "invoice_number", "total")
    list_filter = ("status",)
