# Live-first DLC MCP Architecture Design

Date: 2026-07-16

## 1. Context and Problem

DLC MCP currently uses SQLite as a long-lived asset fact cache. This works reasonably for assets that can be fully enumerated, such as tables, tasks, and data sources. It is not reliable for dynamic or windowed assets such as partitions, task runs, lineage, quality status, and production risk. Those assets are often incomplete, time-dependent, or affected by incremental refresh gaps.

A recent example exposed the failure mode: `ods_cloud_cost_baidu_day_di` had a true latest partition of `dt=20260715`, but the cached partition profile still reported `dt=20260706`. Because the cache already contained some partition facts, the MCP tool considered the fact set available and did not refresh. The result was a stale answer presented as the current partition state.

The new architecture must keep fast search and daily governance patrol useful without letting stale SQLite facts become the default source of truth for dynamic asset queries.

## 2. Goals

- Make interactive single-table and single-task diagnostics live-first by default.
- Keep SQLite for assets that can be fully refreshed and used as stable indexes: tables, tasks, data sources, and optional project metadata.
- Replace long-lived dynamic fact caching with explicit patrol snapshots for daily governance reports.
- Preserve daily patrol timeliness by using bounded live sampling and per-run snapshots rather than live-scanning everything on every report read.
- Clearly distinguish confirmed empty results from live query failures.
- Keep legacy cache access available only as an explicit compatibility/debugging mode.

## 3. Non-goals

- Do not remove SQLite entirely.
- Do not require every report request to live-scan all assets.
- Do not continue treating old dynamic cache data as current truth.
- Do not infer missing partitions, runs, quality rules, or lineage from cache misses.
- Do not attempt a full rewrite in one step.

## 4. Architecture Overview

The system will use three data layers.

### 4.1 Registry Layer

SQLite remains the registry for assets that can be fully synchronized:

| Asset | Role |
| --- | --- |
| Tables | Search, layer/owner/database metadata, table identity, basic fields |
| Tasks | Task ID/name resolution, producer task index |
| Data sources | Data source search and data-source-to-task entry points |
| Projects/members | Optional ownership and project context |

Registry data is an index, not a guarantee of live asset state.

### 4.2 Live Query Layer

Dynamic facts are queried live by default:

| Dynamic area | Default source |
| --- | --- |
| Partitions | DLC/WeData partition API |
| Task runs | `ListTaskInstances` |
| Quality rules/status | quality APIs |
| Lineage/upstream/downstream | lineage APIs |
| Task code | `GetTaskCode` |
| Production status | registry producer task mapping + live task runs |
| Risk/readiness/table profile | live module composition + registry context |

The live query layer returns structured module results with errors. It does not format markdown directly.

### 4.3 Patrol Snapshot Layer

Daily governance analysis writes per-run snapshots rather than long-lived current facts.

Proposed tables:

| Table | Purpose |
| --- | --- |
| `patrol_runs` | one row per patrol run, with scope/status/timing/counts/config/summary |
| `patrol_asset_snapshots` | per-asset sampled live state for a run |
| `patrol_findings` | issues found during that run, with evidence and severity |
| `patrol_metrics` | aggregate coverage/risk metrics for that run |
| `patrol_errors` | per-module live query failures and retryability |

Daily report tools read the latest suitable patrol snapshot. They do not live-scan all assets on report read and do not fall back to old dynamic caches by default.

## 5. MCP Tool Behavior

### 5.1 Unified Source Semantics

MCP responses should use explicit source labels:

| Source | Meaning |
| --- | --- |
| `registry` | SQLite registry index only |
| `live` | fully live result |
| `partial_live` | live query succeeded for some modules and failed for others |
| `patrol_snapshot` | result from a specific patrol run snapshot |
| `legacy_cache` | old SQLite dynamic facts; not current truth |
| `not_available` | no valid source is available |

### 5.2 Source Parameter

Dynamic and report tools should accept:

```json
{
  "source": "auto | live | registry | patrol_snapshot | legacy_cache"
}
```

Default `source=auto` means:

| Tool category | Auto behavior |
| --- | --- |
| Single-table/task diagnostics | live |
| Search/list registry tools | registry |
| Governance reports/inventories | latest patrol snapshot |

Existing `live=true` should be supported during migration and internally mapped to `source=live`. Explicit `source=legacy_cache` is required to read old dynamic facts.

