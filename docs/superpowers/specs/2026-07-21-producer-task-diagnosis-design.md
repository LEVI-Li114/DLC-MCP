# Producer Task Missing Diagnosis Design

Date: 2026-07-21

## 1. Goal

Improve `missing_producer_task` from a generic gap into an actionable diagnosis. The system should explain why a table appears to have no producer task, what evidence supports that conclusion, and what the next check should be.

This phase is diagnostic-first. It does not attempt to automatically repair `task_tables`, rewrite WeData sync, or change SQL parsing behavior.

## 2. Non-goals

This design does not include:

- Rewriting `sync_wedata.py` task extraction.
- Adding large-scale live refresh jobs.
- Automatically backfilling or repairing `task_tables` mappings.
- Adding fuzzy matching, semantic matching, or LLM inference for task-table links.
- Changing quality-rule governance priorities.
- Guessing owners from table names.

## 3. Diagnosis model

Add a lightweight producer diagnosis object to existing gap, issue, and patrol outputs:

```json
{
  "producer_diagnosis": {
    "root_cause": "consumer_only_mapping",
    "reason": "该表有关联任务，但全部是 input/consumer，没有 output/producer。",
    "evidence_source": "cache",
    "evidence": {
      "layer": "ads",
      "task_count": 3,
      "producer_task_count": 0,
      "consumer_task_count": 3,
      "upstream_count": 2,
      "downstream_count": 5,
      "run_count": 0
    },
    "next_check": "检查任务 outputs、SQL INSERT/CREATE 解析和表名标准化，确认该表的产出任务是否漏识别。"
  }
}
```

The diagnosis is deterministic and based on existing cache facts, patrol live context, or explicitly requested live evidence.

## 4. Root cause taxonomy

Initial root cause categories:

| Root cause | Meaning |
| --- | --- |
| `unknown_layer_first` | The table is still in the unknown layer; fix layer classification before trusting producer-gap conclusions. |
| `consumer_only_mapping` | The table has task mappings, but all mappings are input/consumer, with no output/producer. |
| `lineage_without_task_mapping` | The table has upstream or downstream lineage but no `task_tables` mapping. |
| `no_lineage_no_task_mapping` | The table has no lineage and no task mapping; it may be isolated, stale, unsupported, or abandoned. |
| `producer_missing_gap` | The table is in a valid warehouse layer and has no producer task, without a more specific signal. |
| `producer_present_run_missing` | A producer exists; the issue is not producer mapping and should be routed toward run diagnosis. |
| `cache_stale_or_missing_mapping` | Live evidence can find producer tasks but cached `task_tables` cannot. |
| `live_evidence_unavailable` | Cache evidence is insufficient and live evidence was requested but unavailable. |

## 5. Evidence sources

Diagnosis supports three evidence layers.

### Level 1: cache facts

Default for bulk views. Uses local materialized facts:

- `tables`
- `task_tables`
- `lineage`
- `task_runs`
- `data_source_tasks`
- `quality_rules`

### Level 2: patrol live context

When diagnosis is generated during patrol, reuse evidence already collected by `PatrolService`, such as live table tasks and live production status. Do not call the same live API again just to diagnose.

### Level 3: on-demand live evidence

When evidence is insufficient, allow live补证 if explicitly enabled. Live补证 may be triggered when:

1. The table is in a valid warehouse layer, has no producer task and no task mapping, but has lineage or downstream usage.
2. The table is in `ads`, `dws`, or `dwd`, has complete fields/data-source evidence, but no producer task or run.
3. Sync health indicates task coverage is partial or cache evidence is stale.
4. The caller explicitly requests live diagnosis, for example with `live=true`.
5. Patrol is already operating in a live evidence context.

Live evidence must be bounded and visible in output. Bulk APIs should not perform broad live补证 by default.

## 6. Live evidence behavior

When live补证 is enabled:

- Prefer existing live task lookup capabilities, such as `get_table_tasks_live(table_name)`.
- If live returns producer tasks while cache has none, classify as `cache_stale_or_missing_mapping`.
- If live also finds no producer task, keep the cache-derived root cause and mark `live_checked=true`.
- If live fails, keep the cache-derived diagnosis where possible, mark `live_checked=false`, and include `live_error`.
- If cache evidence is insufficient and live fails, classify as `live_evidence_unavailable`.

