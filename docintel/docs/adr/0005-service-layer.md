# 0005 Service and selector layering

## Context

Putting transitions, HTTP, and query shaping in views makes them untestable without the request stack and hides the transaction boundary.

## Decision

Views validate a serializer, read `request.company`, call one service function, and serialize the result. Services own `transaction.atomic` and `select_for_update`. Selectors own `select_related` / `prefetch_related` and are the only place list, detail, review, and export queries are built. AWS, SNS, SES, and webhooks sit behind small adapters or functions with an injectable transport.

Domain failures are `DomainError` subclasses with a stable `code`. The DRF exception handler is the only place that builds the error envelope.

## Consequences

- A service can be called from a task, a management command, or a test without a request.
- Views stay repetitive on purpose. The variation belongs in the service.
- Selectors return querysets; pagination stays in the view so the selector does not know about cursors.
