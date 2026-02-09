# Architecture Hardening - Phase 1

This document captures the first unslop/hardening pass aimed at reducing coupling, removing dead code, and making the codebase safer to extend.

## Goals

- Keep runtime behavior stable.
- Reduce monolithic logic in `app/main.py`.
- Remove duplicate/unused implementation paths.
- Add unit-level safety checks for core normalization/serialization logic.

## What changed

### 1) Extracted cross-cutting helper logic into focused services

- `app/services/failure_reason.py`
  - Failure bucket classification and normalization.
  - Shared by run failure summary/drilldown paths.

- `app/services/view_builders.py`
  - JSON-list parsing helper for persisted string fields.
  - Prompt view model builder.
  - Run payload serialization for run detail endpoints.

- `app/services/runtime_maintenance.py`
  - Startup maintenance routines:
    - backfill failed runs with missing metadata
    - cancel stale in-progress runs after restart

- `app/services/baseline_helpers.py`
  - Baseline source/key/run linking utilities.
  - Local PDF resolution helpers.
  - Baseline summary builders.

`app/main.py` now uses these modules, reducing internal helper bloat and making logic testable in isolation.

### 2) Dead code/duplicate stack cleanup

Removed unused files/directories that were no longer referenced:

- `app/models.py`
- `app/utils/pdf_text_extractor.py`
- `app/llm_providers/` (legacy duplicate provider stack)

Active provider path remains:

- `app/integrations/llm/`

### 3) Safer default queue concurrency

Changed default `QUEUE_CONCURRENCY` from `512` to `3` in `app/config.py`.

This remains fully configurable via environment variable and avoids accidental overload on typical dev machines.

### 4) Fixed DOI normalization bug

Corrected version-suffix stripping regex from broken escaped pattern to:

- `r"/v\d+$"`

Locations:

- `app/services/baseline_helpers.py`
- `app/baseline/loader.py`

This directly improves DOI-based grouping/dedup for baseline runs.

### 5) Added unit tests for critical helper behavior

New tests under `tests/unit/`:

- `test_failure_reason.py`
- `test_view_builders.py`
- `test_baseline_helpers.py`

Validated with:

- `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`

## Current architectural boundaries (targeted)

- `app/main.py`
  - FastAPI app wiring, route registration, dependency composition.

- `app/services/*`
  - Application/business orchestration and shared domain helpers.

- `app/integrations/*`
  - External I/O adapters (LLM/document providers).

- `app/persistence/*`
  - Data models, repositories, migration wiring.

- `public/*`
  - Static UI clients.

## Next phases (recommended)

1. Split API routes out of `app/main.py` by domain (`runs`, `baseline`, `entities`, `prompts`, etc.).
2. Introduce a backend contract module for stable API DTO evolution and deprecation policy.
3. Modularize `public/baseline.js` and `public/app.js` into feature-focused modules.
4. Add integration tests for key endpoints and queue transitions.
5. Decide explicit removal window for legacy `Extraction` table read fallbacks.
