# Asset Governance Issue Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic data-asset governance issue inventory, surface it in the daily report, add a governance-analysis skill, and generate a 20-table core asset validation report.

**Architecture:** Keep deterministic facts in `AssetStore` and MCP tools, not in LLM prompts. Add a small issue-classification layer inside `dlc_mcp/assets.py`, expose it through `dlc_mcp/mcp.py`, consume it from the daily report and a new `validate_core_assets` CLI, then add a project skill that turns evidence into a governance plan.

**Tech Stack:** Python standard library, SQLite, existing `AssetStore`, existing MCP JSON-RPC server, Markdown rendering, unittest/pytest, Superpowers skill markdown.

## Global Constraints

- Do not hide real gaps or convert them into success states.
- Do not let the LLM invent issue facts, owners, or evidence.
- Do not treat `ListTablePartitions InvalidAction` as a payload parameter problem.
- Do not reclassify real missing task/run coverage as fake table cleanup.
- Do not build a web UI, ticket integration, automatic WeData mutation, or messaging workflow in the first version.
- Do not require partition facts for P0 governance while the current WeData action/version is unsupported.
- Each issue must include evidence.
- Missing raw dumps should not prevent DB-derived issues from being reported.
- Unknown owner must be grouped under `unknown owner`; never invent an owner.

---

## File Structure

- Modify `dlc_mcp/assets.py`: add `get_asset_governance_issue_inventory(...)`, issue helpers, summary helpers for daily report, and core validation candidate helpers.
- Modify `dlc_mcp/mcp.py`: expose `get_asset_governance_issue_inventory` as an MCP tool and route tool calls.
- Modify `tests/test_assets.py`: issue inventory unit tests.
- Modify `tests/test_mcp.py`: MCP tool exposure and call tests.
- Modify `tests/test_check_foundation.py` or add `tests/test_governance_daily_report.py`: daily report issue-summary tests.
- Create `.claude/skills/data-asset-governance/SKILL.md`: project skill for LLM governance planning from evidence.
- Create `tests/test_data_asset_governance_skill.py`: guardrail text test for the skill file.
- Create `dlc_mcp/validate_core_assets.py`: CLI that renders 20-table core candidate validation Markdown.
- Create `tests/test_validate_core_assets.py`: validation CLI/report tests.
- Update `README.md`: add the new MCP tool and CLI to user-facing docs.

---

### Task 1: Deterministic Issue Inventory in AssetStore

**Files:**
- Modify: `dlc_mcp/assets.py`
- Test: `tests/test_assets.py`

**Interfaces:**
- Consumes existing tables: `tables`, `columns`, `quality_rules`, `task_tables`, `task_runs`, `data_sources`, `expert_labels`, `table_partitions`.
- Produces:
  - `AssetStore.get_asset_governance_issue_inventory(layer="", core_level="", issue_type="", limit=100) -> dict`
  - Issue item shape with keys: `issue_type`, `asset_type`, `asset_name`, `layer`, `owner`, `severity`, `evidence`, `suspected_root_cause`, `recommended_next_check`.

- [ ] **Step 1: Write failing issue inventory tests**

Append these tests to `tests/test_assets.py` inside the existing test class or create this class if needed:

