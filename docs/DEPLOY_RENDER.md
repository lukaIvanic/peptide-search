# Deploy to Render (Demo Environment)

This guide deploys a single-instance FastAPI service to Render with persistent SQLite storage, optional HTTP Basic access gating, and one-time DB bootstrap from a committed snapshot.

## 1. Create the Render Web Service

1. Connect this repository in Render and create a new **Web Service**.
2. Select a paid plan that supports a persistent disk.
3. Configure:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `bash -lc './scripts/bootstrap_db_from_snapshot.sh && python3 ./scripts/check_local_pdf_mapping.py --limit 20 && alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT'`

## 2. Attach Persistent Disk

1. Add a persistent disk.
2. Mount Path: `/var/data`
3. Set database URL to the mounted path:
   - `DB_URL=sqlite:////var/data/peptide_search.db`

## 3. Configure Environment Variables

Set these in Render:

- `LLM_PROVIDER` (`mock`, `openai`, `openai-full`, `openai-mini`, `openai-nano`, `deepseek`)
- Provider key:
  - `OPENAI_API_KEY` when using OpenAI variants
  - `DEEPSEEK_API_KEY` when using DeepSeek
- `DB_URL=sqlite:////var/data/peptide_search.db`
- `DB_BOOTSTRAP_ON_EMPTY=true`
- `DB_BOOTSTRAP_SNAPSHOT=/opt/render/project/src/deploy/seed/peptide_search.db`
- `DB_BOOTSTRAP_TARGET=/var/data/peptide_search.db`
- `QUEUE_CONCURRENCY=128`
- `QUEUE_CLAIM_TIMEOUT_SECONDS=300`
- `QUEUE_MAX_ATTEMPTS=3`
- `QUEUE_ENGINE_VERSION=v2`
- `CORS_ORIGINS=https://<your-render-service>.onrender.com`

Access gate (recommended for demo/judges):

- `ACCESS_GATE_ENABLED=true`
- `ACCESS_GATE_USERNAME=<shared-user>`
- `ACCESS_GATE_PASSWORD=<shared-pass>`

If the gate causes issues, temporary rollback:

- `ACCESS_GATE_ENABLED=false`

## 4. Bootstrap Snapshot Notes

- Snapshot file path in repo: `deploy/seed/peptide_search.db` (or `.gz`, both supported)
- Bootstrap script: `scripts/bootstrap_db_from_snapshot.sh`
- Behavior:
  - If `/var/data/peptide_search.db` already exists, bootstrap is skipped.
  - If DB is missing and `DB_BOOTSTRAP_ON_EMPTY=true`, snapshot is restored.
  - `sqlite3 PRAGMA integrity_check` runs before finalizing restore.

Local PDF mapping diagnostics:

- The startup command runs `scripts/check_local_pdf_mapping.py`.
- Missing mapped files are **warnings only** (non-blocking), so deploy does not fail.
- API behavior for missing local files remains graceful (`found=false` or 404 without app crash).

## 5. Deploy and Verify

After deploy, run these checks:

1. `GET /api/health` returns `200` with valid credentials.
2. Open `/` in browser and confirm the auth challenge appears when gate is enabled.
3. Create at least one extraction run and one baseline batch.
4. Restart/redeploy service and verify data still exists (persistent disk check).
5. Confirm `/api/stream` connects with auth and live updates continue.

Note: `/api/health` remains intentionally public so Render health checks can pass when the access gate is enabled.

## 6. Demo-Day Quick Checks

1. Verify provider key is valid (no authentication failures from provider).
2. Run one small baseline batch end-to-end.
3. Confirm batch metrics (`completed`, `failed`, `total_papers`) populate in UI.
4. Validate one retry flow from failed run to queued/processed state.
5. Keep a local fallback ready:
   - `alembic upgrade head`
   - `uvicorn app.main:app --host 0.0.0.0 --port 8000`
