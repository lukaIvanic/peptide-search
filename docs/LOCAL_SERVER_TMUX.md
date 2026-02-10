# Local Server Runbook (tmux)

Use this when you want the app running in the background reliably.

## Session Name

`peptide-search`

## Quick Refresh (recommended)

Use the restart helper when changes do not appear in the app:

```bash
cd /Users/lukaivanic/projects/peptide-search
./scripts/restart_server.sh
```

This will:
- stop the current `uvicorn` process for this app (including stale PID cases),
- start a fresh one with `.env` loaded,
- wait for `/api/health` before returning.

## Manual Refresh Sequence

If you want to run it manually:

```bash
cd /Users/lukaivanic/projects/peptide-search
pkill -f ".venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000" || true
set -a; [ -f .env ] && source .env; set +a
nohup .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 >/tmp/peptide-search-server.log 2>&1 &
curl -i http://127.0.0.1:8000/api/health
```

## Start (detached)

```bash
cd /Users/lukaivanic/projects/peptide-search
tmux has-session -t peptide-search 2>/dev/null && tmux kill-session -t peptide-search || true
tmux new-session -d -s peptide-search 'cd /Users/lukaivanic/projects/peptide-search && set -a; [ -f .env ] && source .env; set +a; export LLM_PROVIDER=${LLM_PROVIDER:-mock}; .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 >> /tmp/peptide-search-server.log 2>&1'
```

## Health check

```bash
curl -i http://127.0.0.1:8000/api/health
```

## Logs

```bash
tail -f /tmp/peptide-search-server.log
```

## Attach to running session

```bash
tmux attach -t peptide-search
```

Detach without stopping: `Ctrl-b` then `d`.

## Stop

```bash
tmux kill-session -t peptide-search
```

## If startup fails because schema is behind

```bash
cd /Users/lukaivanic/projects/peptide-search
.venv/bin/alembic upgrade head
```
