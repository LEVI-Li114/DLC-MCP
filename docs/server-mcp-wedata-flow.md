# Server MCP + Real WeData Flow

This document is the end-to-end runbook for running the MCP service on a server and querying real WeData data from Codex.

## Target Layout

```text
/opt/dlc-mcp/DLC-MCP       repo checkout
/data/dlc-mcp/assets.db      SQLite asset database used by MCP
/data/dlc-mcp/sync/          raw WeData JSON dumps
/etc/dlc-mcp/env             server-only Tencent Cloud credentials and sync config
```

Tencent Cloud AK/SK must stay on the server. Do not put them in GitHub, npm, Codex config, or user laptops.

## 1. Install Code On Server

```bash
sudo mkdir -p /opt/dlc-mcp /data/dlc-mcp /etc/dlc-mcp
sudo chown -R "$USER":"$USER" /opt/dlc-mcp /data/dlc-mcp

cd /opt/dlc-mcp
git clone https://github.com/LEVI-Li114/DLC-MCP.git
cd /opt/dlc-mcp/DLC-MCP

python3 -m unittest discover -s tests -v
```

## 2. Configure WeData Credentials

```bash
sudo cp /opt/dlc-mcp/DLC-MCP/deploy/env.example /etc/dlc-mcp/env
sudo chmod 600 /etc/dlc-mcp/env
sudo vi /etc/dlc-mcp/env
```

Fill in real values:

```bash
TENCENTCLOUD_SECRET_ID=your-secret-id
TENCENTCLOUD_SECRET_KEY=your-secret-key
TENCENTCLOUD_REGION=ap-guangzhou
WEDATA_VERSION=2025-08-06
WEDATA_PROJECT_ID=2881307738992685056
DLC_MCP_DB=/data/dlc-mcp/assets.db
WEDATA_SYNC_METADATA=0
WEDATA_METADATA_TABLE_LIMIT=50
WEDATA_METADATA_TABLES=
WEDATA_SYNC_DATA_SOURCES=0
WEDATA_SYNC_INSTANCES=0
WEDATA_INSTANCE_LOOKBACK_DAYS=2
WEDATA_INSTANCE_KEYWORDS=
WEDATA_INSTANCE_MAX_PAGES=50
WEDATA_INSTANCE_START=
WEDATA_INSTANCE_END=
```

Use the numeric WeData project id, not the project name.

## 3. Verify WeData API Access

```bash
cd /opt/dlc-mcp/DLC-MCP

set -a
. /etc/dlc-mcp/env
set +a

python3 -m dlc_mcp.call_wedata_api ListTasks "{\"ProjectId\":\"$WEDATA_PROJECT_ID\",\"PageNumber\":1,\"PageSize\":10}"
```

Success means the response contains `Response.Data.Items`.

## 4. Sync Real WeData Tasks Into MCP Database

```bash
cd /opt/dlc-mcp/DLC-MCP
bash deploy/sync-wedata-incremental.sh
```

The script:

- loads `/etc/dlc-mcp/env`
- calls `ListTasks` with pagination
- optionally calls `ListTable`, `GetTableColumns`, `ListLineage`, and `ListQualityRules`
- saves the raw task dump to `/data/dlc-mcp/sync/wedata_tasks.json`
- imports tasks into `/data/dlc-mcp/assets.db`
- runs a small MCP smoke test

Expected output:

```text
synced 2415 WeData tasks into /data/dlc-mcp/assets.db
saved raw task dump to /data/dlc-mcp/sync/wedata_tasks.json
MCP smoke test passed
```

## 5. Optional: Sync Real Table Metadata

Enable this when you want real fields, downstream lineage, and quality rules:

```bash
cd /opt/dlc-mcp/DLC-MCP
WEDATA_SYNC_METADATA=1 WEDATA_METADATA_TABLE_LIMIT=50 bash deploy/sync-wedata-incremental.sh
```

For a small targeted run:

```bash
WEDATA_SYNC_METADATA=1 WEDATA_METADATA_TABLES=ads_bill_company_1d_di,dws_360_fin_job_seat_1d_di bash deploy/sync-wedata-incremental.sh
```

This uses:

- `ListTable` to resolve table GUID, database, owner, description
- `GetTable` to refresh one table's metadata detail by `TableGuid`
- `GetTableColumns` to sync real fields
- `ListLineage` to sync downstream lineage
- `ListQualityRules` to sync quality monitoring rules

