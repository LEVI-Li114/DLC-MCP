# DLC Agent

WeData-first data asset MCP server. User-facing MCP mode is read-only and does not require Tencent Cloud keys.

## MCP mode

Use this mode for Codex/Cursor/Claude Desktop users. The MCP server only reads the asset fact database.

Recommended shared Codex config through npm + SSH:

```bash
npx -y @baiying/dlc-agent-mcp install-codex
```

The installer writes this block to `~/.codex/config.toml`:

```toml
[mcp_servers.dlc-agent]
command = "npx"
args = ["-y", "@baiying/dlc-agent-mcp"]
type = "stdio"
```

This is the cleanest team setup: users only add the MCP command. The npm launcher defaults to:

- SSH host: `data-agent-host`
- remote dir: `/opt/dlc-agent`
- asset DB: `/data/dlc-agent/assets.db`

If your server path is different, override with env:

```toml
[mcp_servers.dlc-agent.env]
DLC_AGENT_SSH_HOST = "data-agent-host"
DLC_AGENT_REMOTE_DIR = "/opt/dlc-agent"
DLC_AGENT_DB = "/data/dlc-agent/assets.db"
```

Local Codex config without npm:

```toml
[mcp_servers.dlc-agent]
command = "python"
args = ["-m", "dlc_agent.server"]
cwd = "/Users/leve/Documents/DLC-Agent"
type = "stdio"

[mcp_servers.dlc-agent.env]
DLC_AGENT_DB = "/Users/leve/Documents/DLC-Agent/data/assets.db"
```

Shared Codex config without npm:

```toml
[mcp_servers.dlc-agent]
command = "ssh"
args = ["data-agent-host", "cd /opt/dlc-agent && DLC_AGENT_DB=/data/dlc-agent/assets.db python -m dlc_agent.server"]
type = "stdio"
```

In shared mode, Tencent Cloud keys stay on the sync server. Users do not configure AK/SK.

Ask Codex:

- `ads_customer_revenue_daily 是不是核心表？`
- `dws_customer_order_daily 有哪些字段？`
- `dws_customer_order_daily 有没有质量监控？`
- `dws_customer_order_daily 是哪个 ETL 任务产出的？`

## Local Demo

```bash
python -m dlc_agent.seed
DLC_AGENT_DB=data/assets.db python -m dlc_agent.server
```

## Server Sync Mode

Run this only on the trusted sync server.

```bash
export TENCENTCLOUD_SECRET_ID=...
export TENCENTCLOUD_SECRET_KEY=...
export TENCENTCLOUD_REGION=ap-guangzhou
python -m dlc_agent.call_wedata_api ListTasks '{"ProjectId":"your-project-id"}'
```

Import saved Tencent Cloud API responses:

```bash
python -m dlc_agent.import_wedata_api_dump \
  --tables data/wedata_tables.json \
  --tasks data/wedata_tasks.json \
  --quality-rules data/wedata_quality_rules.json \
  --db data/assets.db
```

Import a hand-written WeData snapshot:

```bash
python -m dlc_agent.import_wedata_snapshot examples/wedata_snapshot.json --db data/assets.db
```

## Tools

- `search_assets(query)`
- `get_table_profile(table_name)`
- `list_table_columns(table_name)`
- `get_quality_status(table_name)`
- `get_table_lineage(table_name)`
- `get_table_tasks(table_name)`
- `is_core_table(table_name)`

## WeData Snapshot Shape

The importer accepts:

- `tables`: table metadata plus nested `columns`
- `tasks`: ETL task metadata plus `inputs` and `outputs`
- `lineage`: optional explicit lineage edges
- `quality_rules`: quality rules bound to tables or fields

Skipped: write operations, DLC sync, and automatic quality-rule creation. Add them after WeData read-only answers are calibrated.

## Server Setup

See [deploy/server-setup.md](deploy/server-setup.md).

After `ListTasks` works, sync task metadata into the MCP asset DB:

```bash
cd /opt/dlc-agent/DLC-Agent
bash deploy/sync-wedata-once.sh
```
