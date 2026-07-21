# Producer Task Diagnosis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic root-cause diagnosis to `missing_producer_task` / producer-task coverage gaps, including controlled live evidence enrichment when live context is already available or explicitly supplied.

**Architecture:** Add one focused diagnosis helper in `dlc_mcp/assets.py` and reuse it from coverage gaps, governance issue inventory, and patrol finding normalization. The helper is cache-first and accepts optional live task evidence so patrol can reuse already-collected live data without another API call.

**Tech Stack:** Python 3.10, SQLite-backed `AssetStore`, pytest/unittest, existing MCP markdown formatting in `dlc_mcp/mcp.py`.

## Global Constraints

- Do not rewrite `sync_wedata.py` task extraction in this phase.
- Do not add large-scale live refresh jobs.
- Do not automatically backfill or repair `task_tables` mappings.
- Do not add fuzzy matching, semantic matching, or LLM inference for task-table links.
- Do not infer owners from table names; keep existing owner-resolution behavior.
- Bulk coverage/governance views are cache-only by default.
- Live evidence must be explicit, reused from patrol context, or bounded by the caller.
- Live API failures must not fail coverage, patrol, or governance reports.
- Every diagnosis must include an evidence source: `cache`, `live`, `cache+live`, or `patrol_live_context`.
- Preserve existing public fields and add diagnosis fields as extra structured evidence.
- Follow TDD: write each failing test first and watch it fail before implementation.

---

## File Structure

- Modify `dlc_mcp/assets.py`
  - Add producer diagnosis helper functions near existing governance/coverage helpers.
  - Add `consumer_task_count` to coverage and governance candidate SQL.
  - Attach diagnosis fields to producer-task coverage gaps.
  - Attach diagnosis evidence to governance issues for producer mapping gaps.

- Modify `dlc_mcp/patrol.py`
  - Import/reuse the diagnosis helper.
  - Attach `producer_diagnosis` to `missing_producer_task` patrol findings using cached lineage and already-normalized live task evidence.

- Modify `dlc_mcp/mcp.py`
  - Surface diagnosis root cause / next check in producer coverage gap markdown output.

- Modify `tests/test_assets.py`
  - Add pure helper tests for root-cause taxonomy.
  - Extend coverage gap and governance issue tests.

- Modify `tests/test_patrol.py`
  - Extend existing patrol missing live evidence test.
  - Add a live failure context test for producer diagnosis.

- Modify `tests/test_mcp.py`
  - Extend existing governance / coverage markdown tests to assert diagnosis appears.

---

### Task 1: Add deterministic producer diagnosis helper

**Files:**
- Modify: `dlc_mcp/assets.py:3320-3383`
- Test: `tests/test_assets.py`

**Interfaces:**
- Produces: `diagnose_producer_mapping_gap(context, live_tasks=None, live_error="", evidence_source="cache") -> dict`
- Produces: diagnosis dictionaries with keys `root_cause`, `reason`, `evidence_source`, `evidence`, `next_check`
- Consumes: plain dicts containing optional `layer`, `task_count`, `producer_task_count`, `consumer_task_count`, `upstream_count`, `downstream_count`, `run_count`

- [ ] **Step 1: Write failing helper tests**

Add these tests near `test_coverage_gaps_distinguish_missing_producer_from_missing_runs` in `tests/test_assets.py`:

