# DLC-MCP Architecture

DLC-MCP is a WeData-first data asset MCP service. Its user-facing contract is MCP tools; implementation details such as live API calls, retries, parsing, and SQLite caching must stay behind those tools.

## Layer Model

```text
MCP Tools layer
- User calls tools only.
- Returns governance conclusions, DDL, tasks, lineage, production status, and gaps.
- Does not expose Tencent Cloud credentials or server filesystem paths.

Live Connector layer
- Wraps WeData/DLC APIs.
- Owns pagination, retries, rate-limit pacing, API payload differences, and field parsing.
- Converts raw API shapes into normalized snapshots.

Asset Store layer
- SQLite cache and lightweight asset graph.
- Stores facts, evidence, relationship edges, and refreshable analysis state.
- Supports cross-asset analysis without forcing every user query to refetch the whole tenant.

Sync Jobs / Admin Ops layer
- Full backfill, incremental sync, service restart, deployment, and log inspection.
- Operated through server access, not ordinary data-query MCP usage.
```

## Module Ownership

| Layer | Current modules | Responsibility |
| --- | --- | --- |
| MCP Tools | `dlc_mcp/mcp.py`, `dlc_mcp/server.py`, `dlc_mcp/gateway.py`, `bin/dlc-mcp.js` | MCP protocol, tool schemas, formatted user results, gateway access. |
| Live Connector | `dlc_mcp/live.py`, `dlc_mcp/tencentcloud.py`, `dlc_mcp/wedata.py`, `dlc_mcp/call_wedata_api.py` | WeData/DLC API calls, pagination, parsing, live refresh paths. |
| Asset Store | `dlc_mcp/assets.py` | SQLite schema, upserts, cached facts, evidence edges, governance analysis queries. |
| Sync/Admin Ops | `dlc_mcp/sync_wedata.py`, `dlc_mcp/sync_asset_facts.py`, `dlc_mcp/sync_table_fields.py`, `deploy/*` | Scheduled or manual backfills, incremental refreshes, server-side operational scripts. |
| Reports/Diagnostics | `dlc_mcp/check_foundation.py`, `dlc_mcp/diagnose_asset_gaps.py`, `dlc_mcp/check_table.py`, `dlc_mcp/validate_core_assets.py` | Read-only inspection and governance reports built from the store. |

## Query Path

Normal user data questions should follow this path:

```text
Codex -> dlc-mcp MCP tool -> Asset Store
                         -> Live Connector when live=true or cached evidence is insufficient
                         -> Asset Store update
                         -> formatted MCP result
```

Examples:

- Data source inventory: `get_data_source_inventory(data_source_name=..., live=true)`
- Table diagnosis: `get_table_profile`, `list_table_columns`, `get_table_tasks`, `get_table_lineage`
- Production status: `get_table_production_status`, `get_table_production_risk_detail`
- Coverage gaps: `get_sync_health`, `get_asset_coverage`, `list_asset_coverage_gaps`

Do not bypass MCP tools with shell, `curl`, or direct SQLite reads for ordinary data questions.

## Admin Path

Operational tasks are separate from user data queries:

```text
Codex -> ssh -> server repo/scripts/logs/gateway
```

Use this path only for:

- deploying code
- running full or incremental sync jobs
- restarting the gateway
- checking server logs or process state
- inspecting server-only credentials or environment setup

Tencent Cloud AK/SK must stay on the server.

## SQLite Positioning

SQLite is not the source of truth. It is a local asset cache and materialized graph used to make MCP tools fast and to support cross-asset analysis.

SQLite is appropriate while the service is single-node and asset facts are in the thousands to low millions. The main risks are unbounded history and stale facts, not SQLite itself.

Rules:

- Store normalized facts and evidence, not raw secrets.
- Use upserts for current facts.
- Keep raw dumps and long task-run history under retention control.
- Prefer table-level lineage in the hot store; fetch or archive high-volume column-level detail separately when needed.
- Tool responses must expose gaps instead of treating missing cached facts as healthy.

## Cloud API Catalog

The Asset Store must keep a Tencent Cloud API catalog in SQLite table `cloud_api_catalog`.

Each used WeData/DLC API must be recorded with:

- service, such as `wedata` or `dlc`
- action, such as `ListTasks` or `DescribeTablePartitions`
- provider and product
- official source URL
- document category
- interface description
- project usage

When adding a new Tencent Cloud API call in the Live Connector or Sync/Admin layer, update `TENCENT_CLOUD_API_CATALOG` in `dlc_mcp/assets.py` in the same change. Do not add an API call without cataloging its source, description, document category, and usage.

## Future Store Upgrade

If the project needs high write concurrency, long task-run history, multi-user dashboards, or large graph traversal, migrate the Asset Store behind a store interface:

```text
SQLite -> PostgreSQL -> PostgreSQL + Parquet archive -> optional graph database
```

Do not introduce a graph database before PostgreSQL unless lineage traversal becomes the primary workload and relational queries are no longer sufficient.

## Boundary Rules

- MCP tools should compose store reads and live refreshes; they should not contain vendor-specific pagination details.
- Live Connector code should return normalized API dumps/snapshots; it should not format user-facing markdown.
- Asset Store code should not call Tencent Cloud APIs.
- Sync/Admin scripts may call Live Connector and Asset Store, but they are not user-query interfaces.
- Skills and `AGENTS.md` guide agent behavior; they do not replace MCP tool logic.