### 5.3 Registry Tools

These can continue reading SQLite registry data:

- `search_assets`
- `get_table` / table metadata lookup
- `list_table_columns`, with live refresh support when requested
- `search_tasks`
- `list_data_sources`
- `get_data_source`
- `get_asset_coverage`, after it is updated to use registry and latest patrol metrics instead of old dynamic facts

### 5.4 Live-first Tools

These should default to live:

- `get_table_partition_profile`
- `get_table_production_status`
- `get_task_runs`
- `get_quality_status`
- `get_table_lineage`
- `get_table_tasks`
- `get_task_code`
- `get_table_risk_profile`
- `get_table_readiness`
- `get_table_profile`

If a composed tool has partial failures, it should return successful modules plus explicit errors and label the response `partial_live`.

### 5.5 Governance/Patrol Tools

These should default to latest patrol snapshot:

- `get_asset_governance_daily_report`
- `get_asset_governance_issue_inventory`
- `list_table_production_risks`
- `list_quality_gaps`
- `list_asset_coverage_gaps`
- `list_expert_review_queue`

If no patrol snapshot exists, return a clear message asking the user to run patrol first. Do not silently fall back to legacy dynamic cache.

## 6. Daily Patrol Design

### 6.1 Patrol Scopes

- `daily_p0`: daily high-impact patrol for core/high-downstream/recent-risk/producer-backed assets.
- `weekly_full`: weekly broader patrol over valid warehouse layers (`ods`, `dim`, `dwd`, `dws`, `mid`, `ads`).
- `on_demand`: targeted patrol by table, layer, owner, domain, or chain.

### 6.2 Per-asset Modules

Per table, patrol may sample:

| Module | daily_p0 priority |
| --- | --- |
| Registry profile | required |
| Producer task mapping | required |
| Current/target task runs | required |
| Latest or expected partition | required for partitioned tables |
| Owner/profile | required |
| Data source | required |
| Quality | required for P0/core, optional otherwise |
| Lineage | required for P0/high-downstream, optional otherwise |
| Risk calculation | required, based on sampled modules |

### 6.3 Run and Module Status

Module statuses:

| Status | Meaning |
| --- | --- |
| `ok` | live query succeeded and no issue found |
| `risk` | live query succeeded and found a risk |
| `empty_confirmed` | live query succeeded and confirmed empty state |
| `check_failed` | live query failed |
| `skipped` | skipped by patrol scope |
| `not_applicable` | not relevant for the asset |

Run statuses:

| Status | Meaning |
| --- | --- |
| `completed` | all planned modules completed |
| `partial` | some modules failed but report is usable |
| `failed` | base registry unavailable or failure rate exceeds threshold |
| `cancelled` | manually cancelled |

Default threshold: if more than 30% of planned modules fail, mark the run `failed`; otherwise failures make it `partial`.

### 6.4 Report Generation

`get_asset_governance_daily_report` should:

1. Select the latest completed or partial patrol run matching requested date/scope.
2. Read findings, metrics, errors, and asset snapshots for that single `run_id`.
3. Report the run ID, scope, start/end time, checked count, and error count.
4. Separate confirmed asset risks from check failures.
5. Include a section for incomplete checks.

## 7. Failure, Rate-limit, and Degradation Strategy

### 7.1 Core Semantics

- Live failure does not mean the asset is unhealthy.
- Cache miss does not mean the asset is unhealthy.
- Only a successful live response can confirm an empty/missing condition.
- Failed module checks return `unknown` or `check_failed` with evidence.

Examples:

| Scenario | New result |
| --- | --- |
| partition API fails | `partition.status=check_failed` |
| live partition API succeeds and target partition is absent | confirmed `missing_partition` |
| task run API fails | production status `unknown`, reason `task_run_check_failed` |
| task run API succeeds and no run exists | confirmed `not_run` |
| quality API fails | quality status `unknown` |
| quality API succeeds and returns no rules | confirmed `missing_quality_rules` |

### 7.2 Limits and Retries

Suggested default concurrency:

| Module | Concurrency |
| --- | ---: |
| task runs | 5 |
| partitions | 3 |
| lineage | 3 |
| quality | 3 |
| table detail | 5 |

