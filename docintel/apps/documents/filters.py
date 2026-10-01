"""List filters. Search uses the vendor trigram index plus invoice number."""

from __future__ import annotations

from django.db.models import Q, QuerySet
from django_filters import rest_framework as filters

from docintel.apps.documents.models import Document


class DocumentFilter(filters.FilterSet):
    status = filters.ChoiceFilter(field_name="status", choices=Document.Status.choices)
    vendor = filters.UUIDFilter(field_name="vendor_id")
    invoice_date_after = filters.DateFilter(field_name="invoice_date", lookup_expr="gte")
    invoice_date_before = filters.DateFilter(field_name="invoice_date", lookup_expr="lte")
    total_min = filters.NumberFilter(field_name="total", lookup_expr="gte")
    total_max = filters.NumberFilter(field_name="total", lookup_expr="lte")
    search = filters.CharFilter(method="filter_search")

    class Meta:
        model = Document
        fields: list[str] = []

    def filter_search(self, queryset: QuerySet[Document], name: str, value: str) -> QuerySet[Document]:
        del name
        # doc_co_invoice_no supports equality; icontains is the reviewer's
        # search box. vendor_name_trgm (GIN trigram) serves the vendor side.
        return queryset.filter(
            Q(invoice_number__icontains=value) | Q(vendor__normalized_name__trigram_similar=value)
        )
