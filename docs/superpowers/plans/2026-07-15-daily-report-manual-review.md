# Daily Report Manual Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add severity-prioritized manual-review sections to the daily asset governance report, both in structured JSON and MCP Markdown output.

**Architecture:** Reuse the existing `AssetStore.get_asset_governance_daily_report()` flow in `dlc_mcp/assets.py`. Build manual-review sections from the deterministic governance issue inventory and existing owner gaps, then render those sections in `dlc_mcp/mcp.py` without changing existing field names or removing existing report sections.

**Tech Stack:** Python 3, SQLite, existing `AssetStore`, existing JSON-RPC MCP formatter, unittest/pytest.

## Global Constraints

- Do not add a ticket/status table.
- Do not persist solved/unsolved state.
- Do not auto-classify short-name tables into business layers.
- Do not delete, hide, or suppress temporary tables.
- Do not change `get_asset_governance_issue_inventory()` existing return structure.
- Keep existing `get_asset_governance_daily_report()` fields: `production_risks`, `coverage_gaps`, `quality_gaps`, `owner_gaps`, `lifecycle_watch`, and `expert_review_queue`.
- Quality rule gaps still display, but manual-review coverage issues must be prioritized before quality-rule actions in `top_actions`.
- Markdown should show at most 10 items per manual-review section; structured JSON should retain up to 20 items per section.

---

## File Structure

- Modify: `dlc_mcp/assets.py`
  - Add helpers near governance helper functions: `_manual_review_sections`, `_manual_review_top_items`, `_manual_review_item_from_issue`, `_manual_review_item_from_owner_gap`, `_manual_review_sort_key`, `_manual_review_daily_action`, `_manual_review_issue_type_label`, `_manual_review_owner_bucket_label`.
  - Update `AssetStore.get_asset_governance_daily_report()` to include `manual_review_sections`, `manual_review_top_items`, and manual-review summary counts.
  - Update `_governance_top_actions(...)` signature to accept `manual_review_top_items` and prioritize them before quality gaps.
- Modify: `dlc_mcp/mcp.py`
  - Add Markdown formatter helpers for manual review: `_format_manual_review_top_items(data)` and `_format_manual_review_sections(data)`.
  - Insert rendered sections after “资产画像缺口” and before “质量规则缺口”.
- Modify: `tests/test_assets.py`
  - Add tests for structured daily report fields and ordering.
- Modify: `tests/test_mcp.py`
  - Add tests for Markdown sections and visible issue rows.

---

### Task 1: Add structured manual-review sections to daily report

**Files:**
- Modify: `dlc_mcp/assets.py:1310-1374`
- Modify: `dlc_mcp/assets.py:3043-3061`
- Test: `tests/test_assets.py`

**Interfaces:**
- Consumes: `AssetStore.get_asset_governance_issue_inventory(layer='', core_level='', issue_type='', limit=100) -> dict`.
- Consumes: existing `owner_gaps` list from `get_asset_governance_daily_report()`.
- Produces: `manual_review_sections: list[dict]` in daily report JSON.
- Produces: `manual_review_top_items: list[dict]` in daily report JSON.

- [ ] **Step 1: Write failing structured-report test**

Add this test inside `class AssetGovernanceIssueInventoryTest(unittest.TestCase):` in `tests/test_assets.py`, before `test_daily_report_includes_governance_issue_summaries`:

