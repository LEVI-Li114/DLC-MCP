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
finish_sync() {
  status=$?
  END_TS="$(date +%s)"
  echo "finished_at: $(date '+%Y-%m-%d %H:%M:%S')"
  echo "elapsed_seconds: $((END_TS - START_TS))"
  if [ "$status" -eq 0 ]; then
    echo "sync_status: ok"
  else
    echo "sync_status: failed ($status)"
  fi
  exit "$status"
}
trap finish_sync EXIT

echo "== DLC-MCP full WeData sync =="
echo "db: $DLC_MCP_DB"
echo "started_at: $(date '+%Y-%m-%d %H:%M:%S')"

export WEDATA_FULL_FACTS_SYNC_TASKS="${DLC_MCP_FULL_SYNC_TASKS:-0}"
export WEDATA_FULL_FACTS_SYNC_TASK_DETAILS="${DLC_MCP_FULL_SYNC_TASK_DETAILS:-0}"
export WEDATA_FULL_FACTS_SYNC_LINEAGE="${DLC_MCP_FULL_SYNC_LINEAGE:-0}"
export WEDATA_FULL_FACTS_SYNC_QUALITY="${DLC_MCP_FULL_SYNC_QUALITY:-0}"

echo "sync_tasks: $WEDATA_FULL_FACTS_SYNC_TASKS"
echo "sync_task_details: $WEDATA_FULL_FACTS_SYNC_TASK_DETAILS"
echo "sync_lineage: $WEDATA_FULL_FACTS_SYNC_LINEAGE"
echo "sync_quality: $WEDATA_FULL_FACTS_SYNC_QUALITY"

PYTHON_BIN="${DLC_MCP_PYTHON:-python3}"
"$PYTHON_BIN" -m dlc_mcp.sync_asset_facts "$@"
"$PYTHON_BIN" -m dlc_mcp.sync_table_fields