```python
def test_diagnose_producer_mapping_gap_classifies_cache_root_causes(self):
    from dlc_mcp.assets import diagnose_producer_mapping_gap

    cases = [
        (
            {"name": "mystery_table", "layer": "unknown", "task_count": 0, "producer_task_count": 0},
            "unknown_layer_first",
        ),
        (
            {"name": "ads_input_only", "layer": "ads", "task_count": 2, "consumer_task_count": 2, "producer_task_count": 0},
            "consumer_only_mapping",
        ),
        (
            {"name": "ads_lineage_only", "layer": "ads", "task_count": 0, "producer_task_count": 0, "upstream_count": 1, "downstream_count": 0},
            "lineage_without_task_mapping",
        ),
        (
            {"name": "ads_isolated", "layer": "ads", "task_count": 0, "producer_task_count": 0, "upstream_count": 0, "downstream_count": 0},
            "no_lineage_no_task_mapping",
        ),
        (
            {"name": "ads_generic", "layer": "ads", "task_count": 1, "producer_task_count": 0, "consumer_task_count": 0},
            "producer_missing_gap",
        ),
        (
            {"name": "ads_has_producer", "layer": "ads", "task_count": 1, "producer_task_count": 1, "run_count": 0},
            "producer_present_run_missing",
        ),
    ]

    for context, expected_root_cause in cases:
        with self.subTest(expected_root_cause=expected_root_cause):
            diagnosis = diagnose_producer_mapping_gap(context)
            self.assertEqual(diagnosis["root_cause"], expected_root_cause)
            self.assertEqual(diagnosis["evidence_source"], "cache")
            self.assertIn("next_check", diagnosis)
            self.assertIn("producer_task_count", diagnosis["evidence"])


def test_diagnose_producer_mapping_gap_uses_live_evidence_when_cache_is_stale(self):
    from dlc_mcp.assets import diagnose_producer_mapping_gap

    diagnosis = diagnose_producer_mapping_gap(
        {"name": "ads_live_has_output", "layer": "ads", "task_count": 0, "producer_task_count": 0},
        live_tasks={"tasks": [{"id": "task_1", "name": "build_ads", "direction": "output"}]},
    )

    self.assertEqual(diagnosis["root_cause"], "cache_stale_or_missing_mapping")
    self.assertEqual(diagnosis["evidence_source"], "cache+live")
    self.assertEqual(diagnosis["evidence"]["cache_producer_task_count"], 0)
    self.assertEqual(diagnosis["evidence"]["live_producer_task_count"], 1)
    self.assertTrue(diagnosis["evidence"]["live_checked"])


def test_diagnose_producer_mapping_gap_reports_live_unavailable_when_requested_but_failed(self):
    from dlc_mcp.assets import diagnose_producer_mapping_gap

    diagnosis = diagnose_producer_mapping_gap(
        {"name": "ads_need_live", "layer": "ads", "task_count": 0, "producer_task_count": 0, "upstream_count": 1},
        live_error="ListTasks failed: InternalError temporary unavailable",
    )

    self.assertEqual(diagnosis["root_cause"], "live_evidence_unavailable")
    self.assertEqual(diagnosis["evidence_source"], "cache")
    self.assertFalse(diagnosis["evidence"]["live_checked"])
    self.assertIn("InternalError", diagnosis["evidence"]["live_error"])
```

- [ ] **Step 2: Run tests and verify they fail because the helper does not exist**

Run:

```bash
python -m pytest tests/test_assets.py::AssetStoreTest::test_diagnose_producer_mapping_gap_classifies_cache_root_causes tests/test_assets.py::AssetStoreTest::test_diagnose_producer_mapping_gap_uses_live_evidence_when_cache_is_stale tests/test_assets.py::AssetStoreTest::test_diagnose_producer_mapping_gap_reports_live_unavailable_when_requested_but_failed -v
```

Expected: FAIL with `ImportError` or `cannot import name 'diagnose_producer_mapping_gap'`.

- [ ] **Step 3: Add the helper implementation**

In `dlc_mcp/assets.py`, add this code after `_missing_task_runs_issue_detail` and before `_governance_issues_for_table`:

