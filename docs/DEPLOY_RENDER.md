# Deploy to Render (Demo Environment)

This guide deploys a single-instance FastAPI service to Render with persistent SQLite storage and optional HTTP Basic access gating.

## 1. Create the Render Web Service

1. Connect this repository in Render and create a new **Web Service**.
2. Select a paid plan that supports a persistent disk.
3. Configure:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT`

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
- `QUEUE_CONCURRENCY=1`
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

## 4. Deploy and Verify

After deploy, run these checks:

1. `GET /api/health` returns `200` with valid credentials.
2. Open `/` in browser and confirm the auth challenge appears when gate is enabled.
3. Create at least one extraction run and one baseline batch.
4. Restart/redeploy service and verify data still exists (persistent disk check).
5. Confirm `/api/stream` connects with auth and live updates continue.

## 5. Demo-Day Quick Checks

1. Verify provider key is valid (no authentication failures from provider).
2. Run one small baseline batch end-to-end.
3. Confirm batch metrics (`completed`, `failed`, `total_papers`) populate in UI.
4. Validate one retry flow from failed run to queued/processed state.
5. Keep a local fallback ready:
   - `alembic upgrade head`
   - `uvicorn app.main:app --host 0.0.0.0 --port 8000`
