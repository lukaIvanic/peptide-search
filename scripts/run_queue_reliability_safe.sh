#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"
MODE="${1:-all}"
RELIABILITY_REPORT_PATH="${RELIABILITY_REPORT_PATH:-}"

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
SMOKE_ELAPSED_SECONDS=0
DETERMINISTIC_ELAPSED_SECONDS=0
RANDOMIZED_ELAPSED_SECONDS=0
TIMEOUT_OCCURRED=0
LOAD_AVG_AT_DEEP_CHECK=""
LAST_COMMAND_ELAPSED_SECONDS=0
RUN_STARTED_EPOCH=0
RUN_FINISHED_EPOCH=0
RUN_STARTED_AT=""
RUN_FINISHED_AT=""
ELAPSED_SECONDS=0

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
  LAST_COMMAND_ELAPSED_SECONDS="$elapsed"
  local timed_out=0
  if [[ -s "$timeout_flag" ]]; then
    timed_out=1
  fi
  rm -f "$timeout_flag"

  if [[ "$timed_out" -eq 1 ]]; then
    TIMEOUT_OCCURRED=1
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
  local status=$?
  SMOKE_ELAPSED_SECONDS="$LAST_COMMAND_ELAPSED_SECONDS"
  return "$status"
}

run_deep() {
  local load_1m
  load_1m="$(get_one_min_load)"
  LOAD_AVG_AT_DEEP_CHECK="$load_1m"
  if ! float_leq "$load_1m" "$RELIABILITY_MAX_LOAD_AVG"; then
    echo "[queue-reliability] Deep phase skipped: load(1m)=$load_1m exceeds max=$RELIABILITY_MAX_LOAD_AVG"
    DEEP_SKIPPED=1
    return 0
  fi

  export RUN_QUEUE_RELIABILITY_DEEP=1
  echo "[queue-reliability] Deep throttle: step_delay=${RELIABILITY_RANDOM_STEP_DELAY_SECONDS}s scenario_cooldown=${RELIABILITY_RANDOM_SCENARIO_COOLDOWN_SECONDS}s"

  local deterministic_started
  deterministic_started="$(now_epoch)"
  echo "[queue-reliability] >>> deterministic queue invariant suite"
  run_throttled "$PYTHON_BIN" -m unittest discover -s tests/integration -p 'test_queue_invariants.py'
  local deterministic_status=$?
  DETERMINISTIC_ELAPSED_SECONDS=$(( $(now_epoch) - deterministic_started ))
  if [[ "$deterministic_status" -ne 0 ]]; then
    echo "[queue-reliability] <<< deterministic queue invariant suite FAILED (exit=$deterministic_status, ${DETERMINISTIC_ELAPSED_SECONDS}s)"
    return "$deterministic_status"
  fi
  echo "[queue-reliability] <<< deterministic queue invariant suite PASSED"

  sleep_cooldown

  local randomized_started
  randomized_started="$(now_epoch)"
  echo "[queue-reliability] >>> randomized queue workflow suite"
  run_throttled "$PYTHON_BIN" -m unittest discover -s tests/integration -p 'test_queue_randomized_workflows.py'
  local randomized_status=$?
  RANDOMIZED_ELAPSED_SECONDS=$(( $(now_epoch) - randomized_started ))
  if [[ "$randomized_status" -ne 0 ]]; then
    echo "[queue-reliability] <<< randomized queue workflow suite FAILED (exit=$randomized_status, ${RANDOMIZED_ELAPSED_SECONDS}s)"
    return "$randomized_status"
  fi
  echo "[queue-reliability] <<< randomized queue workflow suite PASSED"
}