```python
def diagnose_producer_mapping_gap(context, live_tasks=None, live_error="", evidence_source="cache"):
    layer = (context.get("layer") or "unknown").lower()
    task_count = _int_value(context.get("task_count") if "task_count" in context else context.get("total_task_count"))
    producer_count = _int_value(context.get("producer_task_count"))
    consumer_count = _int_value(context.get("consumer_task_count"))
    upstream_count = _int_value(context.get("upstream_count"))
    downstream_count = _int_value(context.get("downstream_count"))
    run_count = _int_value(context.get("run_count"))

    evidence = {
        "layer": layer,
        "task_count": task_count,
        "producer_task_count": producer_count,
        "consumer_task_count": consumer_count,
        "upstream_count": upstream_count,
        "downstream_count": downstream_count,
        "run_count": run_count,
    }
    root_cause, reason, next_check = _cache_producer_diagnosis(layer, task_count, producer_count, consumer_count, upstream_count, downstream_count)
    source = evidence_source or "cache"

    if live_tasks is not None:
        live_producer_count, live_consumer_count = _live_task_direction_counts(live_tasks)
        evidence.update(
            {
                "cache_producer_task_count": producer_count,
                "live_producer_task_count": live_producer_count,
                "live_consumer_task_count": live_consumer_count,
                "live_checked": True,
            }
        )
        if live_producer_count > 0 and producer_count == 0:
            root_cause = "cache_stale_or_missing_mapping"
            reason = "live 证据可找到产出任务，但本地 task_tables 缓存没有 producer 映射。"
            next_check = "刷新 task_tables 缓存或修复同步链路，live 已能找到产出任务。"
            source = "cache+live" if source == "cache" else source
    elif live_error:
        evidence.update({"live_checked": False, "live_error": str(live_error)})
        if _producer_evidence_insufficient(layer, task_count, producer_count, upstream_count, downstream_count):
            root_cause = "live_evidence_unavailable"
            reason = "缓存证据不足，且 live 产出任务补证失败。"
            next_check = "重试 live ListTasks / get_table_tasks_live；若仍失败，再检查任务同步链路和 SQL 解析。"

    return {
        "root_cause": root_cause,
        "reason": reason,
        "evidence_source": source,
        "evidence": evidence,
        "next_check": next_check,
    }


def _cache_producer_diagnosis(layer, task_count, producer_count, consumer_count, upstream_count, downstream_count):
    if producer_count > 0:
        return (
            "producer_present_run_missing",
            "该表已存在 output/producer 任务，问题应转向运行实例诊断。",
            "检查 ListTaskInstances 时间窗口、关键词、分页和 task_id 对齐。",
        )
    if layer in {"", "unknown"}:
        return (
            "unknown_layer_first",
            "表仍在 unknown 层，producer 缺失判断不可靠。",
            "先运行 layer 推断或人工确认层级，再复查 producer task 映射。",
        )
    if consumer_count > 0:
        return (
            "consumer_only_mapping",
            "该表有关联任务，但全部是 input/consumer，没有 output/producer。",
            "检查任务 outputs、SQL INSERT/CREATE 解析和表名标准化，确认该表的产出任务是否漏识别。",
        )
    if task_count == 0 and upstream_count + downstream_count > 0:
        return (
            "lineage_without_task_mapping",
            "该表有血缘关系，但没有任何 task_tables 任务映射。",
            "检查血缘来源任务、ListTasks inputs/outputs 和 SQL 解析是否没有写入 task_tables。",
        )
    if task_count == 0 and upstream_count + downstream_count == 0:
        return (
            "no_lineage_no_task_mapping",
            "该表没有血缘和任务映射，可能是孤立表、缓存缺失、暂不支持或疑似废弃。",
            "先确认表是否仍在使用；若仍使用，再补查数据源、任务同步和 live 任务证据。",
        )
    return (
        "producer_missing_gap",
        "该表位于有效数仓层，但当前没有识别到 output/producer 任务。",
        "检查任务 outputs、SQL INSERT/CREATE 解析和表名标准化。",
    )


def _int_value(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _live_task_direction_counts(live_tasks):
    if not isinstance(live_tasks, dict):
        return 0, 0
    tasks = live_tasks.get("tasks") or live_tasks.get("results") or live_tasks.get("raw", {}).get("tasks") or []
    producer_count = len([item for item in tasks if item.get("direction") in {"output", "producer", "produces"}])
    consumer_count = len([item for item in tasks if item.get("direction") in {"input", "consumer", "consumes"}])
    return producer_count, consumer_count


def _producer_evidence_insufficient(layer, task_count, producer_count, upstream_count, downstream_count):
    return layer not in {"", "unknown"} and producer_count == 0 and (task_count == 0 or upstream_count + downstream_count > 0)
```

