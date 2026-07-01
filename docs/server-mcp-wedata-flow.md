# Server MCP + Real WeData Flow

This document is the end-to-end runbook for running the MCP service on a server and querying real WeData data from Codex.

## Target Layout

```text
/opt/dlc-agent/DLC-Agent       repo checkout
/data/dlc-agent/assets.db      SQLite asset database used by MCP
/data/dlc-agent/sync/          raw WeData JSON dumps
/etc/dlc-agent/env             server-only Tencent Cloud credentials and sync config
```

Tencent Cloud AK/SK must stay on the server. Do not put them in GitHub, npm, Codex config, or user laptops.

## 1. Install Code On Server

```bash
sudo mkdir -p /opt/dlc-agent /data/dlc-agent /etc/dlc-agent
sudo chown -R "$USER":"$USER" /opt/dlc-agent /data/dlc-agent

cd /opt/dlc-agent
git clone https://github.com/LEVI-Li114/DLC-Agent.git
cd /opt/dlc-agent/DLC-Agent

python3 -m unittest discover -s tests -v
```

## 2. Configure WeData Credentials

```bash
sudo cp /opt/dlc-agent/DLC-Agent/deploy/env.example /etc/dlc-agent/env
sudo chmod 600 /etc/dlc-agent/env
sudo vi /etc/dlc-agent/env
```

Fill in real values:

```bash
TENCENTCLOUD_SECRET_ID=your-secret-id
TENCENTCLOUD_SECRET_KEY=your-secret-key
TENCENTCLOUD_REGION=ap-guangzhou
WEDATA_VERSION=2025-08-06
WEDATA_PROJECT_ID=2881307738992685056
DLC_AGENT_DB=/data/dlc-agent/assets.db
WEDATA_SYNC_METADATA=0
WEDATA_METADATA_TABLE_LIMIT=50
WEDATA_METADATA_TABLES=
WEDATA_SYNC_INSTANCES=0
WEDATA_INSTANCE_LOOKBACK_DAYS=2
WEDATA_INSTANCE_START=
WEDATA_INSTANCE_END=
```

Use the numeric WeData project id, not the project name.

## 3. Verify WeData API Access

```bash
cd /opt/dlc-agent/DLC-Agent

set -a
. /etc/dlc-agent/env
set +a

python3 -m dlc_agent.call_wedata_api ListTasks "{\"ProjectId\":\"$WEDATA_PROJECT_ID\",\"PageNumber\":1,\"PageSize\":10}"
```

Success means the response contains `Response.Data.Items`.

## 4. Sync Real WeData Tasks Into MCP Database

```bash
cd /opt/dlc-agent/DLC-Agent
bash deploy/sync-wedata-once.sh
```

The script:

- loads `/etc/dlc-agent/env`
- calls `ListTasks` with pagination
- optionally calls `ListTable`, `GetTableColumns`, `ListLineage`, and `ListQualityRules`
- saves the raw task dump to `/data/dlc-agent/sync/wedata_tasks.json`
- imports tasks into `/data/dlc-agent/assets.db`
- runs a small MCP smoke test

Expected output:

```text
synced 2415 WeData tasks into /data/dlc-agent/assets.db
saved raw task dump to /data/dlc-agent/sync/wedata_tasks.json
MCP smoke test passed
```

## 5. Optional: Sync Real Table Metadata

Enable this when you want real fields, downstream lineage, and quality rules:

```bash
cd /opt/dlc-agent/DLC-Agent
WEDATA_SYNC_METADATA=1 WEDATA_METADATA_TABLE_LIMIT=50 bash deploy/sync-wedata-once.sh
```

For a small targeted run:

```bash
WEDATA_SYNC_METADATA=1 WEDATA_METADATA_TABLES=ads_bill_company_1d_di,dws_360_fin_job_seat_1d_di bash deploy/sync-wedata-once.sh
```

This uses:

- `ListTable` to resolve table GUID, database, owner, description
- `GetTableColumns` to sync real fields
- `ListLineage` to sync downstream lineage
- `ListQualityRules` to sync quality monitoring rules

The metadata table limit keeps the sync small enough for manual runs. Increase it after the first run is stable.

## 6. Optional: Sync Task Runs

After `ListTaskInstances` works for your tenant, enable run-instance sync:

```bash
sudo vi /etc/dlc-agent/env
```

```bash
WEDATA_SYNC_INSTANCES=1
WEDATA_INSTANCE_LOOKBACK_DAYS=2
WEDATA_INSTANCE_START=2026-07-01 00:00:00
WEDATA_INSTANCE_END=2026-07-01 23:59:59
```

Then rerun:

```bash
cd /opt/dlc-agent/DLC-Agent
bash deploy/sync-wedata-once.sh
```

This populates task start time, end time, duration, and status for `get_task_runs(task_id)`.

If `WEDATA_INSTANCE_START` and `WEDATA_INSTANCE_END` are empty, the sync uses a rolling window. With `WEDATA_INSTANCE_LOOKBACK_DAYS=2`, every cron run syncs yesterday and today.

## 7. Smoke Test MCP On Server

List tools:

```bash
cd /opt/dlc-agent/DLC-Agent

printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
  | DLC_AGENT_DB=/data/dlc-agent/assets.db python3 -m dlc_agent.server
```

Search real synced tasks:

```bash
printf '%s\n' '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"search_tasks","arguments":{"query":"dws_360_fin_job_seat_1d_di"}}}' \
  | DLC_AGENT_DB=/data/dlc-agent/assets.db python3 -m dlc_agent.server
```

Get task runs:

```bash
printf '%s\n' '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"get_task_runs","arguments":{"task_id":"20250808125438221","limit":5}}}' \
  | DLC_AGENT_DB=/data/dlc-agent/assets.db python3 -m dlc_agent.server
```

## 8. Smoke Test MCP From A User Laptop

The user laptop must be able to SSH to the server.

```bash
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
  | ssh data-agent-host 'cd /opt/dlc-agent/DLC-Agent && DLC_AGENT_DB=/data/dlc-agent/assets.db python3 -m dlc_agent.server'
```

If this returns MCP tools, Codex can use the server.

## 9. Connect Codex

Before the npm package is published, add this to `~/.codex/config.toml`:

```toml
[mcp_servers.dlc-agent]
command = "ssh"
args = ["data-agent-host", "cd /opt/dlc-agent/DLC-Agent && DLC_AGENT_DB=/data/dlc-agent/assets.db python3 -m dlc_agent.server"]
type = "stdio"
```

After the npm package is published, users can run:

```bash
npx -y @baiying/dlc-agent-mcp install-codex
```

Restart Codex, then ask:

```text
用 dlc-agent 搜索任务 dws_360_fin_job_seat_1d_di
```

## 10. Current Supported Real Data

- Real WeData task list: supported through `ListTasks`
- Task search: supported through `search_tasks(query)`
- Task run start/end/duration/status: supported after optional `ListTaskInstances` sync
- Table metadata and fields: supported through optional `ListTable` and `GetTableColumns` sync
- Downstream lineage: supported through optional `ListLineage` sync
- Quality rules: supported through optional `ListQualityRules` sync
- Data source listing and configuration lookup: local model and JSON import supported; live sync still needs follow-up work
- Metadata database/table listing: supported after optional metadata sync
- Usage heat: not supported yet; needs query logs or BI/report access logs

## 11. Routine Refresh

Run whenever you want to refresh data:

```bash
cd /opt/dlc-agent/DLC-Agent
git pull
bash deploy/sync-wedata-once.sh
```

Install automatic refresh every 10 minutes:

```bash
cd /opt/dlc-agent/DLC-Agent
bash deploy/install-sync-cron.sh
```

The installer writes one idempotent crontab entry:

```cron
*/10 * * * * cd /opt/dlc-agent/DLC-Agent && bash deploy/sync-wedata-once.sh /etc/dlc-agent/env >> /data/dlc-agent/logs/sync.log 2>&1 # dlc-agent-wedata-sync
```

Verify the schedule and logs:

```bash
crontab -l | grep dlc-agent-wedata-sync
tail -f /data/dlc-agent/logs/sync.log
```

If `/data/dlc-agent/logs` has no write permission:

```bash
sudo mkdir -p /data/dlc-agent/logs
sudo chown -R "$USER":"$USER" /data/dlc-agent/logs
```

After this, if WeData adds a new task, wait up to 10 minutes or run `bash deploy/sync-wedata-once.sh` manually, then ask MCP through `search_tasks(query)`.
