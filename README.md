# DLC-MCP

WeData-first data asset MCP server. User-facing MCP mode is read-only and does not require Tencent Cloud keys.

## MCP mode

Use this mode for Codex/Cursor/Claude Desktop users. The MCP server only reads the asset fact database.

Recommended shared Codex config through npm + SSH:

```bash
npx -y @baiying/dlc-mcp install-codex
```

The installer writes this block to `~/.codex/config.toml`:

```toml
[mcp_servers.dlc-mcp]
command = "npx"
args = ["-y", "@baiying/dlc-mcp"]
type = "stdio"
```

This is the cleanest team setup: users only add the MCP command. The npm launcher defaults to:

- SSH host: `data-agent-host`
- remote dir: `/opt/dlc-mcp`
- asset DB: `/data/dlc-mcp/assets.db`

If your server path is different, override with env:

```toml
[mcp_servers.dlc-mcp.env]
DLC_MCP_SSH_HOST = "data-agent-host"
DLC_MCP_REMOTE_DIR = "/opt/dlc-mcp"
DLC_MCP_DB = "/data/dlc-mcp/assets.db"
```

Local Codex config without npm:

```toml
[mcp_servers.dlc-mcp]
command = "python3"
args = ["-m", "dlc_mcp.server"]
cwd = "/Users/leve/Documents/DLC-MCP"
type = "stdio"

[mcp_servers.dlc-mcp.env]
DLC_MCP_DB = "/Users/leve/Documents/DLC-MCP/data/assets.db"
```

Shared Codex config without npm:

```toml
[mcp_servers.dlc-mcp]
command = "ssh"
args = ["data-agent-host", "cd /opt/dlc-mcp && DLC_MCP_DB=/data/dlc-mcp/assets.db python3 -m dlc_mcp.server"]
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
python3 -m dlc_mcp.seed
DLC_MCP_DB=data/assets.db python3 -m dlc_mcp.server
```

## Server Sync Mode

Run this only on the trusted sync server.

```bash
export TENCENTCLOUD_SECRET_ID=...
export TENCENTCLOUD_SECRET_KEY=...
export TENCENTCLOUD_REGION=ap-guangzhou
python3 -m dlc_mcp.call_wedata_api ListTasks '{"ProjectId":"your-project-id"}'
```

Import saved Tencent Cloud API responses:

```bash
python3 -m dlc_mcp.import_wedata_api_dump \
  --tables data/wedata_tables.json \
  --tasks data/wedata_tasks.json \
  --quality-rules data/wedata_quality_rules.json \
  --db data/assets.db
```

Import a hand-written WeData snapshot:

```bash
python3 -m dlc_mcp.import_wedata_snapshot examples/wedata_snapshot.json --db data/assets.db
```

## MCP Tools

Update this section whenever a new MCP tool is added.

## 功能目录

- 项目管理：规划中。用于同步项目、项目成员、项目角色。
- 资源组：规划中。用于同步资源组及资源组监控。
- 数据开发：已部分支持。当前支持任务列表同步、任务搜索、任务产出表派生、任务输入输出映射。
- 数据资产-数据字典：已部分支持。当前支持真实表资产、层级、字段、质量状态、核心表判断。
- 运维中心：已部分支持。当前支持任务运行实例的开始时间、结束时间、耗时、状态。
- 数据探索：规划中。用于同步 SQL 脚本、代码文件、运行记录。
- Studio：规划中。用于同步 Studio 相关代码和权限信息。
- 数据安全：规划中。用于同步权限、授权主体、资源访问范围。
- 数据质量：已部分支持。当前支持真实质量规则同步和查询；规则执行结果同步待接入。
- 平台管理：规划中。用于同步平台级配置。
- 数据源管理：已部分支持。当前支持数据源列表、数据源类型、负责人、描述和配置摘要的导入与查询。
- 元数据：已部分支持。当前支持真实表资产、字段、下游血缘同步和查询。

| Tool | What it answers | Current data source |
| --- | --- | --- |
| `search_assets(query)` | Search table assets by name, domain, or description. | Imported table metadata |
| `search_tasks(query)` | Search WeData ETL tasks by task id, task name, owner, or status. | `ListTasks` sync |
| `get_table_profile(table_name)` | Return one table's metadata, columns, lineage, quality summary, related tasks, and core-table decision. | Imported table/column/lineage/quality/task data |
| `list_table_columns(table_name)` | List fields for a table. | `GetTableColumns` metadata sync |
| `get_quality_status(table_name)` | Show whether a table has quality monitoring, rule count, latest status, and rule details. | `ListQualityRules` sync |
| `get_table_lineage(table_name)` | Return upstream and downstream assets for a table. | `ListLineage` sync and task input/output data |
| `get_table_tasks(table_name)` | Return ETL tasks that read from or produce a table. | Task input/output mapping |
| `get_task_runs(task_id/task_name, instance_date)` | Return task instances, including start time, end time, duration, and status. | Optional `ListTaskInstances` sync |
| `list_data_sources(query)` | List data sources and stored configuration summaries. | Imported data source metadata |
| `get_data_source(data_source_id)` | Return one data source, including type, owner, description, and stored config. | Imported data source metadata |
| `list_metadata()` | List imported databases and table metadata. | Imported metadata tables |
| `is_core_table(table_name)` | Explain whether a table is core and return score plus reasons. | Local scoring model over layer/domain/lineage/quality/manual marks |

Current limitation: usage heat is not synced yet. It needs query logs or BI/report access logs, not the current WeData metadata APIs.

## WeData Snapshot Shape

The importer accepts:

- `tables`: table metadata plus nested `columns`
- `tasks`: ETL task metadata plus `inputs` and `outputs`
- `lineage`: optional explicit lineage edges
- `quality_rules`: quality rules bound to tables or fields

Skipped: write operations, DLC sync, and automatic quality-rule creation. Add them after WeData read-only answers are calibrated.

## Server Setup

See [deploy/server-setup.md](deploy/server-setup.md).
End-to-end server MCP and real WeData flow: [docs/server-mcp-wedata-flow.md](docs/server-mcp-wedata-flow.md).
Core table scoring is documented in [docs/core-table-model.md](docs/core-table-model.md).

After `ListTasks` works, sync task metadata into the MCP asset DB:

```bash
cd /opt/dlc-mcp/DLC-MCP
bash deploy/sync-wedata-once.sh
```

Sync real table metadata, fields, downstream lineage, and quality rules:

```bash
WEDATA_SYNC_METADATA=1 WEDATA_METADATA_TABLE_LIMIT=50 bash deploy/sync-wedata-once.sh
```

Sync only selected tables:

```bash
WEDATA_SYNC_METADATA=1 WEDATA_METADATA_TABLES=ads_bill_company_1d_di,dws_360_fin_job_seat_1d_di bash deploy/sync-wedata-once.sh
```

Sync rolling task runs for yesterday and today:

```bash
WEDATA_SYNC_INSTANCES=1 WEDATA_INSTANCE_LOOKBACK_DAYS=2 WEDATA_INSTANCE_KEYWORDS=ads_bill_company_1d_di bash deploy/sync-wedata-once.sh
```

Install a server crontab to sync every 6 hours:

```bash
cd /opt/dlc-mcp/DLC-MCP
bash deploy/install-sync-cron.sh
```