- [ ] **Step 4: Run helper tests and verify they pass**

Run:

```bash
python -m pytest tests/test_assets.py::AssetStoreTest::test_diagnose_producer_mapping_gap_classifies_cache_root_causes tests/test_assets.py::AssetStoreTest::test_diagnose_producer_mapping_gap_uses_live_evidence_when_cache_is_stale tests/test_assets.py::AssetStoreTest::test_diagnose_producer_mapping_gap_reports_live_unavailable_when_requested_but_failed -v
```

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

```bash
git add dlc_mcp/assets.py tests/test_assets.py
git commit -m "feat: add producer task diagnosis helper" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: Integrate diagnosis into coverage gaps and governance issues

**Files:**
- Modify: `dlc_mcp/assets.py:1540-1592`
- Modify: `dlc_mcp/assets.py:1647-1668`
- Modify: `dlc_mcp/assets.py:3351-3399`
- Modify: `dlc_mcp/assets.py:3447-3469`
- Test: `tests/test_assets.py`

**Interfaces:**
- Consumes: `diagnose_producer_mapping_gap(context, live_tasks=None, live_error="", evidence_source="cache") -> dict`
- Produces: producer coverage gap rows with `suspected_root_cause`, `recommended_next_check`, `producer_diagnosis`
- Produces: governance issue evidence with `producer_diagnosis` for producer mapping gaps

- [ ] **Step 1: Write failing coverage gap test**

Add this test after `test_coverage_gaps_distinguish_missing_producer_from_missing_runs` in `tests/test_assets.py`:

```python
def test_producer_task_coverage_gaps_include_diagnosis(self):
    store = make_store()
    store.upsert_table({"name": "ads_has_only_input", "layer": "ads", "data_source_id": "DLC"})
    store.upsert_table({"name": "ads_lineage_only", "layer": "ads", "data_source_id": "DLC"})
    store.upsert_task({"id": "consumer", "name": "consumer", "inputs": ["ads_has_only_input"]})
    store.upsert_lineage("dwd_source", "ads_lineage_only", "lineage_api")

    gaps = store.list_asset_coverage_gaps("producer_tasks", "ads", 20)["results"]
    by_name = {row["name"]: row for row in gaps}

    self.assertEqual(by_name["ads_has_only_input"]["suspected_root_cause"], "consumer_only_mapping")
    self.assertEqual(by_name["ads_has_only_input"]["producer_diagnosis"]["root_cause"], "consumer_only_mapping")
    self.assertIn("outputs", by_name["ads_has_only_input"]["recommended_next_check"])
    self.assertEqual(by_name["ads_lineage_only"]["suspected_root_cause"], "lineage_without_task_mapping")
    self.assertEqual(by_name["ads_lineage_only"]["producer_diagnosis"]["evidence_source"], "cache")
```

- [ ] **Step 2: Write failing governance issue test**

Add this test near the governance daily report tests in `tests/test_assets.py`:

```python
def test_governance_issue_inventory_includes_producer_diagnosis(self):
    store = make_store()
    store.upsert_table({"name": "ads_has_only_input", "layer": "ads", "data_source_id": "DLC"})
    store.upsert_task({"id": "consumer", "name": "consumer", "inputs": ["ads_has_only_input"]})

    inventory = store.get_asset_governance_issue_inventory(layer="ads", issue_type="missing_task_mapping", limit=10)
    issue = next(item for item in inventory["results"] if item["asset_name"] == "ads_has_only_input")

    self.assertEqual(issue["suspected_root_cause"], "consumer_only_mapping")
    self.assertEqual(issue["recommended_next_check"], issue["evidence"]["producer_diagnosis"]["next_check"])
    self.assertEqual(issue["evidence"]["producer_diagnosis"]["evidence_source"], "cache")
