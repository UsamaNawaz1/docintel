# 0004 Tenant scoping on the manager

## Context

A missing `company_id` filter is a data leak. Reviewing every queryset by hand does not scale, and a 403 on another tenant's id confirms that the id exists.

## Decision

`TenantManager.get_queryset` raises `UnscopedQueryError`. Callers use `objects.for_company(company)`. `unscoped` is the explicit escape hatch for admin, the auth check that validates a JWT claim, and workers that scan all tenants. `base_manager_name` is `unscoped` so Django can load relations; selectors still enter through `for_company`.

API lookups that miss the company filter raise `NotFound` (HTTP 404).

## Consequences

- `Model.objects.all()` fails closed in application code.
- Django admin subclasses `UnscopedModelAdmin`.
- `dumpdata` against the default manager will raise. Maintenance commands should use `unscoped`.
- Child rows carry their own `company_id` so a prefetch can stay on `for_company` instead of trusting the join alone.