The metadata table limit keeps the sync small enough for manual runs. Increase it after the first run is stable.

The MCP server also supports cache-first, on-demand refresh for project and task metadata:

| MCP tool | WeData action | Cached table |
| --- | --- | --- |
| `list_projects(live=true)` | `ListProjects` | `projects` |
| `get_project(live=true)` | `GetProject` | `projects` |
| `list_project_members(live=true)` | `ListProjectMembers` | `project_members` |
| `list_downstream_tasks(live=true)` | `ListDownstreamTasks` | `task_relations` |
| `list_upstream_tasks(live=true)` | `ListUpstreamTasks` | `task_relations` |
| `get_table(live=true)` | `GetTable` | `tables` |

`GetTable` accepts only `TableGuid` in this integration. Resolve and cache the GUID through the table catalog first. Do not derive output tables from task-name prefixes.

After a backfill, do not use row counts alone as the acceptance check. Query `get_sync_health`, `get_asset_coverage`, and `list_asset_coverage_gaps`, then sample tables across ODS/DIM/DWD/DWS/ADS to verify fields, lineage, tasks, runs, quality rules, and data-source links.

Full fact sync also calls `GetTask` for each task to rebuild real input/output mappings. Data-integration task node JSON is decoded from `TaskConfiguration.CodeContent`; no task-name fallback is allowed. The same mapping connects existing task instances and `data_source_tasks` to tables.

Task instances retain seven calendar days by default:

```bash
DLC_MCP_TASK_RUN_RETENTION_DAYS=7 bash deploy/sync-wedata-full.sh /etc/dlc-mcp/env
```

Quality rules are listed once for the project with pagination. A successful response replaces the prior SQLite rule cache; API failure leaves the existing cache intact.

For a stable one-off full table field backfill, use the dedicated field-only script. It syncs table catalog and `GetTableColumns`, skips tables that already have columns unless forced, retries transient failures, writes a report with elapsed time, and avoids lineage/quality calls:

```bash
cd /opt/dlc-mcp/DLC-MCP
bash deploy/sync-wedata-full.sh /etc/dlc-mcp/env
```

Tune conservatively in `/etc/dlc-mcp/env` if Tencent Cloud rate limits are hit:

```bash
WEDATA_FULL_FIELDS_REQUEST_INTERVAL=0.3
WEDATA_FULL_FIELDS_MAX_RETRIES=5
WEDATA_FULL_FIELDS_RETRY_BASE_SLEEP=2
WEDATA_FULL_FIELDS_PROGRESS_EVERY=50
```

For a stable one-off full asset fact backfill after fields are ready, use:

```bash
cd /opt/dlc-mcp/DLC-MCP
bash deploy/sync-wedata-full.sh /etc/dlc-mcp/env
```

This syncs full task mappings, lineage, quality rules, and a wider task-instance window. It writes elapsed time and failures to:

```text
/data/dlc-mcp/sync/wedata_asset_facts_full_report.json
```

## 6. Optional: Sync Task Runs

After `ListTaskInstances` works for your tenant, enable run-instance sync:

```bash
sudo vi /etc/dlc-mcp/env
```

```bash
WEDATA_SYNC_INSTANCES=1
WEDATA_INSTANCE_LOOKBACK_DAYS=2
WEDATA_INSTANCE_KEYWORDS=ads_bill_company_1d_di,dws_360_fin_job_seat_1d_di
WEDATA_INSTANCE_MAX_PAGES=50
WEDATA_INSTANCE_START=2026-07-01 00:00:00
WEDATA_INSTANCE_END=2026-07-01 23:59:59
```

Then rerun:

```bash
cd /opt/dlc-mcp/DLC-MCP
bash deploy/sync-wedata-incremental.sh
```

This populates task start time, end time, duration, and status for `get_task_runs(task_id)`.

If `WEDATA_INSTANCE_START` and `WEDATA_INSTANCE_END` are empty, the sync uses a rolling window. With `WEDATA_INSTANCE_LOOKBACK_DAYS=2`, every cron run syncs yesterday and today.

Use `WEDATA_INSTANCE_KEYWORDS` to limit instance sync to task names or task ids. Full-project instance sync can be very large, so do not enable it in scheduled sync without a keyword filter.

## 7. Smoke Test MCP On Server

List tools:

```bash
cd /opt/dlc-mcp/DLC-MCP

printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
  | DLC_MCP_DB=/data/dlc-mcp/assets.db python3 -m dlc_mcp.server
```

