#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${1:-/etc/dlc-agent/env}"
if [ ! -f "$ENV_FILE" ]; then
  echo "missing env file: $ENV_FILE" >&2
  exit 1
fi

set -a
. "$ENV_FILE"
set +a

: "${WEDATA_PROJECT_ID:?missing WEDATA_PROJECT_ID}"
: "${DLC_AGENT_DB:=/data/dlc-agent/assets.db}"

WORK_DIR="${DLC_AGENT_SYNC_DIR:-/data/dlc-agent/sync}"
mkdir -p "$WORK_DIR"

python -m dlc_agent.sync_wedata

printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
  | DLC_AGENT_DB="$DLC_AGENT_DB" python -m dlc_agent.server >/dev/null

echo "MCP smoke test passed"
