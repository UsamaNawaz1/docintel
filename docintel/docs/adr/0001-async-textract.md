# 0001 Async Textract with SNS and a poller

## Context

`AnalyzeExpense` has a synchronous API that holds the worker for the whole document, and an asynchronous API (`StartExpenseAnalysis`) that is the supported path for multi-page PDFs. Completions need a way back into the app.

## Decision

Start jobs asynchronously with a `NotificationChannel`. `POST /api/v1/webhooks/textract/` verifies the SNS signature and enqueues ingest. A Celery beat task polls documents still in `processing` after `textract_poll_after_seconds`, using the partial index on that status. Both paths call `ingest_job`, which locks the row and no-ops unless the status is still `processing`.

`ClientRequestToken` is a hash of the document id, so a retry does not start a second job. An SNS message that arrives before the job id is saved is acknowledged and left for the poller.

## Consequences

- A lost notification still completes, one poll interval later.
- Reprocess re-reads the same Textract job. Forcing a new analysis needs a generation salt on the token.
- The webhook is public. Authentication is the SNS signature and the certificate host check, not JWT.