Retry only retryable errors: timeouts, 5xx, throttling, and temporary unavailable. Retry at most twice with short backoff, e.g. 1s then 3s. Do not retry invalid parameters, unsupported actions, permission denied, or table not found.

### 7.3 Circuit Breaker

If one API action repeatedly fails in a patrol run, skip that module for the rest of the run and record a patrol error. Suggested trigger: 10 consecutive failures or a five-minute failure rate above 50%.

## 8. Component Boundaries

### 8.1 `RegistryStore`

Owns registry-oriented SQLite access. It may initially wrap existing `AssetStore` methods but should be conceptually separate from dynamic fact storage.

Responsibilities:

- Search tables/tasks/data sources.
- Resolve table database/GUID/owner/layer.
- Resolve task ID/name and producer task candidates.
- Provide base candidate sets for patrol.

### 8.2 `LiveAssetService`

Owns live single-asset queries.

Responsibilities:

- Fetch partitions, task runs, quality status, lineage, task code, and composed table profile live.
- Return structured module results and errors.
- Enforce failure semantics and source labels.
- Avoid markdown formatting.

### 8.3 `PatrolService`

Owns batch patrol execution.

Responsibilities:

- Select patrol scope candidates.
- Run bounded concurrent live checks.
- Write `patrol_runs`, snapshots, findings, metrics, and errors.
- Mark run status consistently.

### 8.4 `GovernanceReportService`

Owns report/inventory generation from patrol snapshots.

Responsibilities:

- Generate daily report, issue inventory, risk lists, quality gaps, and coverage gaps from a single run ID.
- Avoid direct live API scans in report read paths.
- Avoid legacy dynamic cache fallback by default.

## 9. Migration Plan

### Phase 1: Correct Query Semantics

- Add `source` parameter support and unified query metadata.
- Make high-risk dynamic tools default to live.
- Fix `get_table_partition_profile` schema/behavior so callers can force live/source and missing target partitions can trigger live checks.
- Mark old dynamic fact reads as `legacy_cache`.

### Phase 2: Extract Live Service

- Introduce `LiveAssetService`.
- Move live partition, task run, quality, lineage, and task code logic behind service methods.
- Update MCP tools to call the service.

### Phase 3: Add Patrol Snapshot

- Add patrol tables.
- Add patrol CLI or MCP entry point, starting with `daily_p0`.
- Write per-run snapshots, findings, metrics, and errors.
- Make daily report read latest patrol snapshot.

### Phase 4: Migrate Governance Aggregates

- Move issue inventory, production risk list, quality gaps, coverage gaps, and expert queue to patrol snapshot sources.
- Keep old aggregate logic behind `source=legacy_cache` only if needed.

### Phase 5: Freeze or Remove Legacy Dynamic Cache

- Stop relying on incremental sync for partitions/runs/lineage/quality as current facts.
- Keep registry sync for tables/tasks/data sources.
- Remove or freeze misleading health checks that depend on stale dynamic facts.

## 10. Testing Strategy

### Live Query Tests

- Live success returns `source=live` and current data.
- Partial module failure returns `source=partial_live` with errors.
- Successful empty live response is required before marking missing/empty.
- Legacy cache absence does not produce missing/risk conclusions.
- `source=legacy_cache` still exposes old data with warning metadata.

### Patrol Tests

- Patrol run creation, completion, partial, and failed status.
- Per-module failure does not block the run unless threshold is exceeded.
- Findings distinguish `missing_*` from `*_check_failed`.
- Daily report uses one run ID consistently.
- No patrol snapshot returns a clear instruction to run patrol first.

### Regression Scenario

Use the known stale partition case:

- Legacy cache latest partition: `dt=20260706`.
- Live latest partition: `dt=20260715`.
- Default `get_table_partition_profile` returns live `dt=20260715`.
- `source=legacy_cache` returns `dt=20260706` with warning metadata.

## 11. Success Criteria

- Single-table dynamic queries default to live results.
- Old dynamic cache is never presented as current truth unless explicitly requested.
- Query failures are reported as failures, not inferred asset gaps.
- Daily governance reports come from a specific patrol `run_id`.
- Patrol reports include checked/error counts and incomplete checks.
- Tables, tasks, and data sources remain searchable from registry.
- Incremental dynamic sync failures no longer pollute interactive answers or patrol conclusions.