```python
import sqlite3
import unittest

from dlc_mcp.assets import AssetStore


class AssetGovernanceIssueInventoryTest(unittest.TestCase):
    def _store(self):
        store = AssetStore(sqlite3.connect(":memory:"))
        store.init_schema()
        return store

    def test_lists_unknown_layer_issue_with_evidence(self):
        store = self._store()
        store.upsert_table({"name": "mystery_daily", "layer": "unknown", "owner": "data-owner"})

        data = store.get_asset_governance_issue_inventory(issue_type="unknown_layer")

        self.assertEqual(data["issue_type"], "unknown_layer")
        self.assertEqual(data["supported_issue_types"][0], "unknown_layer")
        self.assertEqual(len(data["results"]), 1)
        issue = data["results"][0]
        self.assertEqual(issue["issue_type"], "unknown_layer")
        self.assertEqual(issue["asset_type"], "table")
        self.assertEqual(issue["asset_name"], "mystery_daily")
        self.assertEqual(issue["layer"], "unknown")
        self.assertEqual(issue["owner"], "data-owner")
        self.assertEqual(issue["suspected_root_cause"], "manual_mapping_needed")
        self.assertIn("layer", issue["evidence"])

    def test_lists_missing_quality_rule_issue_with_downstream_evidence(self):
        store = self._store()
        store.upsert_table({"name": "ads_revenue", "layer": "ads", "owner": "finance"})
        store.upsert_column("ads_revenue", "amount", "decimal", "", 1)
        store.upsert_lineage("ads_revenue", "report_revenue", "dashboard")

        data = store.get_asset_governance_issue_inventory(issue_type="missing_quality_rules")

        issue = data["results"][0]
        self.assertEqual(issue["issue_type"], "missing_quality_rules")
        self.assertEqual(issue["severity"], "P1")
        self.assertEqual(issue["evidence"]["quality_rule_count"], 0)
        self.assertEqual(issue["evidence"]["downstream_count"], 1)
        self.assertEqual(issue["suspected_root_cause"], "source_governance_gap")

    def test_separates_missing_task_mapping_and_missing_task_runs(self):
        store = self._store()
        store.upsert_table({"name": "ads_no_task", "layer": "ads"})
        store.upsert_table({"name": "ads_no_run", "layer": "ads"})
        store.upsert_task({"id": "task_1", "name": "build_ads_no_run", "outputs": ["ads_no_run"]})

        no_task = store.get_asset_governance_issue_inventory(issue_type="missing_task_mapping")
        no_run = store.get_asset_governance_issue_inventory(issue_type="missing_task_runs")

        self.assertEqual([item["asset_name"] for item in no_task["results"]], ["ads_no_task"])
        self.assertEqual([item["asset_name"] for item in no_run["results"]], ["ads_no_run"])
        self.assertEqual(no_run["results"][0]["suspected_root_cause"], "instance_window_gap")

    def test_filters_by_layer_and_limit(self):
        store = self._store()
        store.upsert_table({"name": "ads_a", "layer": "ads"})
        store.upsert_table({"name": "dwd_b", "layer": "dwd"})

        data = store.get_asset_governance_issue_inventory(layer="ads", issue_type="missing_quality_rules", limit=1)

        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["asset_name"], "ads_a")

    def test_invalid_issue_type_returns_supported_types_and_no_results(self):
        store = self._store()
        store.upsert_table({"name": "ads_a", "layer": "ads"})

        data = store.get_asset_governance_issue_inventory(issue_type="not_real")

        self.assertEqual(data["issue_type"], "not_real")
        self.assertEqual(data["results"], [])
        self.assertIn("missing_quality_rules", data["supported_issue_types"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_assets.py::AssetGovernanceIssueInventoryTest -v
```

Expected: FAIL with `AttributeError: 'AssetStore' object has no attribute 'get_asset_governance_issue_inventory'`.

- [ ] **Step 3: Add issue inventory constants and public method**

Add these near the top-level helper functions or near other governance helpers in `dlc_mcp/assets.py`:

```python
GOVERNANCE_ISSUE_TYPES = [
    "unknown_layer",
    "missing_quality_rules",
    "missing_task_mapping",
    "missing_task_runs",
    "missing_data_source",
    "missing_owner",
    "partition_unsupported",
    "profile_incomplete",
]
```

Add this method inside `AssetStore` after `list_asset_coverage_gaps`:

```python
    def get_asset_governance_issue_inventory(self, layer="", core_level="", issue_type="", limit=100):
        wanted = issue_type or ""
        if wanted and wanted not in GOVERNANCE_ISSUE_TYPES:
            return {
                "issue_type": issue_type,
                "layer": layer,
                "core_level": core_level,
                "limit": limit,
                "supported_issue_types": GOVERNANCE_ISSUE_TYPES,
                "results": [],
                "notes": ["unsupported issue_type; use one of supported_issue_types"],
            }
        issues = []
        candidates = self._governance_issue_candidates(layer, core_level)
        for table in candidates:
            issues.extend(_governance_issues_for_table(table))
            if len(issues) >= limit and wanted:
                break
        issues.extend(self._partition_unsupported_issues())
        if wanted:
            issues = [issue for issue in issues if issue["issue_type"] == wanted]
        issues = issues[:limit]
        return {
            "issue_type": issue_type,
            "layer": layer,
            "core_level": core_level,
            "limit": limit,
            "supported_issue_types": GOVERNANCE_ISSUE_TYPES,
            "results": issues,
            "notes": [
                "Issue inventory is derived from current SQLite facts and does not call external APIs.",
                "Missing facts are reported as governance gaps, not hidden as healthy states.",
            ],
        }
```

- [ ] **Step 4: Add candidate query and partition unsupported helper**

Add these methods inside `AssetStore` near the new public method:

