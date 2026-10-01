"""Vendor matching.

Exact tax id wins. Otherwise the best trigram score across ``normalized_name``
and aliases is kept when it clears the tenant threshold. The GIN index
``vendor_name_trgm`` serves the name path. Alias similarity is an ``unnest``
over that tenant's vendors, which is small next to the document table.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.contrib.postgres.search import TrigramSimilarity
from django.db import connection

from docintel.apps.core.models import Company
from docintel.apps.documents.models import Vendor
from docintel.apps.documents.normalization import normalize_name, normalize_tax_id
from docintel.config.settings.tuning import Tuning


@dataclass(frozen=True)
class VendorMatch:
    vendor: Vendor
    score: Decimal


def match_vendor(
    *,
    company: Company,
    vendor_name: str,
    tax_id: str,
    tuning: Tuning,
) -> VendorMatch | None:
    normalized_tax = normalize_tax_id(tax_id)
    if normalized_tax:
        # Equality on (company, tax_id). Tax id is selective; no extra index
        # beyond the company FK plus a filter. Add one if this shows up hot.
        exact = (
            Vendor.objects.for_company(company).filter(tax_id=normalized_tax).order_by("created_at").first()
        )
        if exact is not None:
            return VendorMatch(vendor=exact, score=Decimal("1.0000"))
    normalized = normalize_name(vendor_name)
    if not normalized:
        return None
    threshold = tuning.vendor_similarity_threshold
    by_name = (
        Vendor.objects.for_company(company)
        .annotate(name_sim=TrigramSimilarity("normalized_name", normalized))
        .filter(name_sim__gte=threshold)
        .order_by("-name_sim")
        .first()
    )
    name_score = Decimal(str(getattr(by_name, "name_sim", 0) or 0)) if by_name else Decimal("0")
    alias = _alias_match(company, normalized, threshold)
    if alias is not None and (by_name is None or alias.score > name_score):
        return alias
    if by_name is None:
        return None
    return VendorMatch(vendor=by_name, score=name_score.quantize(Decimal("0.0001")))


def _alias_match(company: Company, normalized: str, threshold: float) -> VendorMatch | None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT vendor.id, MAX(similarity(alias, %s)) AS score
            FROM documents_vendor AS vendor
            CROSS JOIN LATERAL unnest(vendor.aliases) AS alias
            WHERE vendor.company_id = %s
            GROUP BY vendor.id
            HAVING MAX(similarity(alias, %s)) >= %s
            ORDER BY score DESC
            LIMIT 1
            """,
            [normalized, str(company.id), normalized, threshold],
        )
        row = cursor.fetchone()
    if row is None:
        return None
    vendor = Vendor.objects.for_company(company).get(id=row[0])
    return VendorMatch(vendor=vendor, score=Decimal(str(row[1])).quantize(Decimal("0.0001")))
