# DLC/WeData Incremental Sync and Governance Execution Design

Date: 2026-07-15

## Goal

Implement the P0 technical closure path for the DLC/WeData asset governance system. This design focuses on stabilizing daily incremental sync, making MCP query freshness visible, and lightly upgrading the daily governance report into an execution-oriented report.

This spec intentionally does not introduce a full ticket/status system. The scope is to standardize and harden the existing capabilities without a large architecture rewrite.

## Scope

Included:

1. Change daily table increment defaults from create-time only to structure/update/create based detection.
2. Add task change-time incremental enrichment.
3. Refresh changed tasks' relations, task code, and input/output table mapping.
4. Add bounded repair entry points for missing task mapping and missing task run coverage.
5. Add MCP query metadata so users can see whether results came from cache or live refresh.
6. Add lightweight execution summary, responsibility buckets, and acceptance criteria to the daily governance report.

Excluded:

- No ticket table.
- No persisted solved/ignored state.
- No daily report push/notification workflow.
- No full trend dashboard.
- No large sync framework rewrite.
- No assumption that sparse quality rules are a sync failure.

## Current Context

Current project evidence:

- Full sync entrypoint: `deploy/sync-wedata-full.sh` runs `dlc_mcp.sync_asset_facts` and `dlc_mcp.sync_table_fields`.
- Daily incremental entrypoint: `deploy/sync-wedata-incremental.sh` runs `dlc_mcp.sync_wedata`, MCP smoke test, and foundation check.
- `dlc_mcp.sync_wedata` already syncs task catalog, table catalog, table metadata, partitions, data sources, and task instances.
- Table date filtering already supports `structure_update` via `StructUpdateTime`, but the daily script currently defaults to `create`.
- Task catalog sync currently starts from `ListTasks` and does not have an explicit changed-task enrichment path.
- `dlc_mcp.mcp` already uses cache-first/live-fallback patterns across many tools, but the Markdown response does not expose the source/freshness metadata.
- The daily governance report already includes production risks, coverage gaps, quality gaps, owner gaps, lifecycle watch, expert review queue, and manual review sections from recent work.

## Architecture

Keep the current three-layer structure:

```text
deploy/sync-wedata-incremental.sh
        ↓
dlc_mcp.sync_wedata
        ↓
AssetStore / SQLite
        ↓
dlc_mcp.mcp tools
        ↓
MCP query results and daily governance report
```

Add small boundaries inside the existing files rather than introducing a new framework:

1. Increment window parsing and defaults.
2. Changed task filtering/enrichment.
3. Repair-target discovery.
4. MCP query metadata wrapping.
5. Daily report execution summarization.

## Data Flow

### Table Increment Flow

```text
ListTable full catalog
    ↓
Filter tables by structure_update/update/create window
    ↓
Fetch metadata, columns, lineage, quality rules only for changed tables
    ↓
Import snapshot into SQLite
```

Default daily date fields become:

```text
structure_update,update,create
```

Existing variables remain supported:

- `WEDATA_NEW_ASSET_START`
- `WEDATA_NEW_ASSET_END`
- `WEDATA_NEW_ASSET_DATE_FIELDS`
- `WEDATA_NEW_ASSET_STRICT`

New aliases may be added for clarity:

- `WEDATA_CHANGED_TABLE_START`
- `WEDATA_CHANGED_TABLE_END`
- `WEDATA_TABLE_CHANGE_DATE_FIELDS`
- `WEDATA_TABLE_CHANGE_STRICT`

Precedence:

```text
new variable > old variable > default
```

### Task Increment Flow

```text
ListTasks task catalog
    ↓
Keep full task catalog in the snapshot
    ↓
Filter changed tasks by update/modify/create fields
    ↓
For changed tasks, run bounded enrichment:
        - task detail when needed
        - task code
        - upstream tasks
        - downstream tasks
        - input/output table mapping
    ↓
Merge enriched changed tasks back into snapshot
    ↓
Import snapshot into SQLite
```