```python
    def _governance_issue_candidates(self, layer="", core_level=""):
        filters = []
        args = []
        if layer:
            filters.append("coalesce(nullif(t.layer, ''), 'unknown') = ?")
            args.append(layer)
        if core_level:
            filters.append("coalesce(el.core_level, '') = ?")
            args.append(core_level)
        where = "where " + " and ".join(filters) if filters else ""
        return [
            dict(row)
            for row in self._all(
                f"""
                select
                    t.name,
                    coalesce(nullif(t.layer, ''), 'unknown') as layer,
                    t.owner,
                    t.data_source_id,
                    coalesce(el.core_level, '') as core_level,
                    coalesce(c.column_count, 0) as column_count,
                    coalesce(q.rule_count, 0) as quality_rule_count,
                    coalesce(d.downstream_count, 0) as downstream_count,
                    coalesce(tt.task_count, 0) as task_count,
                    coalesce(r.run_count, 0) as run_count
                from tables t
                left join expert_labels el on el.asset_type = 'table' and el.asset_name = t.name
                left join (select table_name, count(*) as column_count from columns group by table_name) c on c.table_name = t.name
                left join (select table_name, count(*) as rule_count from quality_rules group by table_name) q on q.table_name = t.name
                left join (select upstream, count(*) as downstream_count from lineage group by upstream) d on d.upstream = t.name
                left join (select table_name, count(distinct task_id) as task_count from task_tables group by table_name) tt on tt.table_name = t.name
                left join (
                    select tt.table_name, count(distinct r.instance_id) as run_count
                    from task_tables tt
                    join task_runs r on r.task_id = tt.task_id
                    where tt.direction = 'output'
                    group by tt.table_name
                ) r on r.table_name = t.name
                {where}
                order by
                    case coalesce(el.core_level, '') when 'P0' then 1 when 'P1' then 2 when 'P2' then 3 else 9 end,
                    downstream_count desc,
                    t.name
                """,
                tuple(args),
            )
        ]

    def _partition_unsupported_issues(self):
        return []
```

- [ ] **Step 5: Add issue construction helpers**

Add these top-level helpers in `dlc_mcp/assets.py` near other helper functions:

```python
def _governance_issues_for_table(table):
    issues = []
    if table.get("layer") in ("", "unknown"):
        issues.append(_governance_issue(table, "unknown_layer", "manual_mapping_needed", "Inspect raw ListTable fields and table naming rules for layer inference."))
    if int(table.get("quality_rule_count") or 0) == 0:
        issues.append(_governance_issue(table, "missing_quality_rules", "source_governance_gap", "Compare raw quality rules with DB rules for this table."))
    if int(table.get("task_count") or 0) == 0:
        issues.append(_governance_issue(table, "missing_task_mapping", "parser_gap", "Check raw task inputs/outputs and SQL table-name normalization."))
    elif int(table.get("run_count") or 0) == 0:
        issues.append(_governance_issue(table, "missing_task_runs", "instance_window_gap", "Check ListTaskInstances time window, max pages, and task_id alignment."))
    if not table.get("data_source_id"):
        issues.append(_governance_issue(table, "missing_data_source", "source_metadata_gap", "Check ListTable data source fields and data source sync coverage."))
    if not table.get("owner"):
        issues.append(_governance_issue(table, "missing_owner", "owner_governance_gap", "Ask table owner or warehouse owner to confirm responsibility."))
    if _profile_incomplete(table):
        issues.append(_governance_issue(table, "profile_incomplete", "profile_coverage_gap", "Prioritize missing profile facts by issue inventory entries."))
    return issues


def _governance_issue(table, issue_type, root_cause, next_check):
    evidence = {
        "layer": table.get("layer", ""),
        "core_level": table.get("core_level", ""),
        "column_count": int(table.get("column_count") or 0),
        "quality_rule_count": int(table.get("quality_rule_count") or 0),
        "downstream_count": int(table.get("downstream_count") or 0),
        "task_count": int(table.get("task_count") or 0),
        "run_count": int(table.get("run_count") or 0),
        "data_source_id": table.get("data_source_id", ""),
    }
    return {
        "issue_type": issue_type,
        "asset_type": "table",
        "asset_name": table.get("name", ""),
        "layer": table.get("layer", ""),
        "owner": table.get("owner") or "unknown owner",
        "severity": _governance_issue_severity(table, issue_type),
        "evidence": evidence,
        "suspected_root_cause": root_cause,
        "recommended_next_check": next_check,
    }


def _governance_issue_severity(table, issue_type):
    if table.get("core_level") in {"P0", "P1"}:
        return "P0"
    if issue_type in {"missing_task_runs", "missing_task_mapping"} and table.get("layer") in {"ads", "dws", "dwd"}:
        return "P1"
    if int(table.get("downstream_count") or 0) >= 5:
        return "P1"
    return "P2"


def _profile_incomplete(table):
    return any(
        int(table.get(key) or 0) == 0
        for key in ("column_count", "quality_rule_count", "task_count")
    ) or not table.get("data_source_id") or not table.get("owner") or table.get("layer") in {"", "unknown"}
```

