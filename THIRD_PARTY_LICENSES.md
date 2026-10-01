# Third-party licences

Direct dependencies are pinned in `pyproject.toml`. CI checks every installed distribution, not only this list, via `python scripts/check_licenses.py` and writes a `pip-licenses` report. The allow-list is MIT, Apache-2.0, BSD (2- and 3-clause), PSF-2.0, ISC, HPND, Zlib, 0BSD, and Unlicense.

Source pages are the project URLs on PyPI.

## Runtime

| Package | Version | Licence | Source |
| --- | --- | --- | --- |
| django | 5.2.17 | BSD-3-Clause | https://pypi.org/project/Django/ |
| djangorestframework | 3.16.1 | BSD-3-Clause | https://pypi.org/project/djangorestframework/ |
| djangorestframework-simplejwt | 5.5.1 | MIT | https://pypi.org/project/djangorestframework-simplejwt/ |
| drf-spectacular | 0.29.0 | BSD-3-Clause | https://pypi.org/project/drf-spectacular/ |
| django-filter | 25.2 | BSD | https://pypi.org/project/django-filter/ |
| boto3 | 1.43.106 | Apache-2.0 | https://pypi.org/project/boto3/ |
| celery | 5.6.3 | BSD-3-Clause | https://pypi.org/project/celery/ |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause | https://pypi.org/project/cryptography/ |
| gunicorn | 26.2.0 | MIT | https://pypi.org/project/gunicorn/ |
| pydantic | 2.13.5 | MIT | https://pypi.org/project/pydantic/ |
| redis | 8.1.0 | MIT | https://pypi.org/project/redis/ |
| sentry-sdk | 2.71.0 | MIT | https://pypi.org/project/sentry-sdk/ |
| structlog | 26.1.0 | MIT OR Apache-2.0 | https://pypi.org/project/structlog/ |
| psycopg | 3.3.6 | LGPL-3.0-only | https://pypi.org/project/psycopg/ |

## Development

| Package | Version | Licence | Source |
| --- | --- | --- | --- |
| pytest | 9.1.1 | MIT | https://pypi.org/project/pytest/ |
| pytest-django | 4.14.0 | BSD-3-Clause | https://pypi.org/project/pytest-django/ |
| pytest-cov | 7.1.0 | MIT | https://pypi.org/project/pytest-cov/ |
| factory-boy | 3.3.3 | MIT | https://pypi.org/project/factory-boy/ |
| freezegun | 1.5.5 | Apache-2.0 | https://pypi.org/project/freezegun/ |
| mypy | 1.19.1 | MIT | https://pypi.org/project/mypy/ |
| django-stubs | 5.2.9 | MIT | https://pypi.org/project/django-stubs/ |
| djangorestframework-stubs | 3.16.9 | MIT | https://pypi.org/project/djangorestframework-stubs/ |
| ruff | 0.16.9 | MIT | https://pypi.org/project/ruff/ |
| pre-commit | 4.6.2 | MIT | https://pypi.org/project/pre-commit/ |
| pip-licenses | 5.5.5 | MIT | https://pypi.org/project/pip-licenses/ |

## Exceptions that need a business confirmation

### psycopg (LGPL-3.0-only)

psycopg is the PostgreSQL driver Django loads at runtime. It is not modified, it is not statically linked into the application, and the process talks to it as a dynamically loaded library. LGPL-3.0 is not a permissive licence. It is listed here so the choice is visible, and it should be confirmed with counsel before this service is shipped. `psycopg-binary` / `psycopg2`, if pulled in, are the same exception.

The CI allow-list fails any other LGPL or GPL package.

### certifi (MPL-2.0, transitive)

`certifi` is pulled in by the AWS SDK and Sentry. MPL-2.0 is file-level weak copyleft. The package is used unmodified as the CA bundle. It is an explicit exception in `scripts/check_licenses.py`, not a permissive licence.
