# Asset Governance Issue Workflow Design

Date: 2026-07-10

## Context

The project has reached the point where service-side WeData data has been pulled into the asset store. Current visible issues are real asset-governance conditions, not failures to hide:

- Quality rules are low: 62 from the latest service asset inspection.
- Unknown-layer tables remain high: 2141 from the latest service asset inspection.
- `ListTablePartitions` returns `InvalidAction` on WeData `2025-08-06`; this is an action/version unsupported condition, not a parameter error.
- Some real tables lack task mappings or run instances; these should be treated as real mapping/runtime coverage gaps, not task-derived fake table artifacts.

The next phase should expose these facts clearly, classify root causes, let an LLM propose governance plans from evidence, and validate a fixed set of core candidate tables end to end.

## Goals

- Add a deterministic issue inventory for real asset-governance gaps.
- Upgrade the daily governance report so it summarizes the issue inventory and groups actions.
- Add a project skill that tells the LLM how to turn issue evidence into a governance plan.
- Add a core-asset validation report for 20 candidate tables.
- Keep facts and recommendations separated: code produces evidence; the LLM produces plans from that evidence.

## Non-goals

- Do not hide real gaps or convert them into success states.
- Do not let the LLM invent issue facts, owners, or evidence.
- Do not treat `ListTablePartitions InvalidAction` as a payload parameter problem.
- Do not reclassify real missing task/run coverage as fake table cleanup.
- Do not build a web UI, ticket integration, automatic WeData mutation, or messaging workflow in the first version.
- Do not require partition facts for P0 governance while the current WeData action/version is unsupported.

## Design Overview

Implement a four-layer governance loop:

```text
Issue inventory -> Rule-based root-cause classification -> LLM governance plan -> Core-table validation
```

- **Issue inventory** is deterministic and queryable through MCP/CLI.
- **Root-cause classification** is rule-based and evidence-backed.
- **Governance planning** is handled by a project skill that consumes issue evidence.
- **Validation** runs fixed end-to-end checks on core candidate tables.

## Component 1: Deterministic Issue Inventory

Add an `AssetStore` method and MCP tool:

```text
get_asset_governance_issue_inventory(layer="", core_level="", issue_type="", limit=100)
```

### Supported Issue Types

- `unknown_layer`
- `missing_quality_rules`
- `missing_task_mapping`
- `missing_task_runs`
- `missing_data_source`
- `missing_owner`
- `partition_unsupported`
- `profile_incomplete`

### Issue Shape

Each issue returns a structured item:

```json
{
  "issue_type": "missing_quality_rules",
  "asset_type": "table",
  "asset_name": "ads_xxx",
  "layer": "ads",
  "owner": "owner_name",
  "severity": "P0",
  "evidence": {
    "quality_rule_count": 0,
    "downstream_count": 8,
    "task_count": 2,
    "run_count": 1
  },
  "suspected_root_cause": "source_governance_gap",
  "recommended_next_check": "Compare raw quality rules with DB rules for this table."
}
```

### Severity Rules

Use simple deterministic severity rules:

- `P0`: core-level `P0/P1`, high downstream impact, or production-risk-related gap.
- `P1`: important table, has downstream dependencies, or belongs to ads/dws/dwd without key governance facts.
- `P2`: lower-impact or evidence-insufficient gap.

### Root-Cause Rules

Initial rule mapping:

| Issue | Root-cause candidates |
| --- | --- |
| `unknown_layer` | `parser_gap`, `source_metadata_gap`, `manual_mapping_needed` |
| `missing_quality_rules` | `source_governance_gap`, `sync_scope_gap`, `parser_gap` |
| `missing_task_mapping` | `parser_gap`, `source_mapping_gap`, `name_normalization_gap` |
| `missing_task_runs` | `instance_window_gap`, `pagination_gap`, `task_id_alignment_gap`, `not_run` |
| `missing_data_source` | `source_metadata_gap`, `parser_gap`, `manual_mapping_needed` |
| `missing_owner` | `source_metadata_gap`, `owner_governance_gap` |
| `partition_unsupported` | `api_unsupported` |
| `profile_incomplete` | aggregate of missing profile facts |

The first version can choose one primary `suspected_root_cause` from available evidence and include the rest in `evidence.notes` when relevant.

## Component 2: Daily Governance Report Upgrade

Enhance:

```text
get_asset_governance_daily_report(instance_date="", layer="", core_level="")
```

Add an issue-inventory summary:

- `issue_summary_by_type`
- `issue_summary_by_severity`
- `issue_summary_by_owner`
- top P0 issues
- responsibility buckets:
  - data platform
  - warehouse owner
  - BI owner
  - business owner
  - unknown owner