```

- [ ] **Step 3: Run tests and verify they fail because diagnosis is not integrated**

Run:

```bash
python -m pytest tests/test_assets.py::AssetStoreTest::test_producer_task_coverage_gaps_include_diagnosis tests/test_assets.py::AssetStoreTest::test_governance_issue_inventory_includes_producer_diagnosis -v
```

Expected: FAIL with missing `suspected_root_cause`, missing `producer_diagnosis`, or old root cause values.

- [ ] **Step 4: Add consumer task counts to coverage gap SQL**

In `AssetStore.list_asset_coverage_gaps`, update the select list and joins.

Add this selected column after `producer_task_count`:

```sql
coalesce(ct.consumer_task_count, 0) as consumer_task_count,
```

Add this join after the producer task join:

```sql
left join (select table_name, count(distinct task_id) as consumer_task_count from task_tables where direction = 'input' group by table_name) ct on ct.table_name = t.name
```

- [ ] **Step 5: Attach diagnosis to producer coverage gap rows**

In the `for row in rows:` loop in `list_asset_coverage_gaps`, after `item["gap_keys"] = gaps`, add:

```python
            if "producer_tasks" in gaps:
                diagnosis = diagnose_producer_mapping_gap(item)
                item["producer_diagnosis"] = diagnosis
                item["suspected_root_cause"] = diagnosis["root_cause"]
                item["recommended_next_check"] = diagnosis["next_check"]
```

- [ ] **Step 6: Add consumer task counts to governance candidate SQL**

In `_governance_issue_candidates`, add this selected column after `producer_task_count`:

```sql
coalesce(ct.consumer_task_count, 0) as consumer_task_count,
```

Add this join after the producer task join:

```sql
left join (select table_name, count(distinct task_id) as consumer_task_count from task_tables where direction = 'input' group by table_name) ct on ct.table_name = t.name
```

- [ ] **Step 7: Update governance issue generation to use diagnosis for producer gaps**

Replace `_missing_task_mapping_issue_detail` with:

```python
def _missing_task_mapping_issue_detail(table):
    diagnosis = diagnose_producer_mapping_gap(table)
    return diagnosis["root_cause"], diagnosis["next_check"]
```

Then update `_governance_issue` so producer mapping issues include the full diagnosis. Replace the `evidence = { ... }` block with this version:

```python
    evidence = {
        "layer": table.get("layer", ""),
        "core_level": table.get("core_level", ""),
        "column_count": int(table.get("column_count") or 0),
        "quality_rule_count": int(table.get("quality_rule_count") or 0),
        "downstream_count": int(table.get("downstream_count") or 0),
        "upstream_count": int(table.get("upstream_count") or 0),
        "task_count": int(table.get("task_count") or 0),
        "producer_task_count": int(table.get("producer_task_count") or 0),
        "consumer_task_count": int(table.get("consumer_task_count") or 0),
        "run_count": int(table.get("run_count") or 0),
        "data_source_id": table.get("data_source_id", ""),
    }
    if issue_type == "missing_task_mapping" and int(table.get("producer_task_count") or 0) == 0:
        evidence["producer_diagnosis"] = diagnose_producer_mapping_gap(table)
```

- [ ] **Step 8: Run focused tests and verify they pass**

Run:

```bash
python -m pytest tests/test_assets.py::AssetStoreTest::test_producer_task_coverage_gaps_include_diagnosis tests/test_assets.py::AssetStoreTest::test_governance_issue_inventory_includes_producer_diagnosis tests/test_assets.py::AssetStoreTest::test_coverage_gaps_distinguish_missing_producer_from_missing_runs -v
```

Expected: PASS.

- [ ] **Step 9: Commit Task 2**

```bash
git add dlc_mcp/assets.py tests/test_assets.py
git commit -m "feat: diagnose producer coverage gaps" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: Add producer diagnosis to patrol findings using patrol live context

**Files:**
- Modify: `dlc_mcp/patrol.py:1-8`
- Modify: `dlc_mcp/patrol.py:319-346`
- Test: `tests/test_patrol.py`

**Interfaces:**
- Consumes: `diagnose_producer_mapping_gap(context, live_tasks=None, live_error="", evidence_source="cache") -> dict`
- Produces: `missing_producer_task` patrol finding evidence with `producer_diagnosis`