Do not trim the full task catalog down to only changed tasks. The full catalog keeps cached task metadata complete; the changed-task subset only controls high-cost enrichment calls.

Task date field groups:

- `create`: `CreateTime`, `CreateDate`, `CreatedAt`, `CreateAt`, `GmtCreate`
- `update` / `modify`: `UpdateTime`, `ModifyTime`, `ModifiedAt`, `LastModifyTime`, `UpdateDate`
- `schedule`: `ScheduleTime`, `ScheduleUpdateTime`

Daily defaults:

```bash
WEDATA_TASK_CHANGE_START=$YESTERDAY
WEDATA_TASK_CHANGE_END=$YESTERDAY
WEDATA_TASK_CHANGE_DATE_FIELDS=update,modify,create
WEDATA_TASK_CHANGE_STRICT=0
```

Task strict defaults to `0` because changed-task enrichment is additive. If task date fields are missing, the sync should log that enrichment was skipped while still refreshing the task catalog.

### Partition and Run Flow

Keep existing behavior:

- Daily partition date is yesterday via `WEDATA_PARTITION_DATE`.
- Daily task instance window is yesterday 00:00:00 through 23:59:59.
- `ListTablePartitions InvalidAction` remains classified as unsupported action/version, not a parameter bug.

### Repair Flow

Add bounded repair entry points for task mapping and run coverage issues.

Environment variables:

```bash
WEDATA_REPAIR_TABLES=table_a,table_b
WEDATA_REPAIR_TASK_IDS=123,456
WEDATA_REPAIR_ISSUE_TYPES=missing_task_mapping,missing_task_runs
WEDATA_REPAIR_TASK_LIMIT=200
```

Rules:

- `WEDATA_REPAIR_TASK_IDS` directly enriches those tasks and fetches relevant runs.
- `WEDATA_REPAIR_TABLES` resolves related tasks from existing SQLite cache, then enriches them.
- `WEDATA_REPAIR_ISSUE_TYPES` filters the repair intent; if omitted, repair mapping and run gaps.
- Daily sync does not automatically repair all issue inventory rows. Repair is a targeted manual or cron-controlled action.

## Component Design

### `deploy/sync-wedata-incremental.sh`

Changes:

- Default table metadata date fields to `structure_update,update,create`.
- Export task change window and task change field defaults.
- Log task change fields and window alongside existing metadata/partition logs.

Expected log lines should include:

- `metadata_date_fields: structure_update,update,create`
- `task_change_date_fields: update,modify,create`
- `task_change_window: <yesterday>..<yesterday>`
- existing partition and instance window information.

### `dlc_mcp/sync_wedata.py`

Add helpers:

- `_table_change_start()` / `_table_change_end()` or equivalent alias-aware parsing.
- `_table_change_date_fields()` or alias-aware wrapper over `WEDATA_NEW_ASSET_DATE_FIELDS`.
- `_filter_changed_tasks(tasks_response, start, end)`.
- `_task_item_dates(item)`.
- `_sync_changed_task_relations(client, project_id, changed_tasks, page_size)`.
- `_sync_changed_task_codes(client, project_id, changed_tasks)`.
- `_enrich_changed_task_definitions(client, project_id, changed_tasks, page_size)`.
- `_repair_targets_from_env(store)` or equivalent bounded repair target resolution.

Reuse existing helpers where possible:

- `_parse_date()`
- `_date_in_window()`
- `_list_all()`
- `_task_lineage_tables()`
- `_task_detail()`
- `_merged_table_list()`
- `_merge_task_responses()`

Behavior:

- Always import the full `ListTasks` response into the snapshot.
- Use changed tasks only to drive enrichment.
- Enrichment failures should be collected into raw dump metadata and logged; a single task failure must not abort the whole sync.
- Enrichment should obey limits:
  - `WEDATA_CHANGED_TASK_LIMIT=500`
  - `WEDATA_SYNC_CHANGED_TASK_CODES=1`
  - `WEDATA_CHANGED_TASK_CODE_LIMIT=200`

