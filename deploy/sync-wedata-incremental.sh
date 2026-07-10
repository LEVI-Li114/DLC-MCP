#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${1:-/etc/dlc-mcp/env}"
if [ ! -f "$ENV_FILE" ]; then
  echo "missing env file: $ENV_FILE" >&2
  exit 1
fi

set -a
. "$ENV_FILE"
set +a

: "${WEDATA_PROJECT_ID:?missing WEDATA_PROJECT_ID}"
: "${DLC_MCP_DB:=/data/dlc-mcp/assets.db}"

TODAY="${DLC_MCP_SYNC_TODAY:-$(date +%Y-%m-%d)}"
YESTERDAY="$(date -d "$TODAY -1 day" +%Y-%m-%d)"

export WEDATA_SYNC_TABLE_CATALOG="${DLC_MCP_DAILY_SYNC_TABLE_CATALOG:-1}"
export WEDATA_SYNC_METADATA="${DLC_MCP_DAILY_SYNC_METADATA:-1}"
export WEDATA_NEW_ASSET_START="${YESTERDAY}"
export WEDATA_NEW_ASSET_END="${YESTERDAY}"
export WEDATA_NEW_ASSET_STRICT="${DLC_MCP_DAILY_NEW_ASSET_STRICT:-1}"
export WEDATA_METADATA_TABLE_LIMIT="${DLC_MCP_DAILY_METADATA_TABLE_LIMIT:-100000}"
export WEDATA_SYNC_DATA_SOURCES="${DLC_MCP_DAILY_SYNC_DATA_SOURCES:-1}"
export WEDATA_SYNC_INSTANCES="${DLC_MCP_DAILY_SYNC_INSTANCES:-1}"
export WEDATA_SYNC_PARTITIONS="${DLC_MCP_DAILY_SYNC_PARTITIONS:-1}"
export WEDATA_PARTITION_DATE="$YESTERDAY"
export WEDATA_INSTANCE_START="${YESTERDAY} 00:00:00"
export WEDATA_INSTANCE_END="${YESTERDAY} 23:59:59"
export WEDATA_INSTANCE_KEYWORDS="${DLC_MCP_DAILY_INSTANCE_KEYWORDS:-}"

echo "== DLC-MCP daily incremental sync for $YESTERDAY =="

PYTHON_BIN="${DLC_MCP_PYTHON:-python3}"
"$PYTHON_BIN" -m dlc_mcp.sync_wedata

printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
  | DLC_MCP_DB="$DLC_MCP_DB" "$PYTHON_BIN" -m dlc_mcp.server >/dev/null

echo "MCP smoke test passed"

if [ "${DLC_MCP_SYNC_HEALTH_CHECK:-1}" = "1" ]; then
  echo
  echo "== Asset foundation check =="
  GAP_LIMIT="${DLC_MCP_SYNC_GAP_LIMIT:-20}"
  GAP_TYPES="${DLC_MCP_SYNC_GAP_TYPES:-fields,lineage,quality,tasks,runs,data_source}"
  "$PYTHON_BIN" -m dlc_mcp.check_foundation \
    --db "$DLC_MCP_DB" \
    --gap-types "$GAP_TYPES" \
    --gap-limit "$GAP_LIMIT"
fi
