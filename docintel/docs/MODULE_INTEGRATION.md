# Module integration

Documents is a tenant of the platform primitives. It does not reimplement them.

## Tenancy

`Vendor`, `Document`, `ExtractedField`, `LineItem`, and `DocumentEvent` extend `TenantScopedModel`. Application code uses `objects.for_company`. Workers that scan every tenant (the Textract poller, the outbox sweeper) use `unscoped` and bind `company_id` into the log context as soon as they load a row. S3 keys start with `tenants/{company_id}/` and are checked again before a download URL is signed.

## Permissions

The tool slug is `documents`. Actions:

| Endpoint | Action |
| --- | --- |
| List, detail | `view` |
| Upload, complete | `create` |
| Review queue, field patch, approve, reject | `review` |
| `export.csv` | `export` |
| Reprocess | `admin` |

Imports use the tool slug `imports` (`view` for the template, `create` for upload, preview, and commit). Defaults: owner and admin have every action; reviewer has `view` and `review`; member has `view` and `create`. A `ToolPermission` row for the user, or else for the role, replaces that default for one tool.

Upload, export, and reprocess throttles are keyed by company id in the Django cache.

## Sync

`approve_document` calls `emit_event` inside the same transaction as the status change. The event type is `document.approved`. The payload is the denormalized invoice plus line items, with money as strings. A `SyncRule` for that event type maps dotted source paths onto the webhook body and signs it. Dead letters are replayed with `manage.py replay_sync_events` or the admin action; the idempotency key does not change.

## Imports

`VendorImporter` is registered from `DocumentsConfig.ready`. The generic pipeline owns the job row, streaming parse, preview errors, and chunked commit. The importer owns the row schema and the upsert. Vendors are later matched to extracted invoices by tax id, then trigram similarity on the normalized name and aliases.

## Realtime and mail

Entering `needs_review` schedules `documents.send_review_digest` if the Redis debounce key was not already set, and publishes `document.status_changed` on `tenant:{company_id}`. A Socket.IO service can subscribe to that channel; this repo does not ship one.
