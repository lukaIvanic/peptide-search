#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Python interpreter not found at $PYTHON_BIN"
  echo "Create the venv and install requirements first."
  exit 1
fi

cd "$ROOT_DIR"

echo "[reliability] Running unit tests..."
"$PYTHON_BIN" -m unittest discover -s tests/unit -p 'test_*.py'

echo "[reliability] Running integration tests..."
"$PYTHON_BIN" -m unittest discover -s tests/integration -p 'test_*.py'

echo "[reliability] Running quick API smoke subset..."
"$PYTHON_BIN" -m unittest discover -s tests/integration -p 'test_frontend_smoke_pages.py'
"$PYTHON_BIN" -m unittest discover -s tests/integration -p 'test_api_providers_and_models.py'
"$PYTHON_BIN" -m unittest discover -s tests/integration -p 'test_ui_api_contracts.py'

echo "[reliability] All reliability checks passed."
echo "[reliability] For low-impact queue hardening checks use: ./scripts/run_queue_reliability_safe.sh all"
