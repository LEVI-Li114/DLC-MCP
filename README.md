# DLC-MCP

WeData-first data asset MCP server. It lets Codex query synced WeData assets, tasks, metadata, quality rules, lineage, data sources, task runs, metric definitions, and core-table decisions.

User-facing MCP access is read-only. Tencent Cloud AK/SK stay on the trusted server; ordinary users only need the Gateway URL and token.

## User Install

```bash
DLC_MCP_GATEWAY_TOKEN=your-token npx -y @levisli/dlc-mcp install-codex
```

If the Gateway URL is not the default:

```bash
DLC_MCP_GATEWAY_URL=https://64.186.234.87/mcp \
DLC_MCP_GATEWAY_TOKEN=your-token \
  npx -y @levisli/dlc-mcp install-codex
```

The installer writes this Codex config:

> **Local development note:** if you run plain `npx` from the `@levisli/dlc-mcp` source checkout itself, npm may resolve the current package instead of the published package. The generated config uses `--prefix` with the system temporary directory to avoid that collision.

```toml
[mcp_servers.dlc-mcp]
command = "npx"
args = ["--yes", "--prefix", "/private/tmp", "@levisli/dlc-mcp@0.1.9"]
type = "stdio"

[mcp_servers.dlc-mcp.env]
DLC_MCP_GATEWAY_URL = "https://64.186.234.87/mcp"
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

The project architecture and layer boundaries are documented in [docs/architecture.md](docs/architecture.md).

Core-table and asset-value scoring are documented in [docs/core-table-model.md](docs/core-table-model.md).

Ordinary user access and token handling are documented in [docs/user-access.md](docs/user-access.md).

## Query Mode

The default user-facing server now uses explicit source modes instead of treating every SQLite fact as current truth.

DLC MCP uses three primary data sources:

- `registry`: SQLite index for tables, tasks, data sources, and project metadata.
- `live`: current Tencent Cloud / DLC / WeData API results for dynamic facts such as partitions, task runs, quality, lineage, and task code.
- `patrol_snapshot`: a specific daily patrol run used for governance reports and issue inventories.

Default `source=auto` behavior:

- Single-table and single-task diagnostics use `live`.
- Search and list tools use `registry`.
- Governance reports and issue inventories use the latest `patrol_snapshot`.

Use `source=legacy_cache` only for debugging old SQLite dynamic facts. Legacy cache results do not represent current truth.

Query failures are reported as `check_failed` or `partial_live`; they are not treated as confirmed missing partitions, missing task runs, missing quality rules, or missing lineage.

Query mode does not mutate remote WeData/DLC business objects. It may read remote metadata/code/project facts and update the local SQLite registry or patrol snapshots. Tools are advertised with MCP `readOnlyHint` annotations so clients that support tool annotations can make safer auto-approval decisions, but confirmation prompts are still controlled by each MCP Host.

## Asset patrol modes

The asset patrol command reuses the existing server registry for stable facts and live-refreshes dynamic evidence during the patrol run.

Stable cache/registry evidence:

- table metadata
- columns
- table lineage
- data source
- core table decision

Live-only evidence, written only to patrol snapshots/findings/errors:

- related tasks and producer task coverage
- task details and task dependencies
- quality status
- production status and task runs

Daily core patrol:

```bash
python3 -m dlc_mcp.asset_patrol --scope daily_core --instance-date 2026-07-16 --limit 100
```

Monthly full patrol, batched:

```bash
python3 -m dlc_mcp.asset_patrol --scope monthly_full --instance-date 2026-07-16 --limit 500 --batch-size 500 --offset 0
```

Manual table patrol:

```bash
python3 -m dlc_mcp.asset_patrol --scope manual --table ads_360_fin_income_cost_1d_di --instance-date 2026-07-16
```

`daily_p0` remains supported as a compatibility scope.

Patrol defaults favor completeness over aggressive runtime: concurrency is 3, each table has a 120-second timeout, retry count is 2, retry backoff is 2 seconds, API delay is 0.2 seconds, and failure threshold is 0.3. Slow or failed table checks are recorded in `patrol_errors` and marked `check_failed`; they are not treated as confirmed missing data.

The patrol writes:

- `patrol_runs`
- `patrol_asset_snapshots`
- `patrol_findings`
- `patrol_metrics`
- `patrol_errors`

Governance report tools read a single patrol `run_id` so report evidence is time-consistent. If no patrol snapshot exists, report tools ask the user to run patrol instead of falling back to legacy dynamic cache.

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
| `get_task_code(task_id/task_name, live)` | Return cached or live-refreshed WeData task SQL/code content. |
| `list_data_sources(query, live)` | List data sources, configuration summaries, and related task counts. |
| `get_data_source(data_source_id, live)` | Return one data source, including type, owner, related task count, description, and config summary. |
| `list_data_source_tasks(data_source_id, live)` | List tasks related to one data source. |
| `list_projects(query, live)` | List WeData projects cached from Tencent Cloud ListProjects. |
| `get_project(project_id, live)` | Return one WeData project, defaulting to `WEDATA_PROJECT_ID` when omitted. |
| `list_project_members(project_id, live)` | List members and roles for a WeData project. |
| `list_downstream_tasks(task_id, project_id, live)` | List downstream WeData task dependencies for a task. |
| `list_upstream_tasks(task_id, project_id, live)` | List upstream WeData task dependencies for a task. |
| `get_table(table_name/table_guid, live)` | Return Tencent Cloud WeData table metadata detail. |
| `get_data_source_inventory(data_source_id/data_source_name, live)` | Return one data source's tasks, parsed tables, SQL DDL, and unresolved or missing-field gaps. |
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
| `cleanup_task_name_pseudo_tables(dry_run, limit)` | Clean up pseudo table assets derived from task names. |

The project, member, task-relation, and table-detail tools use the same query-mode cache-first model as the existing asset tools. By default they read SQLite first and live-refresh only when the cached fact is missing or incomplete. Set `live=true` to force-refresh the requested fact from WeData. `GetTable` requires a real table GUID for live refresh; the service does not infer a table name from a task name.

Asset completeness must be checked with `get_sync_health`, `get_asset_coverage`, and `list_asset_coverage_gaps`. A successful API backfill only proves that the corresponding facts were collected; it does not prove that fields, lineage, quality rules, task mappings, runs, and data-source links are complete for every table.

Task input/output mappings come from real `GetTask` definitions. Data-integration node configuration is Base64-decoded and SQL tasks are parsed from returned SQL; task names are never used to infer table names. Task runs retain the latest seven calendar days by default (`DLC_MCP_TASK_RUN_RETENTION_DAYS`). Quality rules are fetched once as an authoritative paginated project list and replace stale cached rules after a successful full sync.

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
