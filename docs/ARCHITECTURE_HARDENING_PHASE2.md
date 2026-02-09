# Architecture Hardening Phase 2

## Scope

This phase executed the three requested items:

1. Split `app/main.py` into domain routers.
2. Modularize `public/baseline.js` and `public/app.js`.
3. Add API integration tests for queue transitions and baseline retry flows.

## Backend: Router Split

`app/main.py` now handles only:
- app initialization
- CORS setup
- startup/shutdown lifecycle (DB init, queue start/stop, callback wiring)
- static HTML routes
- router registration

API domain handlers moved into:
- `app/api/routers/system_router.py`
- `app/api/routers/search_router.py`
- `app/api/routers/extraction_router.py`
- `app/api/routers/papers_router.py`
- `app/api/routers/runs_router.py`
- `app/api/routers/metadata_router.py`
- `app/api/routers/baseline_router.py`

This reduces coupling and makes endpoint ownership explicit.

## Frontend: Entry-Point Decomposition

### Dashboard (`public/app.js`)
Extracted filter/csv utilities and state helpers to:
- `public/js/dashboard/paper_filters.js`

`public/app.js` now consumes those utilities instead of embedding all filter/storage/export logic.

### Baseline (`public/baseline.js`)
Extracted shared constants and low-level utility functions to:
- `public/js/baseline/helpers.js`

`public/baseline.js` now focuses more on orchestration/rendering.

## Integration Tests Added

New integration suite:
- `tests/integration/test_api_queue_and_baseline_retry.py`

Covers:
- failed run bulk retry transition (`failed -> queued`) via `/api/runs/failures/retry`
- baseline case retry dedupe behavior via `/api/baseline/cases/{case_id}/retry`
- baseline batch retry behavior via `/api/baseline/batch-retry`

The suite runs against an isolated temporary SQLite database and forces queue concurrency to `0` for deterministic API behavior.

## Validation

Executed successfully:
- `.venv/bin/python -m compileall app tests/integration`
- `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`
- `.venv/bin/python -m unittest discover -s tests/integration -p 'test_*.py'`
- `node --check public/app.js`
- `node --check public/baseline.js`
- `node --check public/js/dashboard/paper_filters.js`
- `node --check public/js/baseline/helpers.js`
