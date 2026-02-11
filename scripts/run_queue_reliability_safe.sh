#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"
MODE="${1:-all}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "[queue-reliability] Python interpreter not found at $PYTHON_BIN"
  echo "[queue-reliability] Create the venv and install requirements first."
  exit 1
fi

case "$MODE" in
  smoke|deep|all) ;;
  *)
    echo "Usage: $0 [smoke|deep|all]"
    exit 2
    ;;
esac

export RELIABILITY_SMOKE_TIMEOUT_SECONDS="${RELIABILITY_SMOKE_TIMEOUT_SECONDS:-60}"
export RELIABILITY_MAX_LOAD_AVG="${RELIABILITY_MAX_LOAD_AVG:-12}"
export RELIABILITY_COOLDOWN_SECONDS="${RELIABILITY_COOLDOWN_SECONDS:-15}"
export RELIABILITY_RANDOM_SEEDS="${RELIABILITY_RANDOM_SEEDS:-11,29,47,73,101}"
export RELIABILITY_RANDOM_STEPS="${RELIABILITY_RANDOM_STEPS:-40}"
export RELIABILITY_RANDOM_SCENARIOS="${RELIABILITY_RANDOM_SCENARIOS:-50}"
export RELIABILITY_RANDOM_STEP_DELAY_SECONDS="${RELIABILITY_RANDOM_STEP_DELAY_SECONDS:-0.02}"
export RELIABILITY_RANDOM_SCENARIO_COOLDOWN_SECONDS="${RELIABILITY_RANDOM_SCENARIO_COOLDOWN_SECONDS:-0.25}"

cd "$ROOT_DIR"

SMOKE_STATUS=0
DEEP_STATUS=0
DEEP_SKIPPED=0

now_epoch() {
  date +%s
}

get_one_min_load() {
  sysctl -n vm.loadavg | awk '{print $2}'
}

float_leq() {
  local lhs="$1"
  local rhs="$2"
  "$PYTHON_BIN" - "$lhs" "$rhs" <<'PY'
import sys
lhs = float(sys.argv[1])
rhs = float(sys.argv[2])
sys.exit(0 if lhs <= rhs else 1)
PY
}

sleep_cooldown() {
  local seconds="$RELIABILITY_COOLDOWN_SECONDS"
  if [[ "$seconds" -gt 0 ]]; then
    echo "[queue-reliability] Cooling down for ${seconds}s..."
    sleep "$seconds"
  fi
}

run_throttled() {
  taskpolicy -c utility nice -n 20 "$@"
}

run_with_timeout() {
  local timeout_s="$1"
  local label="$2"
  shift 2

  local started
  started="$(now_epoch)"
  local timeout_flag
  timeout_flag="$(mktemp -t queue_reliability_timeout)"
  rm -f "$timeout_flag"

  echo "[queue-reliability] >>> $label"

  set +e
  run_throttled "$@" &
  local cmd_pid=$!
  local cmd_pgid
  cmd_pgid="$(ps -o pgid= -p "$cmd_pid" | tr -d ' ')"

  (
    sleep "$timeout_s"
    if kill -0 "$cmd_pid" 2>/dev/null; then
      echo "1" > "$timeout_flag"
      if [[ -n "$cmd_pgid" ]]; then
        kill -TERM -- "-$cmd_pgid" 2>/dev/null || kill -TERM "$cmd_pid" 2>/dev/null || true
      else
        kill -TERM "$cmd_pid" 2>/dev/null || true
      fi
      sleep 2
      if kill -0 "$cmd_pid" 2>/dev/null; then
        if [[ -n "$cmd_pgid" ]]; then
          kill -KILL -- "-$cmd_pgid" 2>/dev/null || kill -KILL "$cmd_pid" 2>/dev/null || true
        else
          kill -KILL "$cmd_pid" 2>/dev/null || true
        fi
      fi
    fi
  ) &
  local watchdog_pid=$!

  wait "$cmd_pid"
  local status=$?

  kill "$watchdog_pid" 2>/dev/null || true
  wait "$watchdog_pid" 2>/dev/null || true
  set -e

  local elapsed=$(( $(now_epoch) - started ))
  local timed_out=0
  if [[ -s "$timeout_flag" ]]; then
    timed_out=1
  fi
  rm -f "$timeout_flag"

  if [[ "$timed_out" -eq 1 ]]; then
    echo "[queue-reliability] <<< $label TIMED OUT after ${elapsed}s"
    return 124
  fi

  if [[ "$status" -ne 0 ]]; then
    echo "[queue-reliability] <<< $label FAILED (exit=$status, ${elapsed}s)"
    return "$status"
  fi

  echo "[queue-reliability] <<< $label PASSED (${elapsed}s)"
  return 0
}

run_smoke() {
  run_with_timeout \
    "$RELIABILITY_SMOKE_TIMEOUT_SECONDS" \
    "queue reliability smoke" \
    "$PYTHON_BIN" -m unittest discover -s tests/integration -p 'test_queue_reliability_smoke.py'
}

run_deep() {
  local load_1m
  load_1m="$(get_one_min_load)"
  if ! float_leq "$load_1m" "$RELIABILITY_MAX_LOAD_AVG"; then
    echo "[queue-reliability] Deep phase skipped: load(1m)=$load_1m exceeds max=$RELIABILITY_MAX_LOAD_AVG"
    DEEP_SKIPPED=1
    return 0
  fi

  export RUN_QUEUE_RELIABILITY_DEEP=1
  echo "[queue-reliability] Deep throttle: step_delay=${RELIABILITY_RANDOM_STEP_DELAY_SECONDS}s scenario_cooldown=${RELIABILITY_RANDOM_SCENARIO_COOLDOWN_SECONDS}s"

  echo "[queue-reliability] >>> deterministic queue invariant suite"
  run_throttled "$PYTHON_BIN" -m unittest discover -s tests/integration -p 'test_queue_invariants.py'
  echo "[queue-reliability] <<< deterministic queue invariant suite PASSED"

  sleep_cooldown

  echo "[queue-reliability] >>> randomized queue workflow suite"
  run_throttled "$PYTHON_BIN" -m unittest discover -s tests/integration -p 'test_queue_randomized_workflows.py'
  echo "[queue-reliability] <<< randomized queue workflow suite PASSED"
}

if [[ "$MODE" == "smoke" ]]; then
  set +e
  run_smoke
  SMOKE_STATUS=$?
  set -e
elif [[ "$MODE" == "deep" ]]; then
  set +e
  run_deep
  DEEP_STATUS=$?
  set -e
else
  set +e
  run_smoke
  SMOKE_STATUS=$?
  set -e

  if [[ "$SMOKE_STATUS" -eq 0 ]]; then
    sleep_cooldown
    set +e
    run_deep
    DEEP_STATUS=$?
    set -e
  else
    echo "[queue-reliability] Deep phase skipped because smoke failed (exit=$SMOKE_STATUS)."
    DEEP_SKIPPED=1
  fi
fi

echo "[queue-reliability] Summary: mode=$MODE smoke_status=$SMOKE_STATUS deep_status=$DEEP_STATUS deep_skipped=$DEEP_SKIPPED"

if [[ "$SMOKE_STATUS" -ne 0 ]]; then
  exit "$SMOKE_STATUS"
fi
if [[ "$DEEP_STATUS" -ne 0 ]]; then
  exit "$DEEP_STATUS"
fi
exit 0
