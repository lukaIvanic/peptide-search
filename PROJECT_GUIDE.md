# Peptide Search Project Guide

Single source of truth for mission, architecture, workflows, operations, deployment, and testing.

## 1) Mission and Scope

This project converts scientific literature into structured peptide-centric data:

1. Search open-access sources for papers.
2. Extract structured entities from PDF/HTML with an LLM.
3. Persist runs/entities in SQLite with traceability.
4. Run evaluation batches against baseline datasets to compare model quality, cost, and time.

Primary domain focus:

1. Peptides, especially self-assembling / hydrogel-related peptides.
2. Extraction fields include sequence, terminal modifications, labels, and reported conditions.

Out of scope:

1. This repo is not the downstream model-training pipeline.
2. This repo is not a multi-tenant production platform.

## 2) Product Surfaces

UI routes:

1. `/` dashboard: search, queue, run monitoring.
2. `/baseline` evaluation overview: batch cards and chart.
3. `/baseline/{batch_id}` evaluation details and case-level triage.
4. `/runs/{run_id}` run details/history/follow-ups.
5. `/runs/{run_id}/edit` append-only run editing.
6. `/entities` entity explorer.
7. `/help` usage/troubleshooting.

API families:

1. `system`: health, stream, admin clear.
2. `search`: external literature lookup.
3. `extraction/runs/papers/entities`: core extraction lifecycle.
4. `baseline`: evaluation datasets, case operations, batches, retry/stop/reset.
5. `providers`: provider/model catalog and refresh.

## 3) High-Level Architecture

Backend:

1. FastAPI app with router split under `app/api/routers/`.
2. SQLModel + Alembic migrations.
3. In-process queue engine (`QUEUE_ENGINE_VERSION=v2`) for extraction jobs.
4. Provider registry for OpenAI, DeepSeek, Gemini, OpenRouter, Mock.
5. Static frontend served from `public/`.

Frontend:

1. Static HTML + JS modules under `public/js/`.
2. Shared API client: `public/js/api.js`.
3. SSE stream `/api/stream` for live updates.
4. Runtime config: `public/app_config.js`.

Critical runtime files:

1. `app/main.py`
2. `app/config.py`
3. `app/services/queue_service.py`
4. `app/api/routers/baseline_router.py`
5. `app/services/batch_metrics.py`
6. `scripts/restart_server.sh`
7. `scripts/bootstrap_db_from_snapshot.sh`

## 4) Core Workflows

### 4.1 Search -> Extract -> Persist

1. User searches sources.
2. User queues paper extraction.
3. Queue worker fetches content and runs provider extraction.
4. Payload is validated and stored as run + entities.
5. UI receives status via SSE.

### 4.2 Evaluation Batch Runs

1. User starts batch for dataset/provider/model.
2. Batch creates many extraction runs linked to baseline cases.
3. Batch counters update as runs become stored/failed/cancelled.
4. Batch overview computes ranking/chart metrics from finished + running batches.
5. Details page supports paper-level triage and retries.

### 4.3 Retry and Stop Behavior

1. Retry creates new run attempt; queue handles locking/claims.
2. Batch stop cancels active jobs/runs and marks batch metrics stale for recompute.
3. Failed/cancelled state remains traceable.

## 5) Data and Metrics Semantics

Batch metrics:

1. Match rate is extraction quality against expected baseline entities.
2. Batch time is wall-clock elapsed time from batch start to terminal completion, including retries.
3. Cost is token-price based only when model pricing is known.
4. If pricing is unknown, cost is shown as `n/a` (no fallback guess).

Chart aggregation:

1. Ranking is model-based (not provider-only).
2. Include running, partial, failed, completed where metric definition allows.
3. Use explicit denominator logic per metric and show clear empty-state reasons.

## 6) Local PDF Handling

Mapping and resolution:

1. Mapping file: `app/baseline/data/local_pdfs.json`.
2. Paths are repository-relative.
3. Resolver returns missing gracefully (no app crash).

Behavior:

1. Local PDF endpoints return `found=false` or `404` when absent.
2. Baseline UI should surface local-PDF failures explicitly (not silently swallow errors).