- [ ] **Step 1: Write failing patrol diagnosis test**

Modify `test_patrol_normalizes_missing_live_evidence_into_findings` in `tests/test_patrol.py` by adding these assertions after the `assert all(...)` line:

```python
    producer_finding = next(finding for finding in result["findings"] if finding["issue_type"] == "missing_producer_task")
    diagnosis = producer_finding["evidence"]["producer_diagnosis"]
    assert diagnosis["root_cause"] == "lineage_without_task_mapping"
    assert diagnosis["evidence_source"] == "patrol_live_context"
    assert diagnosis["evidence"]["live_checked"] is True
    assert diagnosis["evidence"]["live_producer_task_count"] == 0
```

- [ ] **Step 2: Write failing patrol live failure test**

Add this test after `test_patrol_normalizes_missing_live_evidence_into_findings`:

```python
def test_patrol_producer_diagnosis_records_live_task_error():
    store = AssetStore(sqlite3.connect(":memory:"))
    store.init_schema()
    table = {"name": "ads_need_live", "layer": "ads", "owner": "tencent", "database_name": "dw"}
    evidence = {
        "source_policy": {"metadata": "cache", "columns": "cache", "lineage": "cache", "tasks": "live_only", "quality": "live_only", "runs": "live_only"},
        "cached": {
            "metadata": {"status": "complete", "core_level": "P2"},
            "columns": {"status": "complete", "count": 10},
            "lineage": {"status": "complete", "upstream_count": 1, "downstream_count": 0},
        },
        "live": {
            "tasks": {"status": "live_failed", "producer_count": 0, "consumer_count": 0, "raw": {"error": "live_failed", "message": "ListTasks failed: InternalError temporary unavailable"}},
            "quality": {"status": "missing", "rule_count": 0},
            "runs": {"status": "missing", "run_count": 0, "summary_status": "not_run"},
        },
        "errors": [],
    }

    result = PatrolService(store, PatrolLive(store))._normalize_table_result(table, evidence)

    producer_finding = next(finding for finding in result["findings"] if finding["issue_type"] == "missing_producer_task")
    diagnosis = producer_finding["evidence"]["producer_diagnosis"]
    assert diagnosis["root_cause"] == "live_evidence_unavailable"
    assert diagnosis["evidence_source"] == "patrol_live_context"
    assert diagnosis["evidence"]["live_checked"] is False
    assert "InternalError" in diagnosis["evidence"]["live_error"]
```

- [ ] **Step 3: Run tests and verify they fail because patrol findings lack diagnosis**

Run:

```bash
python -m pytest tests/test_patrol.py::test_patrol_normalizes_missing_live_evidence_into_findings tests/test_patrol.py::test_patrol_producer_diagnosis_records_live_task_error -v
```

Expected: FAIL with missing `producer_diagnosis`.

- [ ] **Step 4: Import diagnosis helper in patrol**

Change the import at the top of `dlc_mcp/patrol.py` from:

```python
from dlc_mcp.assets import Source
```

To:

```python
from dlc_mcp.assets import Source, diagnose_producer_mapping_gap
```

- [ ] **Step 5: Add a patrol diagnosis builder method**

Add this method in `PatrolService`, just before `_finding`:

```python
    def _producer_diagnosis(self, table, cached, live_tasks):
        lineage = cached.get("lineage", {})
        context = {
            "name": table.get("name", ""),
            "layer": table.get("layer", ""),
            "task_count": live_tasks.get("count", 0),
            "producer_task_count": live_tasks.get("producer_count", 0),
            "consumer_task_count": live_tasks.get("consumer_count", 0),
            "upstream_count": lineage.get("upstream_count", 0),
            "downstream_count": lineage.get("downstream_count", 0),
            "run_count": 0,
        }
        if live_tasks.get("status") == "live_failed":
            raw = live_tasks.get("raw") or {}
            return diagnose_producer_mapping_gap(
                context,
                live_error=raw.get("message") or raw.get("error") or "live task evidence unavailable",
                evidence_source="patrol_live_context",
            )
        return diagnose_producer_mapping_gap(context, live_tasks=live_tasks.get("raw", {}), evidence_source="patrol_live_context")
```

