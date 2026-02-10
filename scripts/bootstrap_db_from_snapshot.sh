#!/usr/bin/env bash
set -euo pipefail

BOOTSTRAP_ON_EMPTY="${DB_BOOTSTRAP_ON_EMPTY:-false}"
BOOTSTRAP_SNAPSHOT="${DB_BOOTSTRAP_SNAPSHOT:-/opt/render/project/src/deploy/seed/peptide_search.db}"
BOOTSTRAP_TARGET="${DB_BOOTSTRAP_TARGET:-/var/data/peptide_search.db}"

as_bool() {
  local raw="${1:-}"
  raw="$(echo "$raw" | tr '[:upper:]' '[:lower:]')"
  [[ "$raw" == "1" || "$raw" == "true" || "$raw" == "yes" || "$raw" == "on" ]]
}

if [[ -f "$BOOTSTRAP_TARGET" ]]; then
  echo "[bootstrap-db] Target DB already exists at $BOOTSTRAP_TARGET; skipping bootstrap."
  exit 0
fi

if ! as_bool "$BOOTSTRAP_ON_EMPTY"; then
  echo "[bootstrap-db] Target DB missing but DB_BOOTSTRAP_ON_EMPTY is disabled; skipping bootstrap."
  exit 0
fi

if [[ ! -f "$BOOTSTRAP_SNAPSHOT" ]]; then
  echo "[bootstrap-db] Snapshot not found: $BOOTSTRAP_SNAPSHOT"
  exit 1
fi

mkdir -p "$(dirname "$BOOTSTRAP_TARGET")"
tmp_target="${BOOTSTRAP_TARGET}.tmp"

rm -f "$tmp_target"
echo "[bootstrap-db] Restoring DB snapshot from $BOOTSTRAP_SNAPSHOT to $BOOTSTRAP_TARGET"
if [[ "$BOOTSTRAP_SNAPSHOT" == *.gz ]]; then
  gzip -dc "$BOOTSTRAP_SNAPSHOT" > "$tmp_target"
else
  cp "$BOOTSTRAP_SNAPSHOT" "$tmp_target"
fi

if ! command -v sqlite3 >/dev/null 2>&1; then
  echo "[bootstrap-db] sqlite3 is required for integrity check but was not found in PATH."
  rm -f "$tmp_target"
  exit 1
fi

integrity_result="$(sqlite3 "$tmp_target" 'PRAGMA integrity_check;' | tr -d '\r')"
if [[ "$integrity_result" != "ok" ]]; then
  echo "[bootstrap-db] Integrity check failed: $integrity_result"
  rm -f "$tmp_target"
  exit 1
fi

mv "$tmp_target" "$BOOTSTRAP_TARGET"
echo "[bootstrap-db] Snapshot restore complete."