## 7) Configuration Reference

Canonical env source: `env.example` and `app/config.py`.

Core:

1. `DB_URL` (default local: `sqlite:///peptide_search.db`)
2. `LLM_PROVIDER` (`mock|openai|openai-full|openai-mini|openai-nano|deepseek|gemini|openrouter`)

Provider keys/models:

1. `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_MODEL_MINI`, `OPENAI_MODEL_NANO`
2. `DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL`
3. `GEMINI_API_KEY`, `GEMINI_MODEL`
4. `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`

Queue/runtime:

1. `QUEUE_CONCURRENCY` (current default in `env.example`: `1024`)
2. `QUEUE_CLAIM_TIMEOUT_SECONDS`
3. `QUEUE_CLAIM_HEARTBEAT_SECONDS`
4. `QUEUE_RECOVERY_INTERVAL_SECONDS`
5. `QUEUE_MAX_ATTEMPTS`
6. `QUEUE_ENGINE_VERSION` (`v2`)

Deploy bootstrap:

1. `DB_BOOTSTRAP_ON_EMPTY`
2. `DB_BOOTSTRAP_SNAPSHOT`
3. `DB_BOOTSTRAP_TARGET`

Security/network:

1. `ACCESS_GATE_ENABLED`, `ACCESS_GATE_USERNAME`, `ACCESS_GATE_PASSWORD`
2. `CORS_ORIGINS`

Observability:

1. `REQUEST_LOGGING_ENABLED` (default `true`, emits request lifecycle logs and `X-Request-Id` response header)

Prompt definitions:

1. `INCLUDE_DEFINITIONS=true|false`
2. Definitions path used at runtime: `Peptide LLM/definitions_for_llms.md`

## 8) Local Development Runbook

First-time:

1. Create `.venv` and install `requirements.txt`.
2. Copy `env.example` -> `.env`.
3. Run migrations: `alembic upgrade head`.
4. Start server.

Reliable restart sequence:

1. `./scripts/restart_server.sh`
2. Verify: `curl -i http://127.0.0.1:8000/api/health`

Important hostname note:

1. Use `http://127.0.0.1:8000` or `http://localhost:8000`.
2. `http://www.127.0.0.1:8000` is invalid.

## 9) Render Deployment Runbook

Persistent DB deployment:

1. Mount persistent disk at `/var/data`.
2. Set `DB_URL=sqlite:////var/data/peptide_search.db`.
3. Keep bootstrap vars pointing to snapshot in repo:
   1. `DB_BOOTSTRAP_ON_EMPTY=true`
   2. `DB_BOOTSTRAP_SNAPSHOT=/opt/render/project/src/deploy/seed/peptide_search.db`
   3. `DB_BOOTSTRAP_TARGET=/var/data/peptide_search.db`

Start command:

```bash
bash -lc './scripts/bootstrap_db_from_snapshot.sh && alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT'
```

Recommended provider keys for full UI visibility:

1. `GEMINI_API_KEY`
2. `OPENROUTER_API_KEY`
3. `OPENAI_API_KEY` (optional if OpenAI needed)
4. `DEEPSEEK_API_KEY` (optional if DeepSeek needed)

First-boot checks:

1. `/api/health` returns 200.
2. `/baseline` loads historical runs from persistent DB.
3. Providers appear as enabled when their API keys are present.
4. SSE updates work during a small test run.

## 10) Testing and Quality Gates

Strategy:

1. Unit tests for pure logic/helpers.
2. Integration API tests with isolated DB and deterministic queue behavior.
3. Smoke-level UI/API contract checks.
4. Queue reliability profiles: lightweight smoke gate first, then deep queue-only invariants/randomized workflows.

High-risk areas to keep covered:

1. Queue claim/recovery/lock behavior.
2. Retry and retry-with-source edge cases.
3. Baseline batch counters and recompute behavior.
4. Error envelope consistency for 400/404/validation.

Fast checks before pushing:

1. `node --check` for touched frontend JS files.
2. `alembic upgrade head` on a clean DB.
3. Targeted integration tests for changed API paths.
4. Full local reliability suite: `./scripts/test_local_reliability.sh`