- [ ] **Step 6: Attach diagnosis to `missing_producer_task` finding**

Replace this block in `_normalize_table_result`:

```python
        if live.get("tasks", {}).get("status") == "missing":
            findings.append(self._finding("missing_producer_task", "P1", "live", live.get("tasks", {}), suggested_action="Check ListTasks inputs/outputs or SQL parsing for this table."))
```

With:

```python
        if live.get("tasks", {}).get("status") in {"missing", "live_failed"}:
            task_evidence = dict(live.get("tasks", {}))
            diagnosis = self._producer_diagnosis(table, cached, task_evidence)
            task_evidence["producer_diagnosis"] = diagnosis
            findings.append(self._finding("missing_producer_task", "P1", "live", task_evidence, suggested_action=diagnosis["next_check"]))
```

- [ ] **Step 7: Run patrol tests and verify they pass**

Run:

```bash
python -m pytest tests/test_patrol.py::test_patrol_normalizes_missing_live_evidence_into_findings tests/test_patrol.py::test_patrol_producer_diagnosis_records_live_task_error tests/test_patrol.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit Task 3**

```bash
git add dlc_mcp/patrol.py tests/test_patrol.py
git commit -m "feat: include producer diagnosis in patrol findings" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: Surface diagnosis in MCP markdown output

**Files:**
- Modify: `dlc_mcp/mcp.py:1040-1062`
- Test: `tests/test_mcp.py`

**Interfaces:**
- Consumes: coverage gap rows containing `producer_diagnosis`, `suspected_root_cause`, `recommended_next_check`
- Produces: markdown coverage gap table with diagnosis columns

- [ ] **Step 1: Write failing MCP coverage markdown test**

Add this test near `test_coverage_gap_markdown_includes_producer_task_and_run_reason` in `tests/test_mcp.py`:

```python
def test_coverage_gap_markdown_includes_producer_diagnosis():
    store = AssetStore(sqlite3.connect(":memory:"))
    store.init_schema()
    store.upsert_table({"name": "ads_has_only_input", "layer": "ads", "data_source_id": "DLC"})
    store.upsert_task({"id": "consumer", "name": "consumer", "inputs": ["ads_has_only_input"]})

    text = _call_tool(
        store,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "list_asset_coverage_gaps", "arguments": {"gap_type": "producer_tasks", "layer": "ads", "limit": 10}},
        },
    )["result"]["content"][0]["text"]

    assert "疑似原因" in text
    assert "下一步检查" in text
    assert "consumer_only_mapping" in text
    assert "SQL INSERT/CREATE" in text
```

- [ ] **Step 2: Run test and verify it fails because markdown lacks diagnosis columns**

Run:

```bash
python -m pytest tests/test_mcp.py::test_coverage_gap_markdown_includes_producer_diagnosis -v
```

Expected: FAIL with missing `疑似原因` or missing `consumer_only_mapping`.

- [ ] **Step 3: Add diagnosis columns to coverage gap markdown table**

In `dlc_mcp/mcp.py`, find the `_table(...)` call for `list_asset_coverage_gaps` with columns:

```python
["表名", "层级", "负责人", "字段", "质量规则", "上游", "下游", "任务", "产出任务", "运行实例", "运行实例缺口原因", "数据源", "缺口"]
```

Replace the column list with:

```python
["表名", "层级", "负责人", "字段", "质量规则", "上游", "下游", "任务", "产出任务", "运行实例", "运行实例缺口原因", "数据源", "缺口", "疑似原因", "下一步检查"]
```

Then replace each row list with this version:

```python
                        [
                            r.get("name"),
                            r.get("layer"),
                            r.get("owner"),
                            r.get("column_count"),
                            r.get("quality_rule_count"),
                            r.get("upstream_count"),
                            r.get("downstream_count"),
                            r.get("task_count"),
                            r.get("producer_task_count"),
                            r.get("run_count"),
                            _run_gap_reason_label(r.get("run_gap_reason")),
                            r.get("data_source_id"),
                            "、".join(r.get("gaps") or []),
                            r.get("suspected_root_cause", ""),
                            r.get("recommended_next_check", ""),
                        ]
```