### `dlc_mcp/live.py`

Keep current live sync functions. If a live function does not return useful status, update it to return a simple dictionary:

```python
{
    "ok": True,
    "action": "sync_task_code",
    "refreshed": 1,
    "error": "",
}
```

MCP metadata should not depend on perfect status from every live function; exceptions and successful completion are enough for the first version.

### `dlc_mcp/mcp.py`

Add metadata for every tool call:

```python
meta = {
    "source": "cache",
    "live_attempted": False,
    "live_reason": "",
    "live_error": "",
}
```

Add a helper such as:

```python
def _maybe_live_refresh(meta, args, data, predicate, refresh_fn, reason=""):
    ...
```

Responsibilities:

1. Decide whether a live refresh is needed.
2. Record whether live was attempted.
3. Record why it was attempted.
4. Catch refresh exceptions.
5. Leave cached data available when refresh fails.

Suggested source values:

- `cache`
- `cache_snapshot`
- `cache_after_live_refresh`
- `live_refresh_failed_cache`
- `live_refresh_failed_no_cache`

Add Markdown wrapper:

```python
def _format_with_meta(tool_name, data, meta):
    return _format_query_meta(meta) + "\n\n" + _format_markdown(tool_name, data)
```

Example:

```markdown
**查询元信息**

- 数据来源：cache_after_live_refresh
- 实时刷新：是
- 触发原因：cache_miss
```

If live fails:

```markdown
**查询元信息**

- 数据来源：live_refresh_failed_cache
- 实时刷新：失败
- 触发原因：user_requested
- 失败原因：GetTaskCode failed: ...
```

Initial coverage should include high-trust user-facing tools:

- `search_tasks`
- `get_table_profile`
- `list_table_columns`
- `get_quality_status`
- `get_table_lineage`
- `get_table_tasks`
- `get_task_runs`
- `get_task_code`
- `get_table`
- `get_table_production_status`
- `get_table_production_risk_detail`
- `get_data_source`
- `list_data_source_tasks`

Summary-only tools should not trigger live refresh and should use `cache_snapshot`:

- `get_sync_health`
- `get_asset_coverage`
- `get_asset_governance_issue_inventory`
- `get_asset_governance_daily_report`

### `dlc_mcp/assets.py`

Enhance `AssetStore.get_asset_governance_daily_report()` by adding:

```json
{
  "execution_summary": {
    "p0": [],
    "p1": [],
    "p2": []
  },
  "responsibility_buckets": {
    "data_platform": [],
    "warehouse_owner": [],
    "bi_owner": [],
    "business_owner": [],
    "unknown_owner": []
  },
  "acceptance_criteria": []
}
```

Inputs:

- `manual_review_sections`
- `manual_review_top_items`
- `production_risks`
- `coverage_gaps`
- `quality_gaps`
- `owner_gaps`
- `lifecycle_watch`

Rules:

- Prioritize deterministic manual review and production gaps before sparse quality-rule gaps.
- Quality-rule gaps remain visible, but recommendations must not imply that source-governance sparsity is a sync bug.
- Unknown or conflicting owner evidence goes to `unknown_owner` or an explicit owner-review bucket; do not invent owners.

MCP Markdown should render:

- Governance execution summary.
- Responsibility breakdown.
- Acceptance criteria.

## Error Handling

### Table Date Fields Missing

In strict mode, fail with a clear error if no recognizable table date fields exist:

```text
ListTable response has no recognized create/update/structure_update time fields for changed asset sync
```

In non-strict mode, return no changed tables and log the condition.

### Task Date Fields Missing

Default `WEDATA_TASK_CHANGE_STRICT=0`.

If no task date fields are recognized:

- Log: `ListTasks response has no recognized task change time fields; changed task enrichment skipped`.
- Keep full task catalog import.
- Skip changed-task enrichment.
- If strict is enabled, fail the sync.

