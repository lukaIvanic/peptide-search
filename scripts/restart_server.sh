#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
APP_TARGET="${APP_TARGET:-app.main:app}"
LOG_FILE="${LOG_FILE:-/tmp/peptide-search-server.log}"
PID_FILE="${PID_FILE:-/tmp/peptide-search-server.pid}"
USE_RELOAD="${USE_RELOAD:-0}"
UVICORN_BIN="${UVICORN_BIN:-$ROOT_DIR/.venv/bin/uvicorn}"
USE_TMUX="${USE_TMUX:-1}"
TMUX_SESSION="${TMUX_SESSION:-peptide-search}"

if [[ ! -x "$UVICORN_BIN" ]]; then
  echo "uvicorn not found at $UVICORN_BIN"
  echo "Create the venv and install requirements first."
  exit 1
fi

collect_target_pids() {
  {
    if [[ -f "$PID_FILE" ]]; then
      tr -d '[:space:]' <"$PID_FILE" 2>/dev/null || true
      echo
    fi
    pgrep -f "uvicorn ${APP_TARGET} --host ${HOST} --port ${PORT}" || true
  } | awk '/^[0-9]+$/{ if (!seen[$1]++) print $1 }'
}

stop_existing() {
  if [[ "$USE_TMUX" == "1" ]] && command -v tmux >/dev/null 2>&1; then
    tmux has-session -t "$TMUX_SESSION" 2>/dev/null && tmux kill-session -t "$TMUX_SESSION" || true
  fi

  local pids
  pids="$(collect_target_pids | tr '\n' ' ' | xargs 2>/dev/null || true)"
  if [[ -z "$pids" ]]; then
    return 0
  fi

  echo "Stopping existing server process(es): $pids"
  kill $pids 2>/dev/null || true

  local timeout=30
  local i
  for ((i = 0; i < timeout; i++)); do
    local alive=0
    local pid
    for pid in $pids; do
      if kill -0 "$pid" 2>/dev/null; then
        alive=1
        break
      fi
    done
    [[ "$alive" -eq 0 ]] && break
    sleep 0.1
  done

  local stubborn=""
  local pid
  for pid in $pids; do
    if kill -0 "$pid" 2>/dev/null; then
      stubborn="$stubborn $pid"
    fi
  done
  stubborn="$(echo "$stubborn" | xargs 2>/dev/null || true)"
  if [[ -n "$stubborn" ]]; then
    echo "Force stopping stubborn process(es): $stubborn"
    kill -9 $stubborn 2>/dev/null || true
  fi
}

start_server() {
  local -a args=("$APP_TARGET" "--host" "$HOST" "--port" "$PORT")
  if [[ "$USE_RELOAD" == "1" ]]; then
    args+=("--reload" "--reload-delay" "0.5")
  fi

  if [[ "$USE_TMUX" == "1" ]] && command -v tmux >/dev/null 2>&1; then
    local cmd
    cmd="cd $ROOT_DIR && set -a; [ -f .env ] && source .env; set +a; $UVICORN_BIN ${args[*]} >>$LOG_FILE 2>&1"
    tmux new-session -d -s "$TMUX_SESSION" "$cmd"
    sleep 0.3
    local pid
    pid="$(pgrep -f "uvicorn ${APP_TARGET} --host ${HOST} --port ${PORT}" | tail -n 1 || true)"
    if [[ "$pid" =~ ^[0-9]+$ ]]; then
      echo "$pid" >"$PID_FILE"
    fi
    return 0
  fi

  (
    cd "$ROOT_DIR"
    set -a
    [[ -f .env ]] && source .env
    set +a
    nohup "$UVICORN_BIN" "${args[@]}" >"$LOG_FILE" 2>&1 &
    echo "$!" >"$PID_FILE"
  )
}

wait_for_health() {
  local health_url="http://${HOST}:${PORT}/api/health"
  local attempts=40
  local i
  for ((i = 0; i < attempts; i++)); do
    if curl -fsS "$health_url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.25
  done
  return 1
}

stop_existing
start_server

new_pid="$(tr -d '[:space:]' <"$PID_FILE" 2>/dev/null || true)"
if [[ ! "$new_pid" =~ ^[0-9]+$ ]] || ! kill -0 "$new_pid" 2>/dev/null; then
  echo "Server failed to start. Last log lines:"
  tail -n 80 "$LOG_FILE" 2>/dev/null || true
  exit 1
fi

if wait_for_health; then
  echo "Server restarted successfully (PID $new_pid)."
  echo "URL: http://${HOST}:${PORT}"
  echo "Log: $LOG_FILE"
else
  echo "Server started (PID $new_pid) but health check did not pass yet."
  echo "Check logs: tail -f $LOG_FILE"
  exit 1
fi
