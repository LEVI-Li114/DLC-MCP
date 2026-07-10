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

Use the installer once from a normal terminal. After Codex restarts, data queries should go through the `dlc-mcp` MCP tools directly, not through shell, `curl`, or `ssh`; that avoids Codex command approval prompts during normal use.

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
| `get_table_partition_profile(table_name, partition_date)` | Return partition volume, recent partitions, and partition health. |
| `get_table_readiness(table_name, live)` | Return a governance readiness report for any table asset profile. |
| `get_table_production_status(table_name, instance_date, live)` | Return table-level production status from output tasks and latest task run instances. |
| `get_table_production_risk_detail(table_name, instance_date, live)` | Return actionable production-risk diagnosis for one table. |
| `list_table_production_risks(layer, core_level, instance_date, status, limit)` | List table-level production risks. |
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
| `get_asset_owner_profile(table_name, live)` | Return asset ownership chain and responsibility gaps. |
| `get_asset_usage_profile(table_name, live)` | Return metadata-proxy usage signals for a table asset. |
| `get_asset_lifecycle_profile(table_name, live)` | Return lifecycle status and governance evidence. |
| `get_asset_change_impact(table_name, change_type, live)` | Return bounded change impact analysis for a table asset. |
| `get_metric_definition(table_name, live)` | Explain ads/dws metric definitions from fields, lineage, and related tasks. |
| `list_quality_gaps(layer, domain, limit)` | List high-impact tables with no quality rules. |
| `get_expert_label(asset_type, asset_name)` | Return expert label for one asset. |
| `list_expert_review_queue(layer, limit)` | List high-impact unlabelled tables for expert review. |
| `list_metadata()` | List imported databases and table metadata. |
| `get_sync_health()` | Return sync health, asset counts, latest observed sync signals, and current data gaps. |
| `get_asset_coverage()` | Return asset coverage by layer for fields, lineage, quality rules, tasks, data sources, and runs. |
| `list_asset_coverage_gaps(gap_type, layer, limit)` | List tables with missing asset profile coverage, filtered by gap type or layer. |
| `get_asset_governance_issue_inventory(layer, core_level, issue_type, limit)` | Return deterministic governance issues with evidence, suspected root cause, severity, and recommended next check. |
| `get_asset_governance_daily_report(instance_date, layer, core_level)` | Return a daily governance patrol report. |
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