```python
    def test_daily_report_groups_manual_review_sections_by_issue_type(self):
        store = self._store()
        store.upsert_table({"name": "company", "layer": "unknown", "owner": "tencent"})
        for index in range(3):
            store.upsert_lineage("company", f"downstream_{index}", "lineage")
        store.upsert_table({"name": "ods_encrypt_md5_mobile_df", "layer": "ods", "owner": "tencent"})
        store.upsert_task({"id": "task_consumer", "name": "consume_mobile", "inputs": ["ods_encrypt_md5_mobile_df"]})
        store.upsert_table({"name": "ads_unfinish_cdp_31_1d", "layer": "ads", "owner": "tencent"})
        store.upsert_task({"id": "task_output", "name": "build_ads_unfinish", "outputs": ["ads_unfinish_cdp_31_1d"]})
        store.upsert_table({"name": "ads_owner_gap", "layer": "ads", "owner": ""})

        report = store.get_asset_governance_daily_report()

        self.assertIn("manual_review_sections", report)
        self.assertIn("manual_review_top_items", report)
        sections = {section["key"]: section for section in report["manual_review_sections"]}
        self.assertEqual(sections["layer_manual_mapping"]["items"][0]["name"], "company")
        self.assertEqual(sections["producer_mapping_review"]["items"][0]["name"], "ods_encrypt_md5_mobile_df")
        self.assertEqual(sections["instance_window_review"]["items"][0]["name"], "ads_unfinish_cdp_31_1d")
        self.assertTrue(sections["owner_review"]["items"])
        self.assertTrue(report["manual_review_top_items"])
        self.assertIn("daily_action", report["manual_review_top_items"][0])
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python3 -m pytest tests/test_assets.py::AssetGovernanceIssueInventoryTest::test_daily_report_groups_manual_review_sections_by_issue_type -q
```

Expected: FAIL because `manual_review_sections` is not present.

- [ ] **Step 3: Implement structured manual-review helpers**

In `dlc_mcp/assets.py`, add these helpers immediately before `_governance_top_actions`:

