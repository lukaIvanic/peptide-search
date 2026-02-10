# Local Server Runbook (tmux)

Use this when you want the app running in the background reliably.

## Session Name

`peptide-search`

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
