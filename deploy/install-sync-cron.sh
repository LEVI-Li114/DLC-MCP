#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${DLC_MCP_REPO_DIR:-$(pwd)}"
ENV_FILE="${DLC_MCP_ENV_FILE:-/etc/dlc-mcp/env}"
LOG_DIR="${DLC_MCP_LOG_DIR:-/data/dlc-mcp/logs}"
CRON_TAG="# dlc-mcp-wedata-sync"

if [ ! -f "$REPO_DIR/deploy/sync-wedata-managed.sh" ]; then
  echo "missing sync script: $REPO_DIR/deploy/sync-wedata-managed.sh" >&2
  echo "run this from the DLC-MCP repo, or set DLC_MCP_REPO_DIR" >&2
  exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
  echo "missing env file: $ENV_FILE" >&2
  exit 1
fi

mkdir -p "$LOG_DIR"

CRON_CMD="cd $REPO_DIR && bash deploy/sync-wedata-managed.sh $ENV_FILE >> $LOG_DIR/sync.log 2>&1"
CRON_LINE="0 5 * * * $CRON_CMD $CRON_TAG"

(
  crontab -l 2>/dev/null | grep -v "$CRON_TAG" || true
  echo "$CRON_LINE"
) | crontab -

echo "installed crontab:"
echo "$CRON_LINE"
echo
echo "check it with:"
echo "  crontab -l | grep dlc-mcp-wedata-sync"
echo "  tail -f $LOG_DIR/sync.log"