```python
def _manual_review_sections(governance_issues, owner_gaps):
    section_specs = [
        (
            "layer_manual_mapping",
            "层级待人工判断",
            "表名无法自动推断数仓层级，但存在下游、任务或运行实例，需要人工确认层级或标记为临时/废弃。",
            "warehouse_owner",
            [
                issue
                for issue in governance_issues
                if issue.get("issue_type") == "unknown_layer" and issue.get("suspected_root_cause") == "manual_mapping_needed"
            ],
        ),
        (
            "producer_mapping_review",
            "产出任务映射待确认",
            "表存在任务关联但没有识别到 output producer，需检查任务 output、SQL INSERT/CREATE 解析和表名标准化。",
            "data_platform",
            [
                issue
                for issue in governance_issues
                if issue.get("issue_type") in {"missing_task_mapping", "missing_task_runs"}
                and issue.get("suspected_root_cause") in {"producer_mapping_gap", "producer_missing_gap"}
            ],
        ),
        (
            "instance_window_review",
            "运行实例窗口待确认",
            "表已识别 producer 任务但没有匹配运行实例，需确认实例窗口、关键词、分页或任务是否确实未执行。",
            "data_platform",
            [
                issue
                for issue in governance_issues
                if issue.get("issue_type") == "missing_task_runs" and issue.get("suspected_root_cause") == "instance_window_gap"
            ],
        ),
    ]
    sections = []
    for key, title, description, owner_bucket, issues in section_specs:
        items = sorted((_manual_review_item_from_issue(issue, key, owner_bucket) for issue in issues), key=_manual_review_sort_key)[:20]
        sections.append(
            {
                "key": key,
                "title": title,
                "description": description,
                "owner_bucket": owner_bucket,
                "count": len(items),
                "items": items,
            }
        )
    owner_items = [_manual_review_item_from_owner_gap(item) for item in owner_gaps[:20]]
    sections.append(
        {
            "key": "owner_review",
            "title": "Owner 责任待确认",
            "description": "表 Owner、任务 Owner、数据源 Owner 缺失或不一致，需要人工确认责任链。",
            "owner_bucket": "warehouse_owner",
            "count": len(owner_items),
            "items": owner_items,
        }
    )
    return sections


def _manual_review_top_items(sections, limit=10):
    items = []
    for section in sections:
        items.extend(section.get("items") or [])
    return sorted(items, key=_manual_review_sort_key)[:limit]


def _manual_review_item_from_issue(issue, section_key, owner_bucket):
    evidence = issue.get("evidence") or {}
    return {
        "section_key": section_key,
        "issue_type": issue.get("issue_type", ""),
        "issue_label": _manual_review_issue_type_label(section_key, issue.get("suspected_root_cause", "")),
        "name": issue.get("asset_name", ""),
        "layer": issue.get("layer", ""),
        "owner": issue.get("owner", ""),
        "severity": issue.get("severity", ""),
        "downstream_count": int(evidence.get("downstream_count") or 0),
        "task_count": int(evidence.get("task_count") or 0),
        "producer_task_count": int(evidence.get("producer_task_count") or 0),
        "run_count": int(evidence.get("run_count") or 0),
        "suspected_root_cause": issue.get("suspected_root_cause", ""),
        "recommended_next_check": issue.get("recommended_next_check", ""),
        "owner_bucket": owner_bucket,
        "owner_bucket_label": _manual_review_owner_bucket_label(owner_bucket),
        "daily_action": _manual_review_daily_action(section_key, issue.get("suspected_root_cause", "")),
    }


def _manual_review_item_from_owner_gap(item):
    return {
        "section_key": "owner_review",
        "issue_type": "missing_owner",
        "issue_label": "Owner 责任待确认",
        "name": item.get("name", ""),
        "layer": item.get("layer", ""),
        "owner": item.get("owner", ""),
        "severity": "P1",
        "downstream_count": int(item.get("downstream_count") or 0),
        "task_count": int(item.get("task_count") or 0),
        "producer_task_count": int(item.get("producer_task_count") or 0),
        "run_count": 0,
        "owner_candidates": item.get("owner_candidates") or [],
        "gaps": item.get("gaps") or [],
        "suspected_root_cause": "owner_governance_gap",
        "recommended_next_check": "确认表、产出任务和数据源 Owner 是否需要统一或明确分工。",
        "owner_bucket": "warehouse_owner",
        "owner_bucket_label": "数仓Owner/业务Owner",
        "daily_action": "确认责任人和责任边界。",
    }


def _manual_review_sort_key(item):
    severity_rank = {"P0": 0, "P1": 1, "P2": 2}.get(item.get("severity"), 9)
    issue_rank = {
        "producer_mapping_review": 0,
        "instance_window_review": 1,
        "layer_manual_mapping": 2,
        "owner_review": 3,
    }.get(item.get("section_key"), 9)
    layer_rank = {"ads": 0, "dws": 1, "dwd": 2, "dim": 3, "ods": 4, "mid": 5}.get(item.get("layer"), 9)
    actionability = int(bool(item.get("task_count") or item.get("producer_task_count") or item.get("run_count")))
    return (
        severity_rank,
        issue_rank,
        -int(item.get("downstream_count") or 0),
        -actionability,
        layer_rank,
        item.get("name", ""),
    )


def _manual_review_issue_type_label(section_key, root_cause):
    if section_key == "layer_manual_mapping":
        return "层级待判断"
    if section_key == "producer_mapping_review":
        return "产出任务映射缺失" if root_cause == "producer_missing_gap" else "产出任务映射待确认"
    if section_key == "instance_window_review":
        return "运行实例窗口待确认"
    if section_key == "owner_review":
        return "Owner 责任待确认"
    return "人工判断问题"


def _manual_review_owner_bucket_label(owner_bucket):
    return {
        "data_platform": "数据平台",
        "warehouse_owner": "数仓Owner/业务Owner",
        "business_owner": "业务Owner",
        "unknown_owner": "待确认Owner",
    }.get(owner_bucket, owner_bucket or "待确认Owner")


def _manual_review_daily_action(section_key, root_cause):
    if section_key == "layer_manual_mapping":
        return "确认为 dim/ods/dwd/dws/mid/ads、临时表或废弃表。"
    if section_key == "producer_mapping_review":
        return "确认 output producer 或 SQL INSERT/CREATE 解析。"
    if section_key == "instance_window_review":
        return "确认实例窗口、关键词、分页或任务是否确实未执行。"
    if section_key == "owner_review":
        return "确认责任人和责任边界。"
    return "人工复核并记录处理结论。"
```

- [ ] **Step 4: Wire helpers into `get_asset_governance_daily_report()`**

In `dlc_mcp/assets.py`, update `get_asset_governance_daily_report()` after `responsibility_buckets = ...`:

```python
        manual_review_sections = _manual_review_sections(governance_issues, owner_gaps)
        manual_review_top_items = _manual_review_top_items(manual_review_sections, 10)
```

Add to `summary`:

```python
            "manual_review_count": sum(section.get("count", 0) for section in manual_review_sections),
            "manual_review_top_count": len(manual_review_top_items),
```

Add to returned dict before `top_actions`:

