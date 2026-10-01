# 0003 Direct-to-S3 uploads

## Context

Invoice PDFs are larger than we want on a Gunicorn worker, and streaming them through Django makes the app part of the data plane.

## Decision

`POST /api/v1/documents/uploads/` inserts a `pending_upload` row and returns a presigned POST. Conditions pin the exact key, content type, content-length range, and server-side encryption (`AES256`, or `aws:kms` when a key id is configured). The key is `tenants/{company_id}/documents/{yyyy}/{mm}/{document_id}/{safe_name}`.

`complete` HEADs the object, checks the size, sniffs magic bytes, and hashes the body. The client content type is not trusted. Download URLs are presigned GETs with a short TTL, and only after the key still starts with that tenant's prefix.

CSV import is the exception: those files are streamed from the client into S3 by the API because the pipeline must parse them itself. They are still not loaded as one `bytes` blob during preview and commit.

## Consequences

- The API cannot see a file that was never completed. Those rows stay `pending_upload` until a sweeper (not built) expires them.
- Presigned POST expiry is `upload_url_ttl_seconds`.
- Local and test runs use an in-memory storage adapter with the same method names, so the service code does not branch on the backend.