Queue reliability profiles (resource-safe on macOS):

1. Smoke only (1-minute gate): `./scripts/run_queue_reliability_safe.sh smoke`
2. Deep only (deterministic + randomized queue workflows): `./scripts/run_queue_reliability_safe.sh deep`
3. Layered default (smoke then deep): `./scripts/run_queue_reliability_safe.sh all`
4. Runtime knobs:
   1. `RELIABILITY_SMOKE_TIMEOUT_SECONDS` (default `60`)
   2. `RELIABILITY_MAX_LOAD_AVG` (default `12`)
   3. `RELIABILITY_COOLDOWN_SECONDS` (default `15`)
   4. `RELIABILITY_RANDOM_SEEDS` (default `11,29,47,73,101`)
   5. `RELIABILITY_RANDOM_STEPS` (default `40`)
   6. `RELIABILITY_RANDOM_SCENARIOS` (default `50`)
   7. `RELIABILITY_RANDOM_STEP_DELAY_SECONDS` (default `0.02`, delay after each randomized step)
   8. `RELIABILITY_RANDOM_SCENARIO_COOLDOWN_SECONDS` (default `0.25`, delay between randomized scenarios)

### Reliability Report Output

You can emit a machine-readable JSON report by setting `RELIABILITY_REPORT_PATH`:

```bash
RELIABILITY_REPORT_PATH=/tmp/queue_reliability_report.json ./scripts/run_queue_reliability_safe.sh all
```

Example report fields:

```json
{
  "mode": "all",
  "smoke_status": 0,
  "deep_status": 0,
  "deep_skipped": 0,
  "started_at": "2026-02-11T19:10:40Z",
  "finished_at": "2026-02-11T19:11:12Z",
  "elapsed_seconds": 32,
  "smoke_elapsed_seconds": 2,
  "deterministic_elapsed_seconds": 12,
  "randomized_elapsed_seconds": 16,
  "timeout_occurred": false,
  "load_avg_at_deep_check": 1.52,
  "throttle_settings": {
    "cooldown_seconds": 1,
    "random_seeds": "11,29,47,73,101",
    "random_steps": 40,
    "random_scenarios": 50,
    "step_delay_seconds": 0.02,
    "scenario_cooldown_seconds": 0.25
  }
}
```

Postgres contract checks (optional, read-only):

1. Export a test DB URL:
   1. `export TEST_POSTGRES_URL='postgresql://.../peptide_search'`
2. Run gated checks:
   1. `.venv/bin/python -m unittest tests.integration.test_postgres_contracts`

## 11) Troubleshooting

No providers visible:

1. Missing provider API keys in environment.
2. Verify `/api/providers` and `enabled` flags.

Evaluation details page appears empty/stale:

1. Restart server with `./scripts/restart_server.sh`.
2. Hard refresh browser.
3. Confirm health endpoint and correct local host URL.

Local PDFs not opening:

1. Confirm mapping entry exists in `app/baseline/data/local_pdfs.json`.
2. Confirm mapped files exist on deployed/local filesystem.
3. Check baseline status text for surfaced local-PDF errors.

No data after deploy:

1. Check persistent disk mount path.
2. Confirm `DB_URL` and `DB_BOOTSTRAP_*` env vars.
3. Check bootstrap logs for restore/skip behavior.

## 12) Repository Map

Top-level directories:

1. `app/` backend runtime code.
2. `public/` frontend pages/assets.
3. `scripts/` operational scripts (restart/bootstrap/checks).
4. `tests/` unit/integration/perf harness.
5. `deploy/seed/` committed DB snapshot(s).
6. `Peptide LLM/` domain definition assets used in prompts.

## 13) Documentation Policy

1. Keep this file as the only comprehensive project guide.
2. Keep `README.md` concise and link here for full details.
3. Avoid creating new standalone planning docs unless they are temporary and explicitly archived.
4. Remaining `.md` files outside this guide are runtime/test assets:
   1. `Peptide LLM/definitions_for_llms.md` (prompt input data)
   2. `tests/perf/pdf_vs_markdown/paper.md` (perf benchmark input sample)