- [ ] **Step 6: Run issue inventory tests**

Run:

```bash
pytest tests/test_assets.py::AssetGovernanceIssueInventoryTest -v
```

Expected: PASS.

- [ ] **Step 7: Run broader asset tests**

Run:

```bash
pytest tests/test_assets.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit issue inventory**

```bash
git add dlc_mcp/assets.py tests/test_assets.py
git commit -m "Add asset governance issue inventory

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: Expose Issue Inventory Through MCP

**Files:**
- Modify: `dlc_mcp/mcp.py`
- Modify: `README.md`
- Test: `tests/test_mcp.py`

**Interfaces:**
- Consumes: `AssetStore.get_asset_governance_issue_inventory(layer="", core_level="", issue_type="", limit=100) -> dict`.
- Produces MCP tool `get_asset_governance_issue_inventory` with arguments `layer`, `core_level`, `issue_type`, `limit`.

- [ ] **Step 1: Write failing MCP tests**

Append these tests to `tests/test_mcp.py`:

```python
import json
import sqlite3
import unittest

from dlc_mcp.assets import AssetStore
from dlc_mcp.mcp import handle_request


class GovernanceIssueInventoryMcpTest(unittest.TestCase):
    def _store(self):
        store = AssetStore(sqlite3.connect(":memory:"))
        store.init_schema()
        return store

    def test_tools_list_includes_governance_issue_inventory(self):
        store = self._store()
        response = handle_request(store, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

        tool_names = [tool["name"] for tool in response["result"]["tools"]]
        self.assertIn("get_asset_governance_issue_inventory", tool_names)

    def test_can_call_governance_issue_inventory(self):
        store = self._store()
        store.upsert_table({"name": "ads_revenue", "layer": "ads"})

        response = handle_request(
            store,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "get_asset_governance_issue_inventory",
                    "arguments": {"issue_type": "missing_quality_rules", "limit": 10},
                },
            },
        )

        text = response["result"]["content"][0]["text"]
        self.assertIn("missing_quality_rules", text)
        self.assertIn("ads_revenue", text)
```

- [ ] **Step 2: Run MCP tests to verify failure**

Run:

```bash
pytest tests/test_mcp.py::GovernanceIssueInventoryMcpTest -v
```

Expected: FAIL because the tool is not listed or routed.

- [ ] **Step 3: Add MCP tool schema**

In `dlc_mcp/mcp.py`, add this entry to `TOOLS` near other governance tools:

```python
    "get_asset_governance_issue_inventory": {
        "description": "Return deterministic governance issue inventory for real asset gaps, grouped by issue type, layer, core level, and evidence.",
        "schema": {
            "type": "object",
            "properties": {
                "layer": {"type": "string"},
                "core_level": {"type": "string"},
                "issue_type": {"type": "string"},
                "limit": {"type": "integer"},
            },
        },
    },
```

- [ ] **Step 4: Route MCP tool call**

In `_call_tool` in `dlc_mcp/mcp.py`, add this branch near `get_asset_governance_daily_report`:

```python
    elif name == "get_asset_governance_issue_inventory":
        data = store.get_asset_governance_issue_inventory(
            args.get("layer", ""),
            args.get("core_level", ""),
            args.get("issue_type", ""),
            int(args.get("limit", 100)),
        )
```

- [ ] **Step 5: Update README tool table**

Add this row to the README tool table after `list_asset_coverage_gaps`:

```markdown
| `get_asset_governance_issue_inventory(layer, core_level, issue_type, limit)` | Return deterministic governance issues with evidence, suspected root cause, severity, and recommended next check. |
```

- [ ] **Step 6: Run MCP tests**

Run:

```bash
pytest tests/test_mcp.py::GovernanceIssueInventoryMcpTest -v
```

Expected: PASS.

- [ ] **Step 7: Run broader MCP tests**

