#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${1:-/etc/dlc-mcp/env}"
if [ "$#" -gt 0 ]; then
  shift
fi
if [ ! -f "$ENV_FILE" ]; then
  echo "missing env file: $ENV_FILE" >&2
  exit 1
fi

set -a
. "$ENV_FILE"
set +a

: "${WEDATA_PROJECT_ID:?missing WEDATA_PROJECT_ID}"
: "${DLC_MCP_DB:=/data/dlc-mcp/assets.db}"

START_TS="$(date +%s)"
echo "== DLC-MCP full WeData sync =="
echo "db: $DLC_MCP_DB"
echo "started_at: $(date '+%Y-%m-%d %H:%M:%S')"

PYTHON_BIN="${DLC_MCP_PYTHON:-python3}"
"$PYTHON_BIN" -m dlc_mcp.sync_asset_facts "$@"
"$PYTHON_BIN" -m dlc_mcp.sync_table_fields

END_TS="$(date +%s)"
echo "finished_at: $(date '+%Y-%m-%d %H:%M:%S')"
echo "elapsed_seconds: $((END_TS - START_TS))"
