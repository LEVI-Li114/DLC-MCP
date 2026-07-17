---
name: data-asset-governance
description: Use when analyzing exposed WeData/DLC asset governance gaps, classifying issue inventory, or preparing an evidence-backed governance plan for data assets.
---

# Data Asset Governance

Use this skill when the user asks to analyze data asset governance gaps, produce a governance plan, classify exposed issues, or decide next actions for WeData/DLC asset quality and coverage problems.

## Operating Boundary

- Normal data queries must go through the `dlc-mcp` MCP server.
- Do not use `ssh`, `curl`, direct SQLite reads, or ad hoc scripts to answer ordinary data questions.
- Use `ssh` only for deployment, backfill/sync jobs, gateway restart, process checks, or server log inspection.
- Treat SQLite as an asset cache/materialized graph, not as absolute truth when live evidence is requested.
- DDL must come from actual synced or live-refreshed columns; do not infer DDL from table names.

## Required Inputs

Obtain deterministic issue evidence before making recommendations. Prefer:

1. MCP: `get_asset_governance_issue_inventory(layer="", core_level="", issue_type="", limit=100)`
2. CLI/report: `python3 -m dlc_mcp.diagnose_asset_gaps ...`
3. Daily report: `get_asset_governance_daily_report(instance_date="", layer="", core_level="")`

If issue evidence is unavailable, ask the user to run one of these first. Do not invent issue facts or owners.

## Query Playbooks

### Data Source Inventory

When the user asks for one data source's tasks, tables, or DDL:

1. Use `get_data_source_inventory(data_source_name=..., live=true)` or `get_data_source_inventory(data_source_id=..., live=true)`.
2. Report data source id, type, owner, task count, table count, unresolved task count, and missing-field table count.
3. Label gaps explicitly as parsed, unresolved, or missing fields.
4. Include SQL DDL only for tables with real columns.
5. If the result has unresolved tasks or missing fields, explain whether the issue is API coverage, parser coverage, stale cache, or missing live refresh evidence.

### Table Diagnosis

When the user asks about one table:

1. Use `get_table_profile(table_name=..., live=true)`.
2. Use `list_table_columns(table_name=..., live=true)` when fields or DDL matter.
3. Use `get_table_tasks(table_name=...)` for producer/consumer tasks.
4. Use `get_table_lineage(table_name=..., live=true)` for upstream/downstream impact.
5. Use `get_table_production_status(table_name=..., instance_date=..., live=true)` or `get_table_production_risk_detail(...)` when execution status matters.

### Coverage and Governance Gaps

When the user asks why data is incomplete or asks for an asset patrol:

1. Use `get_sync_health()`.
2. Use `get_asset_coverage()`.
3. Use `list_asset_coverage_gaps(gap_type=..., layer=..., limit=...)`.
4. Use `get_asset_governance_issue_inventory(...)` for deterministic issue grouping.
5. Distinguish missing source API data, parser loss, stale cache, missing task/run coverage, and intentionally unsupported API actions.

## Guardrails

- Do not invent issue facts or owners.
- Do not treat absent data as healthy.
- Do not treat `ListTablePartitions InvalidAction` as a parameter problem; classify it as action/version unsupported.
- Do not treat real missing task/run coverage as fake-table cleanup.
- Every recommendation must cite issue evidence.
- If evidence is insufficient, recommend the next check rather than guessing.
- Separate deterministic facts from LLM recommendations.
- Say whether evidence came from cached asset facts, live MCP refresh, or a server-side sync/admin check.

## Workflow

1. Read the issue inventory or diagnostic report.
2. Group issues by severity, issue type, owner, and suspected root cause.
3. Identify P0 issues for this week.
4. Split actions by responsibility bucket: data platform, warehouse owner, BI owner, business owner, unknown owner.
5. Recommend next checks only when evidence is insufficient.
6. Provide acceptance criteria for each action.

## Output Format

```markdown
# 数据资产治理方案

## 1. 总体判断

State what is known from evidence. Do not hide real gaps.

## 2. P0 本周必须处理

For each issue group: evidence, why P0, owner bucket, action, acceptance criteria.

## 3. P1 下周推进

For each issue group: evidence, owner bucket, action, acceptance criteria.

## 4. P2 观察或排期

Lower-impact or evidence-insufficient issues.

## 5. 按责任方拆解

- 数据平台
- 数仓 Owner
- BI Owner
- 业务 Owner
- unknown owner

## 6. 建议执行顺序

Order actions by dependency and impact.

## 7. 验收标准

List measurable checks, such as issue counts reduced, core table profile completeness improved, and risk explanations available.

## 8. 需要人工确认的问题

Only list items whose evidence is insufficient or owner is unknown.
```