The report should keep existing production risks, coverage gaps, quality gaps, owner gaps, lifecycle watch items, and expert review queue.

### Daily Report Narrative

Markdown/rendered output should make the state explicit:

- These are real current governance gaps.
- `62` and `2141`, when supplied to diagnostics, are service inspection baselines.
- Partition action unsupported is an API/action-version limitation.
- Missing task/run coverage is a real mapping/runtime coverage issue.

## Component 3: Project Governance Skill

Create a project skill:

```text
.claude/skills/data-asset-governance/SKILL.md
```

### Trigger

Use when the user asks to analyze data asset governance gaps, prepare a governance plan, classify issue inventory, or decide next actions for exposed WeData/DLC asset gaps.

### Skill Workflow

The skill instructs the model to:

1. Obtain or ask for issue inventory from `get_asset_governance_issue_inventory` or `diagnose_asset_gaps`.
2. Group issues by severity, issue type, owner, and root cause.
3. Produce a governance plan with evidence references.
4. Separate deterministic facts from LLM recommendations.
5. List next checks and acceptance criteria.

### Skill Guardrails

The skill must state:

- Do not invent issue facts or owners.
- Do not treat absent data as healthy.
- Do not treat `ListTablePartitions InvalidAction` as a parameter problem.
- Do not treat real missing task/run coverage as fake-table cleanup.
- Every recommendation must cite issue evidence.
- If evidence is insufficient, recommend the next check rather than guessing.

### Skill Output Format

```markdown
# 数据资产治理方案

## 1. 总体判断

## 2. P0 本周必须处理

## 3. P1 下周推进

## 4. P2 观察或排期

## 5. 按责任方拆解

## 6. 建议执行顺序

## 7. 验收标准

## 8. 需要人工确认的问题
```

## Component 4: Core Candidate Validation Report

Add a CLI:

```bash
python3 -m dlc_mcp.validate_core_assets \
  --db /data/dlc-mcp/assets.db \
  --limit 20 \
  --output /data/dlc-mcp/reports/core_asset_validation.md
```

### Input Selection

Select up to 20 tables in this priority:

1. Expert-labeled core candidates ordered by core level.
2. High-scoring asset value candidates.
3. High downstream-impact tables.
4. ads/dws/dwd tables with quality or runtime gaps.

### Per-Table Checks

Each table report includes:

- table profile summary
- core-table decision
- asset value profile
- quality status
- production status
- production risk detail
- owner profile
- issue inventory entries for that table

### Per-Table Output

```markdown
## ads_xxx

- 画像完整度：80%
- 核心判断：P1 / L1
- 质量状态：缺规则 / 有规则
- 生产状态：成功 / 失败 / 未运行 / 未知
- 风险解释：...
- 当前缺口：
  - 缺质量规则
  - 缺运行实例
- 建议动作：
  - 数仓 Owner 补质量规则
  - 数据平台扩大实例同步窗口
```

## Data Flow

```text
SQLite facts + raw sync evidence
  -> AssetStore issue inventory
  -> MCP tool / CLI report
  -> daily governance report
  -> data-asset-governance skill
  -> governance plan
  -> validate_core_assets report
  -> OKR acceptance evidence
```

## Error Handling

- Empty asset store: return empty issue inventory with a clear `asset_catalog_missing` note.
- Missing raw dumps: inventory still returns DB-derived issues; root cause should say evidence is insufficient where raw comparison is required.
- Partition `InvalidAction`: return `partition_unsupported` with root cause `api_unsupported`.
- Unknown owner: group under `unknown owner`; do not invent owner.
- Invalid issue type: return supported issue types and no results.

## Tests

Add tests for:

- Inventory lists unknown-layer tables.
- Inventory lists missing quality-rule tables with evidence.
- Inventory lists missing task mappings and missing task runs separately.
- Inventory returns `partition_unsupported` when partition raw or sync result contains `InvalidAction`.
- Daily governance report includes issue summaries.
- MCP exposes `get_asset_governance_issue_inventory`.
- Skill file includes required guardrails.
- Core validation CLI renders 20-table markdown with profile, core decision, quality, production, risk, and recommendations.

## Acceptance Criteria

- Users can ask for real governance gaps and receive a structured issue inventory.
- Daily governance report includes issue counts by type/severity/owner.
- The LLM governance skill can generate a plan from evidence without inventing facts.
- The 20-table validation report can be generated from the service DB.
- `ListTablePartitions InvalidAction` is consistently reported as action/version unsupported.
- Missing task/run coverage remains classified as real mapping/runtime coverage gaps.