- [ ] **Step 4: Run MCP markdown test and verify it passes**

Run:

```bash
python -m pytest tests/test_mcp.py::test_coverage_gap_markdown_includes_producer_diagnosis -v
```

Expected: PASS.

- [ ] **Step 5: Run related MCP tests**

Run:

```bash
python -m pytest tests/test_mcp.py::test_rich_patrol_daily_report_includes_evidence_source tests/test_mcp.py::test_coverage_gap_markdown_includes_producer_task_and_run_reason tests/test_mcp.py::test_coverage_gap_markdown_includes_producer_diagnosis -v
```

Expected: PASS.

- [ ] **Step 6: Commit Task 4**

```bash
git add dlc_mcp/mcp.py tests/test_mcp.py
git commit -m "feat: show producer diagnosis in coverage gaps" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: Final verification and regression pass

**Files:**
- Verify only unless tests reveal a defect.

**Interfaces:**
- Consumes: all prior task outputs.
- Produces: clean test run and final review notes.

- [ ] **Step 1: Run focused producer diagnosis tests**

Run:

```bash
python -m pytest tests/test_assets.py::AssetStoreTest::test_diagnose_producer_mapping_gap_classifies_cache_root_causes tests/test_assets.py::AssetStoreTest::test_diagnose_producer_mapping_gap_uses_live_evidence_when_cache_is_stale tests/test_assets.py::AssetStoreTest::test_diagnose_producer_mapping_gap_reports_live_unavailable_when_requested_but_failed tests/test_assets.py::AssetStoreTest::test_producer_task_coverage_gaps_include_diagnosis tests/test_assets.py::AssetStoreTest::test_governance_issue_inventory_includes_producer_diagnosis tests/test_patrol.py::test_patrol_normalizes_missing_live_evidence_into_findings tests/test_patrol.py::test_patrol_producer_diagnosis_records_live_task_error tests/test_mcp.py::test_coverage_gap_markdown_includes_producer_diagnosis -v
```

Expected: all selected tests PASS.

- [ ] **Step 2: Run full test suite**

Run:

```bash
python -m pytest
```

Expected: `266+ passed`; exact count may increase because this plan adds tests.

- [ ] **Step 3: Inspect changed files**

Run:

```bash
git diff --stat HEAD~4..HEAD
git status --short --branch
```

Expected: branch is clean except for intentional commits; changed files are limited to:

- `dlc_mcp/assets.py`
- `dlc_mcp/patrol.py`
- `dlc_mcp/mcp.py`
- `tests/test_assets.py`
- `tests/test_patrol.py`
- `tests/test_mcp.py`

- [ ] **Step 4: If any final fixes are needed, commit them**

Only run this if Step 1 or Step 2 revealed a small defect and you fixed it:

```bash
git add dlc_mcp/assets.py dlc_mcp/patrol.py dlc_mcp/mcp.py tests/test_assets.py tests/test_patrol.py tests/test_mcp.py
git commit -m "fix: stabilize producer diagnosis outputs" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

- [ ] **Step 5: Report completion**

Summarize:

- root cause categories implemented;
- outputs enriched;
- live evidence behavior supported through optional/patrol context;
- test command results.

---

## Self-Review Notes

- Spec coverage: Tasks cover helper taxonomy, cache output integration, patrol live context, markdown visibility, and full verification.
- Live补证 scope: Implemented as optional live evidence supplied to the helper and patrol live-context reuse. No unbounded bulk live API calls are added.
- Backward compatibility: Existing fields remain; diagnosis is additive.
- TDD coverage: Each implementation task starts with failing tests and a targeted verification command.
- Type consistency: The helper signature is used consistently as `diagnose_producer_mapping_gap(context, live_tasks=None, live_error="", evidence_source="cache")`.
