# Data Gap Remediation Design

Date: 2026-07-10

## Context

The latest service asset inspection reports four prominent data gaps:

1. Quality rules are limited to 62, with low coverage across synced tables.
2. Unknown-layer tables remain high at 2141.
3. Partition data still needs isolated WeData API parameter validation.
4. Some real tables lack task mappings or run instances; this is no longer treated as task-derived fake table creation.

The values `62` and `2141` are service-side inspection baselines, not local demo database values. Local `data/assets.db` remains a seed/demo database and must not be used as the real service baseline.

## Goals

- Add a read-only diagnostic capability that explains the four data gaps before changing sync behavior.
- Make reports explicitly label service inspection baselines such as `62` quality rules and `2141` unknown-layer tables.
- Classify whether each gap is caused by WeData source data, sync scope, raw dump absence, parser/import mapping, naming mismatch, or runtime window limits.
- Prepare targeted follow-up fixes in `dlc_mcp/wedata.py`, `dlc_mcp/sync_wedata.py`, and `dlc_mcp/check_foundation.py` once the diagnosis is in place.

## Non-goals

- Do not automatically mutate or backfill service data during diagnosis.
- Do not run a full partition sync by default.
- Do not assume local `data/assets.db` represents service reality.
- Do not classify real tables missing tasks/runs as fake task-derived tables.

## Recommended approach

Use a two-phase approach:

1. Build a read-only diagnostic tool and report.
2. Use the diagnostic output to guide targeted parser and sync improvements.

This avoids blind changes to WeData payloads or table parsing while still giving operators an actionable report.

## Proposed CLI

Add a module such as:

```bash
python3 -m dlc_mcp.diagnose_asset_gaps \
  --db /data/dlc-mcp/assets.db \
  --sync-dir /data/dlc-mcp/sync \
  --report-source "latest service asset inspection" \
  --quality-rule-count 62 \
  --unknown-layer-count 2141
```

The command prints Markdown. It reads SQLite and available raw WeData dumps. It does not call external APIs by default.

## Inputs

### SQLite asset database

The diagnostic tool reads:

- `tables`
- `columns`
- `quality_rules`
- `task_tables`
- `tasks`
- `task_runs`
- `table_partitions`
- `expert_labels`

### Raw WeData dump files

If present, the diagnostic tool reads:

- `wedata_tables.json`
- `wedata_metadata.json`
- `wedata_task_instances.json`
- `wedata_table_partitions.json`
- `wedata_tasks.json`

If raw dumps are missing, the report states that diagnosis is DB-only and cannot distinguish source API absence from parser/import loss.

## Output structure

The Markdown report contains:

1. Inspection source and baseline values.
2. Quality rule coverage diagnosis.
3. Unknown-layer diagnosis.
4. Partition parameter validation guidance.
5. Task/run gap diagnosis.
6. Recommended next actions.

The first section must state that `62` and `2141` come from the latest service asset inspection when those CLI arguments are supplied.

## Quality rule diagnosis

The tool calculates:

- Total rules in `quality_rules`.
- Number of tables with at least one rule.
- Coverage by layer.
- Tables with columns but no rules.
- Core candidates with no rules.
- Raw quality rule item count from metadata dumps when available.

Root-cause categories:

1. Source governance gap: raw dump count is also low.
2. Sync scope too small: metadata table limits or sampled tables constrain `ListQualityRules` calls.
3. Parser/import loss: raw rule count is higher than DB rule count.
4. Table-name mismatch: quality rule table names do not join to `tables.name` after normalization.

Follow-up fixes may extend `_quality_rule_from_api` in `dlc_mcp/wedata.py`, but only after the diagnostic report shows parser/import loss or name mismatch.

## Unknown-layer diagnosis

The tool calculates:

- Tables whose `layer` is empty or `unknown`.
- Sample unknown-layer tables.
- Whether sampled raw records contain usable layer, database, source, folder, path, or project fields.
- Whether layer can be inferred from normalized table name or database/path tokens.

Candidate inference sources:

- Explicit fields: `Layer`, `TableLayer`, `BizLayer`, `DataLayer`, `layer`.
- Database fields: `DatabaseName`, `Database`, `DbName`, `SchemaName`.
- Path/category fields: `FolderName`, `FolderPath`, `CategoryName`, `ProjectName`.
- Source fields: `DatasourceName`, `DataSourceName`.
- Table name prefixes: `ods_`, `dim_`, `dwd_`, `dws_`, `ads_`.

