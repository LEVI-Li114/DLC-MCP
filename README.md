# DLC-MCP

WeData-first data asset MCP server. It lets Codex query synced WeData assets, tasks, metadata, quality rules, lineage, data sources, task runs, metric definitions, and core-table decisions.

User-facing MCP access is read-only. Tencent Cloud AK/SK stay on the trusted server; ordinary users only need the Gateway URL and token.

## User Install

```bash
DLC_MCP_GATEWAY_TOKEN=your-token npx -y @levisli/dlc-mcp install-codex
```

If the Gateway URL is not the default:

```bash
DLC_MCP_GATEWAY_URL=http://64.186.234.87:8787/mcp \
DLC_MCP_GATEWAY_TOKEN=your-token \
  npx -y @levisli/dlc-mcp install-codex
```

The installer writes this Codex config:

```toml
[mcp_servers.dlc-mcp]
command = "npx"
args = ["-y", "@levisli/dlc-mcp"]
type = "stdio"

[mcp_servers.dlc-mcp.env]
DLC_MCP_GATEWAY_URL = "http://64.186.234.87:8787/mcp"
DLC_MCP_GATEWAY_TOKEN = "your-token"
```

Then restart Codex and ask questions such as:

- `dws_360_fin_job_seat_1d_di 统计了哪些指标？`
- `ads_bill_company_1d_di 今天执行耗时是多少？`
- `dwd_call_sms_instance_bill_di 是不是核心表？`
- `tech_support 这个数据源关联了多少任务？`

## Server

Server setup, WeData credentials, sync jobs, cron, Gateway startup, and smoke tests are documented in [docs/server-mcp-wedata-flow.md](docs/server-mcp-wedata-flow.md).

Core-table and asset-value scoring are documented in [docs/core-table-model.md](docs/core-table-model.md).

Ordinary user access and token handling are documented in [docs/user-access.md](docs/user-access.md).

## Tools

Update this list whenever a new MCP tool is added.

| Tool | Answers |
| --- | --- |
| `search_assets(query)` | Search table assets by name, domain, or description. |
| `search_tasks(query, live)` | Search WeData ETL tasks by id, name, owner, or status. |
| `get_table_profile(table_name, live)` | Return metadata, columns, lineage, quality summary, related tasks, and core-table decision. |
| `list_table_columns(table_name, live)` | List table fields. |
| `get_quality_status(table_name, live)` | Show quality rules and monitoring status. |
| `get_table_lineage(table_name, live)` | Return upstream and downstream assets. |
| `get_table_tasks(table_name)` | Return ETL tasks that read from or produce a table. |
| `get_task_runs(task_id/task_name, instance_date, live)` | Return task instance start time, end time, duration, and status. |
| `list_data_sources(query, live)` | List data sources, configuration summaries, and related task counts. |
| `get_data_source(data_source_id, live)` | Return one data source, including type, owner, related task count, description, and config summary. |
| `list_data_source_tasks(data_source_id, live)` | List tasks related to one data source. |
| `get_table_risk_profile(table_name, live)` | Explain governance risk from layer, downstream dependencies, quality rules, and task runs. |
| `get_asset_value_profile(table_name, live)` | Return asset value tier and core-table decision. |
| `get_metric_definition(table_name, live)` | Explain ads/dws metric definitions from fields, lineage, and related tasks. |
| `list_quality_gaps(layer, domain, limit)` | List high-impact tables with no quality rules. |
| `get_expert_label(asset_type, asset_name)` | Return expert label for one asset. |
| `list_expert_review_queue(layer, limit)` | List high-impact unlabelled tables for expert review. |
| `list_metadata()` | List imported databases and table metadata. |
| `is_core_table(table_name)` | Explain whether a table is core and why. |

## Development

```bash
python3 -m unittest discover -s tests -v
node --check bin/dlc-mcp.js
npm pack --dry-run
```

Publish after tests pass:

```bash
NPM_TOKEN=your-npm-token bash publish-npm.sh
```