Run:

```bash
pytest tests/test_mcp.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit MCP exposure**

```bash
git add dlc_mcp/mcp.py tests/test_mcp.py README.md
git commit -m "Expose governance issue inventory MCP tool

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: Daily Governance Report Issue Summaries

**Files:**
- Modify: `dlc_mcp/assets.py`
- Test: `tests/test_assets.py`

**Interfaces:**
- Consumes: `AssetStore.get_asset_governance_issue_inventory(...) -> dict`.
- Produces additional keys in `AssetStore.get_asset_governance_daily_report(...)`:
  - `issue_summary_by_type: dict[str, int]`
  - `issue_summary_by_severity: dict[str, int]`
  - `issue_summary_by_owner: dict[str, int]`
  - `top_governance_issues: list[dict]`
  - `responsibility_buckets: dict[str, list[dict]]`

- [ ] **Step 1: Write failing daily report issue-summary test**

Append this test to `AssetGovernanceIssueInventoryTest` in `tests/test_assets.py`:

```python
    def test_daily_report_includes_governance_issue_summaries(self):
        store = self._store()
        store.upsert_table({"name": "ads_revenue", "layer": "ads", "owner": "finance"})
        store.upsert_table({"name": "unknown_table", "layer": "unknown", "owner": ""})

        report = store.get_asset_governance_daily_report()

        self.assertIn("issue_summary_by_type", report)
        self.assertGreaterEqual(report["issue_summary_by_type"]["missing_quality_rules"], 1)
        self.assertGreaterEqual(report["issue_summary_by_type"]["unknown_layer"], 1)
        self.assertIn("issue_summary_by_severity", report)
        self.assertIn("issue_summary_by_owner", report)
        self.assertIn("unknown owner", report["issue_summary_by_owner"])
        self.assertIn("top_governance_issues", report)
        self.assertIn("responsibility_buckets", report)
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
pytest tests/test_assets.py::AssetGovernanceIssueInventoryTest::test_daily_report_includes_governance_issue_summaries -v
```

Expected: FAIL because daily report has no issue summary fields.

- [ ] **Step 3: Update daily report method**

In `AssetStore.get_asset_governance_daily_report`, after `lifecycle_watch = lifecycle_watch[:20]`, add:

```python
        issue_inventory = self.get_asset_governance_issue_inventory(layer, core_level, "", 100)
        governance_issues = issue_inventory["results"]
        issue_summary_by_type = _governance_issue_counts(governance_issues, "issue_type")
        issue_summary_by_severity = _governance_issue_counts(governance_issues, "severity")
        issue_summary_by_owner = _governance_issue_counts(governance_issues, "owner")
        responsibility_buckets = _governance_responsibility_buckets(governance_issues)
```

Then add these keys to the returned dict:

```python
            "issue_summary_by_type": issue_summary_by_type,
            "issue_summary_by_severity": issue_summary_by_severity,
            "issue_summary_by_owner": issue_summary_by_owner,
            "top_governance_issues": governance_issues[:20],
            "responsibility_buckets": responsibility_buckets,
```

Also add `"governance_issue_count": len(governance_issues),` to the `summary` dict.

- [ ] **Step 4: Add summary helper functions**

Add these top-level helpers near other governance helpers:

```python
def _governance_issue_counts(issues, key):
    counts = {}
    for issue in issues:
        value = issue.get(key) or "unknown"
        counts[value] = counts.get(value, 0) + 1
    return counts


def _governance_responsibility_buckets(issues):
    buckets = {
        "data_platform": [],
        "warehouse_owner": [],
        "bi_owner": [],
        "business_owner": [],
        "unknown_owner": [],
    }
    for issue in issues:
        bucket = _governance_responsibility_bucket(issue)
        if len(buckets[bucket]) < 20:
            buckets[bucket].append(issue)
    return buckets


def _governance_responsibility_bucket(issue):
    if issue.get("owner") == "unknown owner":
        return "unknown_owner"
    if issue.get("issue_type") in {"partition_unsupported", "missing_task_runs"}:
        return "data_platform"
    if issue.get("issue_type") in {"missing_quality_rules", "missing_task_mapping", "unknown_layer", "missing_owner"}:
        return "warehouse_owner"
    if issue.get("issue_type") == "missing_data_source":
        return "data_platform"
    return "business_owner"
```

- [ ] **Step 5: Run targeted daily report test**

Run:

```bash
pytest tests/test_assets.py::AssetGovernanceIssueInventoryTest::test_daily_report_includes_governance_issue_summaries -v
```

