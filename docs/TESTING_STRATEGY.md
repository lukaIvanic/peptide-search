# Testing Strategy

## Short answer

Yes, tests are a strong fit for this app.

The LLM output is probabilistic, but most of the system is deterministic and should be tested aggressively:
- API contracts
- queue state transitions
- retry behavior
- persistence and linking rules
- baseline/batch bookkeeping

## Test pyramid for this codebase

1. Unit tests (`tests/unit/`)
- pure helpers/services
- schema shaping and normalization
- failure bucketing/classification

2. Integration API tests (`tests/integration/`)
- run with isolated temporary SQLite DB
- queue concurrency set to `0` for deterministic behavior
- assert endpoint behavior and DB side effects

3. Minimal end-to-end smoke checks
- one or two critical happy-path checks against a local running app
- avoid over-indexing on brittle UI assertions while frontend is evolving

## What not to test directly

- exact LLM text/content values from external providers
- provider-specific timing or token usage variability

Instead, test:
- that provider failures are handled and persisted correctly
- that retries and status transitions are correct
- that response schemas stay stable

## Current integration harness

`tests/integration/support.py` provides reusable setup/teardown for:
- temporary DB engine swap
- queue reset
- `TestClient` lifecycle

This keeps new endpoint tests short and consistent.

## Next high-value tests

1. `/api/enqueue` dedupe + force behavior
2. `/api/runs/{id}/history` lineage consistency
3. baseline source-resolution fallback matrix
4. SSE event payload contract for run status updates
