# Lineage Task Table Reconciliation Design

Date: 2026-07-21

## 1. Goal

Add a conservative reconciliation capability that derives missing `task_tables` mappings from already-synced lineage rows when the lineage `via` value is a known WeData task id.

This targets the dominant producer diagnosis category found after the 2026-07-21 `daily_core` patrol: `lineage_without_task_mapping`. In these cases the asset graph already knows that a table has upstream/downstream lineage, but `task_tables` has no producer mapping for the same task chain.

## 2. Evidence

Observed examples:

- `ads_360_fin_income_cost_1d_di`
  - upstream count: 26
  - downstream count: 13
  - task count: 0
  - lineage `via` includes numeric task id `20250808125219242`

- `ads_label_customer_relation_df`
  - upstream count: 47
  - downstream count: 71
  - task count: 0
  - lineage `via` includes numeric task id `20250808121006578`
  - fetched task code contains `INSERT OVERWRITE TABLE ads_label_customer_relation_df PARTITION (...)`

- `consumer_only_mapping` samples such as `ads_360_call_job_history_1d` and `ads_line_sku_complaint_record_30d_di` have task mappings but no output producer; task code fetch failed because the task type does not support code inspection. These samples strengthen the need to rely on lineage/task metadata, not only SQL code parsing.

## 3. Non-goals

This phase does not:

- Parse SQL.
- Call live APIs.
- Process non-numeric lineage `via` values.
- Create missing tasks.
- Delete or overwrite existing `task_tables` rows.
- Modify `tasks`, `lineage`, or `task_runs` rows.
- Automatically run during incremental sync.
- Expose a write operation through MCP.

## 4. Core behavior

Add an `AssetStore` method:

```python
reconcile_task_tables_from_lineage(limit=100, apply=False, table="") -> dict
```

Default behavior is dry-run. It returns the candidate mappings and counts without writing to the database.

When `apply=True`, it inserts missing `task_tables` rows and matching `asset_edges` rows.

## 5. CLI

Add a small admin CLI module:

```bash
python -m dlc_mcp.reconcile_lineage_task_tables \
  --db /data/dlc-mcp/assets.db \
  --limit 100
```

Default is dry-run.

Apply mode:

```bash
python -m dlc_mcp.reconcile_lineage_task_tables \
  --db /data/dlc-mcp/assets.db \
  --limit 100 \
  --apply
```

Single-table validation:

```bash
python -m dlc_mcp.reconcile_lineage_task_tables \
  --db /data/dlc-mcp/assets.db \
  --table ads_360_fin_income_cost_1d_di \
  --apply
```

The `--table` filter matches either `lineage.upstream` or `lineage.downstream`.

## 6. Candidate selection

Read lineage rows where:

- `upstream` is non-empty.
- `downstream` is non-empty.
- `via` starts with a digit at the SQL prefilter layer.
- `str(via).isdigit()` is true in Python.
- A task exists in `tasks` with `id = via`.

SQL may use a broad prefilter such as:

```sql
select upstream, downstream, via
from lineage
where upstream <> ''
  and downstream <> ''
  and via glob '[0-9]*'
limit ?
```

Because SQLite `glob '[0-9]*'` only guarantees the first character is numeric, Python must enforce `isdigit()` before generating a candidate.

## 7. Mapping rules

For a qualifying lineage row:

```text
upstream   -> task_tables(task_id=via, table_name=upstream, direction='input')
downstream -> task_tables(task_id=via, table_name=downstream, direction='output')
```

If a mapping already exists, skip it and increment `skipped_existing_count`.

If `tasks.id = via` does not exist, skip the lineage row and increment `skipped_missing_task_count`.

Use `insert or ignore` in apply mode so the operation is idempotent.

## 8. Asset edges

In apply mode, add `asset_edges` consistently with `upsert_task()` behavior:

