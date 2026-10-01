# Architecture

Docintel is one Django project and four apps. `core` is the tenant and request boundary. `documents` is the product. `sync` and `imports` are shared machinery that documents plugs into; they do not import the documents app.

## Request path

1. `RequestIDMiddleware` accepts `X-Request-ID` or mints one, binds it into structlog, and tags Sentry.
2. `CompanyJWTAuthentication` validates the access token, loads `Membership` for the `company_id` claim, and sets `request.company`. A token for a company the user has left is an authentication failure.
3. `HasToolPermission` resolves the view's tool and action. User grants replace role grants, which replace the built-in role matrix.
4. The view calls a service. Object lookup uses `Model.objects.for_company(request.company)`, so another tenant's id is a 404.

Celery tasks copy `request_id` from the structlog context into task headers (`before_task_publish`) and bind it again on the worker.

## Idempotency

| Step | Mechanism |
| --- | --- |
| Upload complete | Row lock. If the status is no longer `pending_upload`, the call returns the current row and does not enqueue. |
| Textract start | `ClientRequestToken` is `sha256(document_id)` truncated to 64 chars. A retry returns the original job. The task also returns immediately when a job id is already stored. |
| Textract completion | SNS and the poller both call `ingest_job`. The row is locked; if the status is not `processing`, the call returns. Fields are deleted and reinserted in that same transaction, so a replay replaces rather than duplicates. |
| Import commit | `bulk_create(..., update_conflicts=True)` on `(company, normalized_name)`. A second commit of a `committed` job returns. Chunks are their own transactions, so a crash resumes as an upsert. |
| Sync delivery | Outbox unique key is `(company, idempotency_key)`. Approval uses `document.approved:{id}:{version}`. The webhook sends that key as `Idempotency-Key` and an HMAC of the raw body. A success log for a rule is not sent again. |
| Review writes | `If-Match` must equal `Document.version`. Transitions increment the version under `select_for_update`. |

`emit_event` inserts in the caller's transaction and registers the Celery send with `transaction.on_commit`. A rollback keeps neither the row nor the task. The beat sweeper claims due `pending` rows with `SELECT … FOR UPDATE SKIP LOCKED` in case the process died after commit and before the broker accepted the message.

## Document state

`pending_upload → uploaded → processing → needs_review | extracted → approved | rejected`, plus `failed`. `failed` and `rejected` can return to `processing` (reprocess). `approved` is terminal. The allowed edges live on `Document.ALLOWED` and are mirrored by a `CheckConstraint`.

After extraction, line totals are compared with subtotal and subtotal + tax with total, within `Tuning.amount_tolerance`. Required fields under the company confidence threshold, a failed balance check, or an unmatched vendor name send the document to `needs_review` and record the reason codes. Otherwise the status is `extracted`.

## Data that is not in Postgres

- The original file and the gzipped Textract response live in S3 under `tenants/{company_id}/…`. Presigned GETs call `assert_tenant_key` again.
- Review digests are debounced with `SET key NX EX` so a burst of documents becomes one SES email.
- `document.status_changed` is published to Redis channel `tenant:{company_id}`.

## Observability

structlog JSON lines include `request_id`, `company_id`, `document_id`, and `task_id` when those values exist. Sentry is initialised with the Django and Celery integrations. `before_send` redacts emails, tax ids, secrets, and extracted values. Task success and failure log a duration.

## Settings

`Tuning` in `docintel/config/settings/tuning.py` holds thresholds, TTLs, and retry budgets. `Company.settings` may override confidence, amount tolerance, and the vendor similarity threshold. Production settings refuse to boot without the required environment variables and turn on the usual `SECURE_*` flags.
