"""Tenant query scoping.

``objects`` refuses to run a query until ``for_company`` is called. Cross-tenant
reads are therefore a deliberate use of ``unscoped``, which is reserved for
admin screens, workers that scan every tenant, and auth validation of a JWT
claim. Related-object loading uses ``unscoped`` via ``base_manager_name`` so
Django internals keep working; selectors still enter through ``for_company``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from django.db import models

from docintel.apps.core.exceptions import UnscopedQueryError

if TYPE_CHECKING:
    from docintel.apps.core.models import Company


class TenantQuerySet(models.QuerySet):
    def for_company(self, company: Company) -> TenantQuerySet:
        return cast(TenantQuerySet, self.filter(company=company))


class UnscopedManager(models.Manager.from_queryset(TenantQuerySet)):  # type: ignore[misc]
    """Maintenance manager. Call sites should justify why they are unscoped."""


class TenantManager(models.Manager):
    def get_queryset(self) -> TenantQuerySet:
        raise UnscopedQueryError(
            f"{self.model.__name__}.objects requires .for_company(company). "
            "Use .unscoped for admin and maintenance."
        )

    def for_company(self, company: Company) -> TenantQuerySet:
        return TenantQuerySet(self.model, using=self._db).filter(company=company)