```python
            "manual_review_sections": manual_review_sections,
            "manual_review_top_items": manual_review_top_items,
```

Update `top_actions` call to:

```python
            "top_actions": _governance_top_actions(summary, production_risks, quality_gaps, owner_gaps, lifecycle_watch, expert_queue, manual_review_top_items),
```

Replace `_governance_top_actions` signature and start with:

```python
def _governance_top_actions(summary, production_risks, quality_gaps, owner_gaps, lifecycle_watch, expert_queue, manual_review_top_items=None):
    actions = []
    manual_review_top_items = manual_review_top_items or []
    if manual_review_top_items:
        first = manual_review_top_items[0]
        second = manual_review_top_items[1] if len(manual_review_top_items) > 1 else None
        names = "、".join(item.get("name", "") for item in [first, second] if item and item.get("name"))
        actions.append(f"人工确认 {summary.get('manual_review_count', len(manual_review_top_items))} 个资产覆盖问题，优先处理{first.get('issue_label')}：{names}。")
```

Keep the existing production risk, quality, owner, lifecycle, expert queue action logic after that block.

- [ ] **Step 5: Run structured tests and verify pass**

Run:

```bash
python3 -m pytest tests/test_assets.py::AssetGovernanceIssueInventoryTest::test_daily_report_groups_manual_review_sections_by_issue_type tests/test_assets.py::AssetGovernanceIssueInventoryTest::test_daily_report_includes_governance_issue_summaries -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 1**

```bash
git add dlc_mcp/assets.py tests/test_assets.py
git commit -m $'feat: add manual review sections to daily report\n\nCo-Authored-By: Claude <noreply@anthropic.com>'
```

---

### Task 2: Render manual-review sections in MCP Markdown

**Files:**
- Modify: `dlc_mcp/mcp.py:1083-1107`
- Test: `tests/test_mcp.py`

**Interfaces:**
- Consumes: `manual_review_top_items: list[dict]` and `manual_review_sections: list[dict]` from Task 1.
- Produces: Markdown sections titled `今日优先人工判断问题` and `需要人工判断的资产覆盖问题`.

- [ ] **Step 1: Write failing Markdown test**

In `tests/test_mcp.py`, update `test_calls_asset_governance_daily_report_tool` by adding these assertions after `self.assertIn("资产画像缺口", text)`:

```python
        self.assertIn("今日优先人工判断问题", text)
        self.assertIn("需要人工判断的资产覆盖问题", text)
        self.assertIn("层级待人工判断", text)
        self.assertIn("产出任务映射待确认", text)
        self.assertIn("运行实例窗口待确认", text)
        self.assertIn("Owner 责任待确认", text)
```

- [ ] **Step 2: Run Markdown test and verify it fails**

Run:

```bash
python3 -m pytest tests/test_mcp.py::McpTest::test_calls_asset_governance_daily_report_tool -q
```

Expected: FAIL because the new sections are not rendered.

- [ ] **Step 3: Implement Markdown helpers**

In `dlc_mcp/mcp.py`, add these helpers immediately before `_format_asset_governance_daily_report(data)`:

```python
def _format_manual_review_top_items(data):
    rows = []
    for item in (data.get("manual_review_top_items") or [])[:10]:
        evidence = f"下游{item.get('downstream_count', 0)}，任务{item.get('task_count', 0)}，产出任务{item.get('producer_task_count', 0)}，运行实例{item.get('run_count', 0)}"
        rows.append(
            [
                item.get("severity", ""),
                item.get("issue_label", ""),
                item.get("name", ""),
                evidence,
                item.get("owner_bucket_label", ""),
                item.get("daily_action", ""),
            ]
        )
    return _section("今日优先人工判断问题", []) + "\n\n" + _table(["优先级", "问题类型", "表名", "影响证据", "责任方", "今日动作"], rows)


