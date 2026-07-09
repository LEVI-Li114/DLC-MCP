#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${1:-${DLC_MCP_ENV_FILE:-/etc/dlc-mcp/env}}"
if [ -f "$ENV_FILE" ]; then
  set -a
  . "$ENV_FILE"
  set +a
elif [ "${1:-}" != "" ]; then
  echo "missing env file: $ENV_FILE" >&2
  exit 1
fi

: "${DLC_MCP_DB:=/data/dlc-mcp/assets.db}"
PYTHON_BIN="${DLC_MCP_PYTHON:-python3}"
GAP_LIMIT="${DLC_MCP_SYNC_GAP_LIMIT:-20}"
GAP_TYPES="${DLC_MCP_SYNC_GAP_TYPES:-fields,lineage,quality,tasks,runs,data_source}"

"$PYTHON_BIN" -m dlc_mcp.check_foundation \
  --db "$DLC_MCP_DB" \
  --gap-types "$GAP_TYPES" \
  --gap-limit "$GAP_LIMIT"
