# 0002 Transactional outbox

## Context

Approval must update the document and notify a downstream system. Writing the HTTP call inside the request couples the user's transaction to a third party. Writing it after commit can lose the event if the process dies.

## Decision

`emit_event` inserts `SyncEvent` in the caller's transaction and enqueues delivery with `transaction.on_commit`. A sweeper claims leftover `pending` rows with `FOR UPDATE SKIP LOCKED`. Delivery talks HTTP outside the row lock, records `SyncDeliveryLog`, and either marks the event delivered, schedules exponential backoff with full jitter, or moves it to `dead_letter` after `sync_max_attempts`.

Field mapping is a pydantic model of dotted source paths. The body is signed with HMAC-SHA256 and sent with the outbox idempotency key.

## Consequences

- A rolled-back approval cannot emit.
- Destinations must treat `Idempotency-Key` as the dedupe token. Replay does not mint a new one.
- A crash during HTTP can leave a row in `processing` until an operator replays it or the claim is extended. The sweeper currently picks up `pending` only.