Root-cause categories:

1. Parser fixable from table name.
2. Parser fixable from database/path/source fields.
3. Parser fixable from unrecognized explicit layer fields.
4. WeData `ListTable` information is insufficient for automatic layer inference.

Follow-up fixes may extend `_table_from_api`, `_normalize_table_name`, and `_layer_from_name` in `dlc_mcp/wedata.py`.

## Partition parameter diagnosis

The diagnostic tool does not run a full partition sync. It emits candidate payloads for a small sample of real tables.

Candidate payload shapes:

```json
{"ProjectId":"...","TableName":"..."}
{"ProjectId":"...","TableGuid":"..."}
{"ProjectId":"...","DatabaseName":"...","TableName":"..."}
{"ProjectId":"...","DataSourceId":"...","DatabaseName":"...","TableName":"..."}
```

If `wedata_table_partitions.json` exists, the tool reports:

- Item count.
- Error responses.
- Tables with successful partition results.
- Whether partition names, dates, row counts, storage bytes, and file counts parse into `table_partitions`.

Root-cause categories:

1. Partition sync is not enabled.
2. Action name may be wrong; current default is configurable via `WEDATA_PARTITION_ACTION`.
3. Payload lacks required identifiers.
4. Raw response exists but parser/import mapping is insufficient.

Follow-up fixes may add configurable partition payload modes in `dlc_mcp/sync_wedata.py` after service-side validation confirms which payload succeeds.

## Task and run gap diagnosis

The tool classifies missing task/run coverage in stages:

1. Table exists but has no `task_tables` rows.
2. Table has task mappings but no `task_runs` rows.
3. Raw task instances contain matching task IDs, but DB rows are missing.
4. Table/task names match only after normalization.
5. Runtime window, keyword filters, or max-pages settings likely excluded instances.

Normalization checks include:

- `db.table` versus `table`.
- Backticks and quotes.
- Case differences.
- Environment or schema prefixes.

Root-cause categories:

1. Task input/output fields or SQL were not parsed.
2. Table-name normalization mismatch.
3. Instance window does not cover recent runs.
4. Instance keyword or page limit truncated results.
5. WeData source lacks visible task/run data for the table.

The report must explicitly state that these are real synced tables requiring mapping/runtime diagnosis, not task-derived fake table cleanup.

Follow-up fixes may extend `_task_table_names`, `_normalize_table_name`, and SQL table extraction in `dlc_mcp/wedata.py`, plus instance sync diagnostics in `dlc_mcp/sync_wedata.py`.

## Error handling

- Missing DB file: fail with a clear message.
- Missing raw dumps: continue with DB-only diagnosis.
- Malformed raw JSON: report the specific file and skip raw-derived checks for that file.
- Empty tables: report that asset catalog sync must be fixed first.
- External API calls: not performed by default.

## Tests

Add tests for:

- Report source and baseline values: `62` and `2141` appear as service inspection baselines.
- Quality-rule diagnosis when DB count is low and raw count is equal.
- Quality-rule parser-loss diagnosis when raw count is higher than DB count.
- Unknown-layer diagnosis from table name, database/path fields, and insufficient raw data.
- Partition payload emission without external API calls.
- Task/run gap classification for no mapping, mapping without runs, and instance raw mismatch.
- Parser improvements for layer aliases, database/path layer inference, table-name normalization, and quality rule field aliases.

## Implementation sequence after approval

1. Add diagnostic data collection helpers.
2. Add Markdown rendering for the four sections.
3. Add CLI argument parsing.
4. Add tests for the diagnostic report.
5. Add targeted parser tests for known likely fixes.
6. Implement parser/sync enhancements only where tests and diagnosis justify them.
7. Run the existing test suite plus new tests.

## Acceptance criteria

- A service operator can run one command and get a Markdown report explaining the four gaps.
- The report labels `62` and `2141` as latest service inspection baselines when supplied.
- The report distinguishes DB-only diagnosis from raw-dump-backed diagnosis.
- Unknown-layer tables are classified as parser-fixable or API/source-insufficient.
- Quality-rule gaps are classified as source governance, sync scope, parser/import loss, or name mismatch.
- Partition validation remains bounded and does not trigger full sync by default.
- Real tables missing task/run data are diagnosed without reintroducing fake task-derived table assumptions.