- input mapping:
  - `source_type = 'task'`
  - `source_id = task_id`
  - `target_type = 'table'`
  - `target_id = upstream`
  - `relation_type = 'reads_table'`
  - `evidence_source = 'lineage_task_id'`
  - `confidence = 'high'`

- output mapping:
  - `source_type = 'task'`
  - `source_id = task_id`
  - `target_type = 'table'`
  - `target_id = downstream`
  - `relation_type = 'writes_table'`
  - `evidence_source = 'lineage_task_id'`
  - `confidence = 'high'`

Evidence JSON:

```json
{
  "lineage_upstream": "dws_360_fin_job_line_1d_di",
  "lineage_downstream": "ads_360_fin_income_cost_1d_di",
  "via": "20250808125219242",
  "direction": "output"
}
```

## 9. Return shape

The reconciliation method returns:

```json
{
  "dry_run": true,
  "table": "",
  "limit": 100,
  "candidate_task_count": 2,
  "candidate_mapping_count": 4,
  "inserted_count": 0,
  "skipped_existing_count": 3,
  "skipped_missing_task_count": 5,
  "samples": [
    {
      "task_id": "20250808125219242",
      "table_name": "ads_360_fin_income_cost_1d_di",
      "direction": "output",
      "lineage": {
        "upstream": "dws_360_fin_job_line_1d_di",
        "downstream": "ads_360_fin_income_cost_1d_di",
        "via": "20250808125219242"
      }
    }
  ]
}
```

`samples` should be bounded, for example to the first 20 candidate mappings, to keep CLI output readable.

## 10. Safety and idempotency

- Dry-run is the default.
- `--apply` is required for writes.
- Only numeric `via` values are candidates.
- Only existing tasks are candidates.
- Existing mappings are not overwritten.
- No delete operations are performed.
- No live API calls are performed.
- `limit` defaults to 100 to avoid large accidental writes.
- The method is idempotent; running apply repeatedly does not duplicate mappings.

## 11. Tests

Add tests covering:

1. Dry-run does not write:
   - `tasks`: `task_1`
   - `lineage`: `ods_a -> ads_b via task_1`
   - Expected candidate mapping count: 2
   - Expected inserted count: 0
   - `get_table_tasks('ads_b')` remains empty

2. Apply writes input/output:
   - Same setup
   - Expected `ods_a` has an input task mapping
   - Expected `ads_b` has an output task mapping
   - Expected `asset_edges` includes `reads_table` and `writes_table`

3. Non-numeric `via` is ignored:
   - `via = 'ads_b'`
   - No candidates

4. Missing task id is skipped:
   - `via = '20250808125219242'`
   - No matching task in `tasks`
   - `skipped_missing_task_count = 1`
   - No writes

5. CLI dry-run:
   - Uses a temporary SQLite database
   - Prints JSON with `dry_run: true`

6. CLI apply:
   - Uses a temporary SQLite database
   - Prints JSON with `dry_run: false`
   - Writes mappings

## 12. Acceptance criteria

The phase is complete when:

1. `python -m pytest` passes locally.
2. Server dry-run reports candidate mappings:
   ```bash
   python3 -m dlc_mcp.reconcile_lineage_task_tables \
     --db /data/dlc-mcp/assets.db \
     --limit 50
   ```
3. Single-table apply succeeds for a sample table:
   ```bash
   python3 -m dlc_mcp.reconcile_lineage_task_tables \
     --db /data/dlc-mcp/assets.db \
     --table ads_360_fin_income_cost_1d_di \
     --apply
   ```
4. After apply, `get_table_tasks('ads_360_fin_income_cost_1d_di')` shows an output producer task.
5. The sample table no longer appears as `lineage_without_task_mapping` in producer-task coverage gaps.

## 13. Future work

After this dry-run/apply admin flow proves safe, consider:

- Adding a feature-flagged sync step after incremental sync.
- Reporting missing numeric task ids as unresolved lineage-task links.
- Comparing mappings derived from SQL parser vs lineage task id.
- Tracking how many producer gaps are repaired by `lineage_task_id` evidence.
