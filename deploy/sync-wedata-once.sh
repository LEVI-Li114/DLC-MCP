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

WORK_DIR="${DLC_MCP_SYNC_DIR:-/data/dlc-mcp/sync}"
mkdir -p "$WORK_DIR"

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