def _format_manual_review_sections(data):
    parts = [_section("需要人工判断的资产覆盖问题", [])]
    for section in data.get("manual_review_sections") or []:
        rows = []
        if section.get("key") == "owner_review":
            for item in (section.get("items") or [])[:10]:
                rows.append(
                    [
                        item.get("name", ""),
                        item.get("layer", ""),
                        item.get("owner", ""),
                        "、".join(item.get("owner_candidates") or []),
                        "、".join(item.get("gaps") or []),
                    ]
                )
            table = _table(["表名", "层级", "Owner", "候选责任人", "缺口"], rows)
        else:
            for item in (section.get("items") or [])[:10]:
                rows.append(
                    [
                        item.get("name", ""),
                        item.get("layer", ""),
                        item.get("owner", ""),
                        item.get("downstream_count", 0),
                        item.get("task_count", 0),
                        item.get("producer_task_count", 0),
                        item.get("run_count", 0),
                        item.get("recommended_next_check", ""),
                    ]
                )
            table = _table(["表名", "层级", "Owner", "下游", "任务", "产出任务", "运行实例", "建议"], rows)
        parts.append(f"**{_cell(section.get('title'))}**\n\n{table}")
    return "\n\n".join(parts)
```

- [ ] **Step 4: Insert sections into daily report formatter**

In `_format_asset_governance_daily_report(data)`, insert these two entries after the `资产画像缺口` entry and before `质量规则缺口`:

```python
            _format_manual_review_top_items(data),
            _format_manual_review_sections(data),
```

- [ ] **Step 5: Run Markdown test and verify pass**

Run:

```bash
python3 -m pytest tests/test_mcp.py::McpTest::test_calls_asset_governance_daily_report_tool -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 2**

```bash
git add dlc_mcp/mcp.py tests/test_mcp.py
git commit -m $'feat: render manual review issues in daily report\n\nCo-Authored-By: Claude <noreply@anthropic.com>'
```

---

### Task 3: Verify report behavior end-to-end

**Files:**
- Modify: none unless verification reveals a defect.
- Test: `tests/test_assets.py`, `tests/test_mcp.py`.

**Interfaces:**
- Consumes: Task 1 structured fields and Task 2 Markdown rendering.
- Produces: verified behavior and a clean working tree.

- [ ] **Step 1: Run focused tests**

Run:

```bash
python3 -m pytest tests/test_assets.py::AssetGovernanceIssueInventoryTest tests/test_mcp.py::McpTest::test_calls_asset_governance_daily_report_tool -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run full test suite**

Run:

```bash
python3 -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 3: Run local smoke output for daily report**

Run:

```bash
python3 - <<'PY'
import json
import sqlite3
from dlc_mcp.assets import AssetStore
from dlc_mcp.mcp import handle_request

store = AssetStore(sqlite3.connect('data/assets.db'))
store.init_schema()
response = handle_request(
    store,
    {
        'jsonrpc': '2.0',
        'id': 1,
        'method': 'tools/call',
        'params': {'name': 'get_asset_governance_daily_report', 'arguments': {}},
    },
)
text = response['result']['content'][0]['text']
print('今日优先人工判断问题' in text)
print('需要人工判断的资产覆盖问题' in text)
print(text[:2000])
PY
```

Expected:
- First printed line is `True`.
- Second printed line is `True`.
- Output includes daily report header and manual-review sections.

- [ ] **Step 4: Check git status**

Run:

```bash
git status --short
```

Expected: no uncommitted source or test changes. If smoke check creates/updates `data/assets.db`, do not commit that DB change unless it is already a tracked fixture change required by tests.

- [ ] **Step 5: Commit verification fix if needed**

If Step 3 revealed a small defect and you fixed source/tests, commit it:

```bash
git add dlc_mcp/assets.py dlc_mcp/mcp.py tests/test_assets.py tests/test_mcp.py
git commit -m $'test: verify manual review daily report\n\nCo-Authored-By: Claude <noreply@anthropic.com>'
```

If no changes are needed, skip this step.

---

## Self-Review

- Spec coverage: Task 1 adds `manual_review_sections`, `manual_review_top_items`, grouping, sorting, daily actions, and top action priority. Task 2 renders the new Markdown sections. Task 3 verifies focused, full, and smoke behavior.
- Placeholder scan: No TBD/TODO placeholders remain; conditional steps have exact skip conditions and commands.
- Type consistency: The structured fields produced in Task 1 match the field names consumed by Task 2 (`issue_label`, `owner_bucket_label`, `daily_action`, counts, owner candidates, gaps).