Example live-stale evidence:

```json
{
  "root_cause": "cache_stale_or_missing_mapping",
  "evidence_source": "cache+live",
  "evidence": {
    "cache_producer_task_count": 0,
    "live_producer_task_count": 1,
    "live_checked": true
  },
  "next_check": "刷新 task_tables 缓存或修复同步链路，live 已能找到产出任务。"
}
```

## 7. Integration points

### 7.1 `list_asset_coverage_gaps(gap_type="producer_tasks")`

Each producer gap item should include:

- `suspected_root_cause`
- `recommended_next_check`
- `producer_diagnosis`

This is the primary data-platform work queue for coverage repair.

### 7.2 `get_asset_governance_issue_inventory`

For `missing_producer_task`, include the diagnosis in structured evidence. Markdown output should surface the root cause and next check so the issue inventory can be grouped by root cause instead of only by issue type.

### 7.3 Patrol findings

When `PatrolService` emits `missing_producer_task`, include the producer diagnosis in finding evidence. If patrol already collected live tasks, reuse that live context instead of making another live call.

### 7.4 Table risk and production-risk diagnosis

Where table risk or production-risk outputs already show producer counts and run gaps, include producer diagnosis only when producer mapping is relevant. If producer exists, route users toward run-instance diagnosis instead.

## 8. Error handling and guardrails

- Missing numeric fields default to `0`.
- Missing layer defaults to `unknown`.
- Diagnosis must not turn missing data into a healthy result.
- A missing producer remains a gap unless live evidence proves cached mapping is stale.
- Live API failure must not fail the whole coverage, patrol, or governance report.
- Every diagnosis must state its evidence source: `cache`, `live`, `cache+live`, or `patrol_live_context`.
- Owner attribution continues to use existing owner-resolution logic; this feature does not infer owner from table names.
- Batch reports should not make unbounded live calls. Live补证 should be explicit, reused from patrol context, or capped to a small high-priority subset.

## 9. Testing plan

### 9.1 Pure diagnosis tests

Add tests for the diagnosis helper covering:

- `unknown_layer_first`
- `consumer_only_mapping`
- `lineage_without_task_mapping`
- `no_lineage_no_task_mapping`
- `producer_missing_gap`
- `producer_present_run_missing`
- `cache_stale_or_missing_mapping`
- `live_evidence_unavailable`

### 9.2 Coverage gap tests

Extend coverage-gap tests to assert producer-task gaps include:

- `suspected_root_cause`
- `recommended_next_check`
- `producer_diagnosis`

### 9.3 Governance inventory tests

Extend existing `missing_producer_task` tests so governance output exposes root cause, next check, and evidence source.

### 9.4 Patrol tests

Add patrol tests verifying:

- `missing_producer_task` findings include `producer_diagnosis`.
- Patrol reuses already-collected live task evidence.
- Live task API failure still produces a finding with live error evidence.

### 9.5 No real API dependency

All live补证 tests should use fake live objects. The test suite must remain deterministic and not require Tencent Cloud or WeData credentials.

## 10. Acceptance criteria

This phase is complete when:

1. `missing_producer_task` outputs include root cause, evidence source, and next check.
2. Producer gaps can distinguish at least these cases:
   - only consumer tasks exist;
   - lineage exists but task mapping is absent;
   - neither lineage nor task mapping exists;
   - live can find producer tasks but cache cannot;
   - live evidence was requested but unavailable.
3. Live补证 is controlled:
   - bulk views default to cache-only;
   - explicit live mode or patrol live context can enrich diagnosis;
   - live failures degrade gracefully.
4. Existing public outputs remain backward compatible: current fields stay present, with diagnosis added as extra structured evidence.
5. `python -m pytest` passes.

## 11. Future work

After diagnosis shows the dominant root causes, consider a second phase focused on coverage improvement:

- Fix SQL parser gaps.
- Improve task output extraction.
- Normalize database-qualified table names more aggressively.
- Add controlled cache refresh for task mappings.
- Build a focused repair queue for `cache_stale_or_missing_mapping` cases.
