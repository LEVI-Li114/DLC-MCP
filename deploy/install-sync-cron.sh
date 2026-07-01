#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${DLC_AGENT_REPO_DIR:-$(pwd)}"
ENV_FILE="${DLC_AGENT_ENV_FILE:-/etc/dlc-agent/env}"
LOG_DIR="${DLC_AGENT_LOG_DIR:-/data/dlc-agent/logs}"
CRON_TAG="# dlc-agent-wedata-sync"

if [ ! -f "$REPO_DIR/deploy/sync-wedata-once.sh" ]; then
  echo "missing sync script: $REPO_DIR/deploy/sync-wedata-once.sh" >&2
  echo "run this from the DLC-Agent repo, or set DLC_AGENT_REPO_DIR" >&2
  exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
  echo "missing env file: $ENV_FILE" >&2
  exit 1
fi

mkdir -p "$LOG_DIR"

CRON_CMD="cd $REPO_DIR && bash deploy/sync-wedata-once.sh $ENV_FILE >> $LOG_DIR/sync.log 2>&1"
CRON_LINE="*/10 * * * * $CRON_CMD $CRON_TAG"

(
  crontab -l 2>/dev/null | grep -v "$CRON_TAG" || true
  echo "$CRON_LINE"
) | crontab -

echo "installed crontab:"
echo "$CRON_LINE"
echo
echo "check it with:"
echo "  crontab -l | grep dlc-agent-wedata-sync"
echo "  tail -f $LOG_DIR/sync.log"
