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
WEDATA_SYNC_INSTANCES=0
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
- saves the raw task dump to `/data/dlc-agent/sync/wedata_tasks.json`
- imports tasks into `/data/dlc-agent/assets.db`
- runs a small MCP smoke test

Expected output:

```text
synced 2415 WeData tasks into /data/dlc-agent/assets.db
saved raw task dump to /data/dlc-agent/sync/wedata_tasks.json
MCP smoke test passed
```

## 5. Optional: Sync Task Runs

After `ListTaskInstances` works for your tenant, enable run-instance sync:

```bash
sudo vi /etc/dlc-agent/env
```

```bash
WEDATA_SYNC_INSTANCES=1
WEDATA_INSTANCE_START=2026-07-01 00:00:00
WEDATA_INSTANCE_END=2026-07-01 23:59:59
```

Then rerun:

```bash
cd /opt/dlc-agent/DLC-Agent
bash deploy/sync-wedata-once.sh
```

This populates task start time, end time, duration, and status for `get_task_runs(task_id)`.

## 6. Smoke Test MCP On Server

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

## 7. Smoke Test MCP From A User Laptop

The user laptop must be able to SSH to the server.

```bash
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
  | ssh data-agent-host 'cd /opt/dlc-agent/DLC-Agent && DLC_AGENT_DB=/data/dlc-agent/assets.db python3 -m dlc_agent.server'
```

If this returns MCP tools, Codex can use the server.

## 8. Connect Codex

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

## 9. Current Supported Real Data

- Real WeData task list: supported through `ListTasks`
- Task search: supported through `search_tasks(query)`
- Task run start/end/duration/status: supported after optional `ListTaskInstances` sync
- Data source listing and configuration lookup: local model and JSON import supported; live sync still needs follow-up work
- Metadata database/table listing: local model and JSON import supported; live metadata sync still needs follow-up work
- Table fields, quality rules, lineage: local model exists, real WeData sync still needs follow-up work

## 10. Routine Refresh

Run whenever you want to refresh data:

```bash
cd /opt/dlc-agent/DLC-Agent
git pull
bash deploy/sync-wedata-once.sh
```