### Per-Task Enrichment Failure

Do not abort the whole sync for a single changed task failure. Record:

```json
{
  "task_id": "...",
  "task_name": "...",
  "action": "GetTaskCode",
  "error": "..."
}
```

Store failures in the raw dump under a descriptive key such as `task_enrichment_failures` and print a count.

### Live Fallback Failure

Return the best available cached result with metadata when possible.

Behavior matrix:

| Cache state | Live state | Result |
| --- | --- | --- |
| cache hit | live not needed | return cache + `source=cache` |
| cache miss/incomplete | live succeeds | return refreshed cache + `source=cache_after_live_refresh` |
| cache hit | live fails | return cache + `source=live_refresh_failed_cache` |
| cache miss | live fails | return error + `source=live_refresh_failed_no_cache` |

## Compatibility

- Do not change JSON-RPC envelopes.
- Do not remove existing daily report keys.
- Do not rename existing store methods.
- Keep old table increment variables working.
- Keep quality-rule gaps visible.
- Keep default daily sync bounded through limits.

## Testing Plan

### `tests/test_sync_wedata.py`

Add tests for:

1. Daily table date default includes `structure_update`.
2. `_item_dates()` recognizes `StructUpdateTime`.
3. `_filter_changed_tasks()` filters by `UpdateTime`.
4. Full task catalog remains intact while only changed tasks are enriched.
5. Partition date filtering still keeps only the requested date.
6. Missing task date fields do not fail when strict is disabled.

### `tests/test_mcp.py`

Add tests for:

1. Cache hit shows `数据来源：cache`.
2. Live fallback success shows `cache_after_live_refresh`.
3. Live fallback failure returns cached data and shows failure metadata.
4. Daily report and health tools show snapshot metadata and do not call live.

### `tests/test_assets.py`

Add tests for:

1. Daily report includes `execution_summary`.
2. Daily report includes `responsibility_buckets`.
3. Daily report includes `acceptance_criteria`.
4. Manual review / production gaps appear before quality-rule-only gaps in execution summary.

## Verification

Run targeted tests:

```bash
python3 -m pytest tests/test_sync_wedata.py tests/test_mcp.py tests/test_assets.py -q
```

If targeted tests pass, run full tests:

```bash
python3 -m pytest -q
```

Manual sync smoke test:

```bash
DLC_MCP_SYNC_TODAY=2026-07-15 deploy/sync-wedata-incremental.sh <env-file>
```

Expected sync evidence:

- `metadata_date_fields: structure_update,update,create`
- `task_change_date_fields: update,modify,create`
- `partition_date: 2026-07-14`
- yesterday task instance window
- MCP smoke test passed
- foundation check reports real gaps rather than hidden failures

Manual MCP checks:

- A cache-first table/task tool returns `查询元信息`.
- `live=true` records whether live refresh happened.
- Daily report includes execution summary, responsibility buckets, and acceptance criteria.

## Acceptance Criteria

Implementation is accepted when:

1. Daily incremental table sync defaults to structure/update/create fields.
2. Changed-task filtering exists and is covered by tests.
3. Changed-task enrichment can refresh relations, code, and input/output mappings within configured limits.
4. Repair env vars can target task mapping/run gaps without triggering unbounded sync.
5. MCP Markdown exposes query source and live refresh status.
6. Live failure does not discard usable cached data.
7. Daily governance report contains execution summary, responsibility buckets, and acceptance criteria.
8. Existing report sections and MCP tool names remain compatible.
9. Targeted tests pass.

## Implementation Order

1. Update incremental shell defaults and logs.
2. Add sync window aliases and changed-task filtering tests.
3. Implement changed-task filtering and enrichment helpers.
4. Add bounded repair targets.
5. Add MCP query metadata helper and cover key tools.
6. Add daily report execution summary fields and Markdown rendering.
7. Run targeted and full tests.