Expected: PASS.

- [ ] **Step 6: Run asset tests**

Run:

```bash
pytest tests/test_assets.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit daily report enhancement**

```bash
git add dlc_mcp/assets.py tests/test_assets.py
git commit -m "Summarize governance issues in daily report

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: Data Asset Governance Skill

**Files:**
- Create: `.claude/skills/data-asset-governance/SKILL.md`
- Test: `tests/test_data_asset_governance_skill.py`

**Interfaces:**
- Consumes: issue inventory from `get_asset_governance_issue_inventory` or `diagnose_asset_gaps`.
- Produces: a project skill that guides LLM governance planning from evidence.

- [ ] **Step 1: Write failing skill guardrail test**

Create `tests/test_data_asset_governance_skill.py`:

```python
from pathlib import Path


def test_data_asset_governance_skill_contains_required_guardrails():
    path = Path(".claude/skills/data-asset-governance/SKILL.md")
    text = path.read_text(encoding="utf-8")

    assert "get_asset_governance_issue_inventory" in text
    assert "Do not invent issue facts or owners" in text
    assert "Do not treat absent data as healthy" in text
    assert "ListTablePartitions InvalidAction" in text
    assert "action/version unsupported" in text
    assert "real missing task/run coverage" in text
    assert "Every recommendation must cite issue evidence" in text
    assert "# 数据资产治理方案" in text
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
pytest tests/test_data_asset_governance_skill.py -v
```

Expected: FAIL with `FileNotFoundError`.

- [ ] **Step 3: Create skill file**

Create `.claude/skills/data-asset-governance/SKILL.md`:

```markdown
---
name: data-asset-governance
description: Use when analyzing exposed WeData/DLC asset governance gaps, classifying issue inventory, or preparing an evidence-backed governance plan for data assets.
---

# Data Asset Governance

Use this skill when the user asks to analyze data asset governance gaps, produce a governance plan, classify exposed issues, or decide next actions for WeData/DLC asset quality and coverage problems.

## Required Inputs

Obtain deterministic issue evidence before making recommendations. Prefer:

1. MCP: `get_asset_governance_issue_inventory(layer="", core_level="", issue_type="", limit=100)`
2. CLI/report: `python3 -m dlc_mcp.diagnose_asset_gaps ...`
3. Daily report: `get_asset_governance_daily_report(instance_date="", layer="", core_level="")`

If issue evidence is unavailable, ask the user to run one of these first. Do not invent issue facts or owners.

## Guardrails

- Do not invent issue facts or owners.
- Do not treat absent data as healthy.
- Do not treat `ListTablePartitions InvalidAction` as a parameter problem; classify it as action/version unsupported.
- Do not treat real missing task/run coverage as fake-table cleanup.
- Every recommendation must cite issue evidence.
- If evidence is insufficient, recommend the next check rather than guessing.
- Separate deterministic facts from LLM recommendations.

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
```

- [ ] **Step 4: Run skill test**

Run:

```bash
pytest tests/test_data_asset_governance_skill.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit skill**

```bash
git add .claude/skills/data-asset-governance/SKILL.md tests/test_data_asset_governance_skill.py
git commit -m "Add data asset governance skill

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: Core Asset Validation CLI

**Files:**
- Create: `dlc_mcp/validate_core_assets.py`
- Test: `tests/test_validate_core_assets.py`

**Interfaces:**
- Consumes `AssetStore` methods:
  - `list_core_candidates(layer="", limit=100)`
  - `get_table_profile(table_name)`
  - `is_core_table(table_name)`
  - `get_asset_value_profile(table_name)`
  - `get_quality_status(table_name)`
  - `get_table_production_status(table_name, instance_date="")`
  - `get_table_production_risk_detail(table_name, instance_date="")`
  - `get_asset_owner_profile(table_name)`
  - `get_asset_governance_issue_inventory(issue_type="", limit=...)`
- Produces:
  - `render_core_asset_validation(store: AssetStore, limit: int = 20, instance_date: str = "") -> str`
  - CLI `python3 -m dlc_mcp.validate_core_assets --db ... --limit 20 --output ...`

- [ ] **Step 1: Write failing validation report tests**

Create `tests/test_validate_core_assets.py`:

