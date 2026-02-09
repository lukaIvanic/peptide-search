# Edge Coverage Checklist

This checklist tracks high-risk queue/retry/contract branches covered by integration tests.

## Queue Coordinator
- [x] `enqueue_new_run` rejects blank source URL.
- [x] `enqueue_new_run` dedupes overlapping `pdf_url`/`pdf_urls`.
- [x] `enqueue_new_run` returns conflict metadata for existing source lock.
- [x] `enqueue_existing_run` short-circuits for `queued|claimed` jobs.
- [x] `enqueue_existing_run` requeues failed job and resets claim metadata.
- [x] `enqueue_existing_run` updates lock set when source URLs change.
- [x] `claim_next_job` respects `available_at` ordering.
- [x] `claim_next_job` returns `None` when nothing claimable.
- [x] `finish_job` ignores wrong claim token.
- [x] `finish_job` terminal states release active locks.
- [x] `recover_stale_claims` requeues at timeout.
- [x] `recover_stale_claims` ignores `claimed_at=None`.
- [x] `recover_stale_claims` fails deterministically at attempt threshold.
- [x] `has_active_lock_for_urls` handles blank input and alternate `pdf_urls`.

## Retry Flows
- [x] run retry: missing run -> `404` envelope.
- [x] run retry: missing paper -> `404` envelope.
- [x] run retry: non-failed run -> `400` envelope.
- [x] run retry: pending source conflict returns already-queued response.
- [x] retry-with-source: missing source -> `400` envelope.
- [x] retry-with-source: pending source conflict avoids child-run creation.
- [x] bulk retry: bucket/provider/source/reason filters.
- [x] bulk retry: `limit` boundary.
- [x] bulk retry: `max_runs` boundary.
- [x] bulk retry: skipped reconciliation for missing PDF.
- [x] baseline retry: nonexistent case -> `404` envelope.
- [x] baseline retry: unresolved source -> `400` envelope.
- [x] baseline retry: shared-source case-link propagation.
- [x] batch retry: upload URL remap + missing PDF skip.

## API Contracts
- [x] validation errors use envelope with `error.details`.
- [x] `bad_request` code mapping for runtime `400`.
- [x] `not_found` code mapping for runtime `404`.
- [x] enqueue response key contract.
- [x] run detail response key contract.
- [x] retry response key contract.
- [x] `created_at` uses `ISO8601 + Z` on key endpoints.

## Migration Guardrails
- [x] stale schema rejected with migration command hint.
- [x] stale schema error includes current/head revision details.
- [x] missing `alembic_version` rejected with migration command hint.
- [x] head schema accepted.
