# 0006 Licence policy

## Context

The marketplace only ships permissively licensed dependencies (MIT, Apache-2.0, BSD and the usual permissive variants such as ISC, PSF, HPND, 0BSD). Copyleft in the application process is a legal review, not a silent upgrade.

## Decision

Direct dependencies are pinned in `pyproject.toml` and listed in `THIRD_PARTY_LICENSES.md`. CI runs `scripts/check_licenses.py`, which reads installed distribution metadata and fails on any licence outside the allow-list.

`psycopg` (LGPL-3.0-only) is a documented exception. It is the PostgreSQL driver, it is not modified, and it is loaded dynamically by Django. That exception should be confirmed with counsel before this code is linked into the product. `certifi` (MPL-2.0) is a transitive exception pulled in by the AWS and Sentry stacks; MPL-2.0 is file-level copyleft and the package is used unmodified.

## Consequences

- Adding a dependency means checking its licence expression and, if it is not permissive, stopping to write the exception down.
- The allow-list is stricter than "OSI approved". GPL and AGPL fail the build.
- The driver exception is explicit so it cannot be mistaken for an oversight.