```python
import os
import sqlite3
import unittest
from tempfile import TemporaryDirectory

from dlc_mcp.assets import AssetStore
from dlc_mcp.validate_core_assets import main, render_core_asset_validation


class ValidateCoreAssetsTest(unittest.TestCase):
    def _store(self):
        store = AssetStore(sqlite3.connect(":memory:"))
        store.init_schema()
        return store

    def test_render_core_asset_validation_contains_profile_quality_production_and_issues(self):
        store = self._store()
        store.upsert_table({"name": "ads_revenue", "layer": "ads", "owner": "finance"})
        store.upsert_column("ads_revenue", "amount", "decimal", "", 1)
        store.upsert_expert_label({"asset_name": "ads_revenue", "core_level": "P1", "value_tier": "L1", "owner": "finance"})

        report = render_core_asset_validation(store, limit=20)

        self.assertIn("# 核心候选资产端到端验收报告", report)
        self.assertIn("## ads_revenue", report)
        self.assertIn("画像完整度", report)
        self.assertIn("核心判断", report)
        self.assertIn("质量状态", report)
        self.assertIn("生产状态", report)
        self.assertIn("风险解释", report)
        self.assertIn("当前缺口", report)
        self.assertIn("建议动作", report)

    def test_cli_writes_output_file(self):
        with TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "assets.db")
            output_path = os.path.join(tmpdir, "core_asset_validation.md")
            store = AssetStore(sqlite3.connect(db_path))
            store.init_schema()
            store.upsert_table({"name": "ads_revenue", "layer": "ads"})
            store.upsert_expert_label({"asset_name": "ads_revenue", "core_level": "P1", "value_tier": "L1"})

            main(["--db", db_path, "--limit", "20", "--output", output_path])

            self.assertTrue(os.path.exists(output_path))
            text = open(output_path, encoding="utf-8").read()
            self.assertIn("ads_revenue", text)
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pytest tests/test_validate_core_assets.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'dlc_mcp.validate_core_assets'`.

- [ ] **Step 3: Implement validation CLI**

Create `dlc_mcp/validate_core_assets.py`:

```python
import argparse
import os
import sqlite3

from .assets import AssetStore


def main(argv=None):
    args = _parse_args(argv)
    store = AssetStore(sqlite3.connect(args.db))
    store.init_schema()
    report = render_core_asset_validation(store, args.limit, args.instance_date)
    if args.output:
        output_dir = os.path.dirname(args.output)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report)
    else:
        print(report)


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Render core candidate asset end-to-end validation report.")
    parser.add_argument("--db", default=os.environ.get("DLC_MCP_DB", "data/assets.db"))
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--instance-date", default="")
    parser.add_argument("--output", default="")
    return parser.parse_args(argv)


def render_core_asset_validation(store, limit=20, instance_date=""):
    tables = _core_validation_tables(store, limit)
    sections = [
        "# 核心候选资产端到端验收报告",
        "",
        f"- 验收表数：**{len(tables)}**",
        f"- instance_date：`{instance_date}`",
        "- 报告基于当前 SQLite 资产事实生成，不触发外部 API。",
    ]
    for table_name in tables:
        sections.append(_render_table_validation(store, table_name, instance_date))
    return "\n\n".join(section for section in sections if section)


def _core_validation_tables(store, limit):
    candidates = store.list_core_candidates(limit=limit).get("results", [])
    names = [row["name"] for row in candidates if row.get("table_synced")]
    if len(names) >= limit:
        return names[:limit]
    fallback_rows = store._all(
        """
        select t.name
        from tables t
        left join (select upstream, count(*) as downstream_count from lineage group by upstream) d on d.upstream = t.name
        where t.name not in ({})
        order by coalesce(d.downstream_count, 0) desc,
                 case t.layer when 'ads' then 1 when 'dws' then 2 when 'dwd' then 3 else 9 end,
                 t.name
        limit ?
        """.format(",".join("?" for _ in names) or "''"),
        tuple(names + [limit - len(names)]) if names else (limit,),
    )
    names.extend(row["name"] for row in fallback_rows)
    return names[:limit]


def _render_table_validation(store, table_name, instance_date):
    profile = store.get_table_profile(table_name)
    core = store.is_core_table(table_name)
    value = store.get_asset_value_profile(table_name)
    quality = store.get_quality_status(table_name)
    production = store.get_table_production_status(table_name, instance_date)
    risk = store.get_table_production_risk_detail(table_name, instance_date)
    owner = store.get_asset_owner_profile(table_name)
    issues = [item for item in store.get_asset_governance_issue_inventory(limit=200).get("results", []) if item.get("asset_name") == table_name]
    completeness = _profile_completeness(profile, issues)
    lines = [
        f"## {table_name}",
        "",
        f"- 画像完整度：{completeness}%",
        f"- 核心判断：{core.get('core_level', '')} / {value.get('value_tier', '')}",
        f"- 质量状态：规则数 {quality.get('rule_count', 0)}，状态 {quality.get('latest_status', '') or '未知'}",
        f"- 生产状态：{production.get('status', '未知')}",
        f"- Owner：{owner.get('owner', '') or 'unknown owner'}",
        f"- 风险解释：{risk.get('summary', risk.get('status', '暂无风险摘要'))}",
        "- 当前缺口：",
    ]
    if issues:
        lines.extend(f"  - {issue['issue_type']}：{issue['suspected_root_cause']}" for issue in issues)
    else:
        lines.append("  - 暂无治理缺口")
    lines.append("- 建议动作：")
    lines.extend(_table_recommendations(issues))
    return "\n".join(lines)


def _profile_completeness(profile, issues):
    checks = 6
    missing = 0
    table = profile.get("table") or {}
    if not table.get("layer") or table.get("layer") == "unknown":
        missing += 1
    if not table.get("owner"):
        missing += 1
    if not profile.get("columns"):
        missing += 1
    if not profile.get("tasks"):
        missing += 1
    if not profile.get("quality", {}).get("rule_count"):
        missing += 1
    if not table.get("data_source_id"):
        missing += 1
    return round((checks - missing) / checks * 100)


def _table_recommendations(issues):
    if not issues:
        return ["  - 保持当前治理状态，纳入日常巡检。"]
    actions = []
    for issue in issues:
        actions.append(f"  - {issue['recommended_next_check']}")
    return actions


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run validation CLI tests**

Run:

```bash
pytest tests/test_validate_core_assets.py -v
```

Expected: PASS.

- [ ] **Step 5: Run CLI smoke locally**

Run:

```bash
python3 -m dlc_mcp.validate_core_assets --db data/assets.db --limit 5 | head -40
```

Expected: prints Markdown beginning with `# 核心候选资产端到端验收报告`.