write_report() {
  local report_path="$RELIABILITY_REPORT_PATH"
  if [[ -z "$report_path" ]]; then
    return 0
  fi

  mkdir -p "$(dirname "$report_path")"

  REPORT_MODE="$MODE" \
  REPORT_SMOKE_STATUS="$SMOKE_STATUS" \
  REPORT_DEEP_STATUS="$DEEP_STATUS" \
  REPORT_DEEP_SKIPPED="$DEEP_SKIPPED" \
  REPORT_STARTED_AT="$RUN_STARTED_AT" \
  REPORT_FINISHED_AT="$RUN_FINISHED_AT" \
  REPORT_ELAPSED_SECONDS="$ELAPSED_SECONDS" \
  REPORT_SMOKE_ELAPSED_SECONDS="$SMOKE_ELAPSED_SECONDS" \
  REPORT_DETERMINISTIC_ELAPSED_SECONDS="$DETERMINISTIC_ELAPSED_SECONDS" \
  REPORT_RANDOMIZED_ELAPSED_SECONDS="$RANDOMIZED_ELAPSED_SECONDS" \
  REPORT_TIMEOUT_OCCURRED="$TIMEOUT_OCCURRED" \
  REPORT_LOAD_AVG_AT_DEEP_CHECK="$LOAD_AVG_AT_DEEP_CHECK" \
  REPORT_RELIABILITY_COOLDOWN_SECONDS="$RELIABILITY_COOLDOWN_SECONDS" \
  REPORT_RELIABILITY_RANDOM_SEEDS="$RELIABILITY_RANDOM_SEEDS" \
  REPORT_RELIABILITY_RANDOM_STEPS="$RELIABILITY_RANDOM_STEPS" \
  REPORT_RELIABILITY_RANDOM_SCENARIOS="$RELIABILITY_RANDOM_SCENARIOS" \
  REPORT_RELIABILITY_RANDOM_STEP_DELAY_SECONDS="$RELIABILITY_RANDOM_STEP_DELAY_SECONDS" \
  REPORT_RELIABILITY_RANDOM_SCENARIO_COOLDOWN_SECONDS="$RELIABILITY_RANDOM_SCENARIO_COOLDOWN_SECONDS" \
  "$PYTHON_BIN" - "$report_path" <<'PY'
import json
import os
import sys


def as_int(value: str, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def as_float(value: str, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


load_raw = os.getenv("REPORT_LOAD_AVG_AT_DEEP_CHECK", "").strip()
load_value = None
if load_raw:
    try:
        load_value = float(load_raw)
    except ValueError:
        load_value = load_raw

report = {
    "mode": os.getenv("REPORT_MODE", ""),
    "smoke_status": as_int(os.getenv("REPORT_SMOKE_STATUS", "0")),
    "deep_status": as_int(os.getenv("REPORT_DEEP_STATUS", "0")),
    "deep_skipped": as_int(os.getenv("REPORT_DEEP_SKIPPED", "0")),
    "started_at": os.getenv("REPORT_STARTED_AT", ""),
    "finished_at": os.getenv("REPORT_FINISHED_AT", ""),
    "elapsed_seconds": as_int(os.getenv("REPORT_ELAPSED_SECONDS", "0")),
    "smoke_elapsed_seconds": as_int(os.getenv("REPORT_SMOKE_ELAPSED_SECONDS", "0")),
    "deterministic_elapsed_seconds": as_int(
        os.getenv("REPORT_DETERMINISTIC_ELAPSED_SECONDS", "0")
    ),
    "randomized_elapsed_seconds": as_int(
        os.getenv("REPORT_RANDOMIZED_ELAPSED_SECONDS", "0")
    ),
    "timeout_occurred": as_int(os.getenv("REPORT_TIMEOUT_OCCURRED", "0")) == 1,
    "load_avg_at_deep_check": load_value,
    "throttle_settings": {
        "cooldown_seconds": as_int(
            os.getenv("REPORT_RELIABILITY_COOLDOWN_SECONDS", "0")
        ),
        "random_seeds": os.getenv("REPORT_RELIABILITY_RANDOM_SEEDS", ""),
        "random_steps": as_int(os.getenv("REPORT_RELIABILITY_RANDOM_STEPS", "0")),
        "random_scenarios": as_int(
            os.getenv("REPORT_RELIABILITY_RANDOM_SCENARIOS", "0")
        ),
        "step_delay_seconds": as_float(
            os.getenv("REPORT_RELIABILITY_RANDOM_STEP_DELAY_SECONDS", "0")
        ),
        "scenario_cooldown_seconds": as_float(
            os.getenv("REPORT_RELIABILITY_RANDOM_SCENARIO_COOLDOWN_SECONDS", "0")
        ),
    },
}

with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump(report, handle, indent=2, sort_keys=True)
    handle.write("\n")
PY

  echo "[queue-reliability] Wrote report: $report_path"
}

RUN_STARTED_EPOCH="$(now_epoch)"
RUN_STARTED_AT="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

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

RUN_FINISHED_EPOCH="$(now_epoch)"
RUN_FINISHED_AT="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
ELAPSED_SECONDS=$(( RUN_FINISHED_EPOCH - RUN_STARTED_EPOCH ))

FINAL_STATUS=0
if [[ "$SMOKE_STATUS" -ne 0 ]]; then
  FINAL_STATUS="$SMOKE_STATUS"
elif [[ "$DEEP_STATUS" -ne 0 ]]; then
  FINAL_STATUS="$DEEP_STATUS"
fi

write_report
exit "$FINAL_STATUS"