Search real synced tasks:

```bash
printf '%s\n' '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"search_tasks","arguments":{"query":"dws_360_fin_job_seat_1d_di"}}}' \
  | DLC_MCP_DB=/data/dlc-mcp/assets.db python3 -m dlc_mcp.server
```

Get task runs:

```bash
printf '%s\n' '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"get_task_runs","arguments":{"task_id":"20250808125438221","limit":5}}}' \
  | DLC_MCP_DB=/data/dlc-mcp/assets.db python3 -m dlc_mcp.server
```

## 8. Smoke Test HTTP Gateway From A User Laptop

The user laptop only needs HTTPS access to the Gateway. Nginx terminates TLS with `deploy/nginx-dlc-mcp.conf`; the Python Gateway remains bound to `127.0.0.1:8787`.

```bash
curl --cacert certs/dlc-mcp-gateway.crt -s https://64.186.234.87/health

curl --cacert certs/dlc-mcp-gateway.crt -s https://64.186.234.87/mcp \
  -H 'content-type: application/json' \
  -H 'authorization: Bearer your-token' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

If this returns MCP tools, Codex can use the server.

## 9. Connect Codex

After the npm package is published, users can run:

```bash
DLC_MCP_GATEWAY_TOKEN=your-token npx -y @levisli/dlc-mcp install-codex
```

If the Gateway URL is different:

```bash
DLC_MCP_GATEWAY_URL=https://64.186.234.87/mcp \
DLC_MCP_GATEWAY_TOKEN=your-token \
  npx -y @levisli/dlc-mcp install-codex
```

Restart Codex, then ask:

```text
用 dlc-mcp 搜索任务 dws_360_fin_job_seat_1d_di
```

## 10. Current Supported Real Data

- Real WeData task list: supported through `ListTasks`
- Task search: supported through `search_tasks(query)`
- Task run start/end/duration/status: supported after optional `ListTaskInstances` sync
- Table metadata and fields: supported through optional `ListTable` and `GetTableColumns` sync
- Downstream lineage: supported through optional `ListLineage` sync
- Quality rules: supported through optional `ListQualityRules` sync
- Data source listing, configuration lookup, related task count, and related task details: supported through `ListDataSources` and `GetDataSourceRelatedTasks`
- Data source related task table parsing: `GetDataSourceRelatedTasks` only proves that a data source is related to a WeData task. The inventory does not treat the related task name as a table name. The sync first fetches/imports the related task definition and then uses the task parser to extract input/output tables from explicit task fields or SQL. If an older sync created fake tables derived from task names such as `m2c_ods_*`, run `python3 -m dlc_mcp.cleanup_derived_tables --apply` against the affected database after verifying the dry-run output.
- Metadata database/table listing: supported after optional metadata sync
- Usage heat: not supported yet; needs query logs or BI/report access logs

## 11. Routine Refresh

Run whenever you want to refresh data:

```bash
cd /opt/dlc-mcp/DLC-MCP
git pull
bash deploy/sync-wedata-incremental.sh
```

Install the central scheduler:

```bash
cd /opt/dlc-mcp/DLC-MCP
bash deploy/install-sync-cron.sh
```

The installer writes one idempotent crontab entry. It runs daily at 08:00 and calls `deploy/sync-wedata-incremental.sh`:

```cron
0 8 * * * cd /opt/dlc-mcp/DLC-MCP && bash deploy/sync-wedata-incremental.sh /etc/dlc-mcp/env >> /data/dlc-mcp/logs/sync.log 2>&1 # dlc-mcp-wedata-sync
```

Daily sync updates the bottom-layer facts used by MCP tools: task catalog and task-table mappings, table catalog, full metadata for tables whose catalog create/update date is yesterday, yesterday's task instances, data sources and related tasks, and yesterday's partition facts.

Verify the schedule and logs:

```bash
crontab -l | grep dlc-mcp-wedata-sync
tail -f /data/dlc-mcp/logs/sync.log
```

If `/data/dlc-mcp/logs` has no write permission:

```bash
sudo mkdir -p /data/dlc-mcp/logs
sudo chown -R "$USER":"$USER" /data/dlc-mcp/logs
```

After this, if WeData adds a new task, wait until the next 08:00 run or run `bash deploy/sync-wedata-incremental.sh` manually, then ask MCP through `search_tasks(query)`.