- [ ] **Step 6: Commit validation CLI**

```bash
git add dlc_mcp/validate_core_assets.py tests/test_validate_core_assets.py
git commit -m "Add core asset validation report

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: Final Integration and Verification

**Files:**
- Modify if needed: `README.md`, `docs/okr-status-and-next-steps.md`, changed implementation/test files.

**Interfaces:**
- Consumes all prior task outputs.
- Produces a verified branch with docs and tests passing.

- [ ] **Step 1: Run focused tests**

Run:

```bash
pytest tests/test_assets.py tests/test_mcp.py tests/test_data_asset_governance_skill.py tests/test_validate_core_assets.py -v
```

Expected: PASS.

- [ ] **Step 2: Run full test suite**

Run:

```bash
pytest -q
```

Expected: PASS.

- [ ] **Step 3: Run MCP smoke for the new tool**

Run:

```bash
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"get_asset_governance_issue_inventory","arguments":{"issue_type":"missing_quality_rules","limit":5}}}' \
  | DLC_MCP_DB=data/assets.db python3 -m dlc_mcp.server
```

Expected: JSON-RPC response contains `missing_quality_rules` or an empty `results` list with `supported_issue_types`.

- [ ] **Step 4: Run core validation smoke**

Run:

```bash
python3 -m dlc_mcp.validate_core_assets --db data/assets.db --limit 5 > /tmp/core_asset_validation.md
head -20 /tmp/core_asset_validation.md
```

Expected: output starts with `# 核心候选资产端到端验收报告`.

- [ ] **Step 5: Confirm working tree**

Run:

```bash
git status --short
```

Expected: clean or only intentional uncommitted files. If intentional files remain, commit them:

```bash
git add README.md docs dlc_mcp tests .claude/skills/data-asset-governance/SKILL.md
git commit -m "Finalize asset governance issue workflow

Co-Authored-By: Claude <noreply@anthropic.com>"
```

## Self-Review

- Spec coverage: Task 1 implements deterministic issue inventory. Task 2 exposes MCP. Task 3 upgrades the daily governance report. Task 4 adds the project governance skill. Task 5 adds the 20-table validation CLI. Task 6 verifies integration and docs.
- Placeholder scan: No TBD/TODO/fill-later placeholders remain.
- Type consistency: `get_asset_governance_issue_inventory(layer, core_level, issue_type, limit)` is consistent across AssetStore, MCP, tests, daily report, and validation CLI.
