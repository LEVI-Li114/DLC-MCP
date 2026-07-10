# Data Gap Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only asset gap diagnostic report for the four latest service inspection gaps, then add targeted parser/sync/report enhancements that make the gaps actionable.

**Architecture:** Add a focused diagnostic module that reads SQLite and raw WeData dumps, classifies root causes, and renders Markdown without mutating data. Keep parser improvements in `dlc_mcp/wedata.py`, partition payload helpers in `dlc_mcp/sync_wedata.py`, and foundation-report source labeling in `dlc_mcp/check_foundation.py`.

**Tech Stack:** Python standard library, SQLite, existing `AssetStore`, `unittest`, `pytest`.

## Global Constraints

- `62` quality rules and `2141` unknown-layer tables are latest service asset inspection baselines, not local demo DB values.
- Diagnosis must be read-only and must not mutate service data.
- Diagnosis must not call external WeData APIs by default.
- Partition validation must stay bounded and must not trigger full partition sync by default.
- Missing raw dumps must produce DB-only diagnosis, not a failure.
- Real synced tables missing tasks/runs must not be classified as task-derived fake table artifacts.

---

## File Structure

- Create `dlc_mcp/diagnose_asset_gaps.py`: CLI, SQLite/raw dump readers, diagnosis functions, Markdown rendering.
- Create `tests/test_diagnose_asset_gaps.py`: end-to-end unit tests for the diagnostic report and root-cause classification.
- Modify `dlc_mcp/wedata.py`: add layer inference aliases, safer table-name normalization, and quality-rule field aliases.
- Modify `tests/test_wedata_import.py`: parser regression tests.
- Modify `dlc_mcp/sync_wedata.py`: add partition payload helper used by diagnostics and future sync configuration.
- Modify `tests/test_sync_wedata.py`: partition payload tests.
- Modify `dlc_mcp/check_foundation.py`: optional report source/baseline rendering.
- Modify `tests/test_check_foundation.py`: report source/baseline test.

---

### Task 1: Add Diagnostic Report Module

**Files:**
- Create: `dlc_mcp/diagnose_asset_gaps.py`
- Test: `tests/test_diagnose_asset_gaps.py`

**Interfaces:**
- Consumes: existing `AssetStore` schema and raw dump files under a sync directory.
- Produces:
  - `render_gap_diagnosis(db_path: str, sync_dir: str, report_source: str = "", quality_rule_count: int | None = None, unknown_layer_count: int | None = None, sample_limit: int = 10, project_id: str = "") -> str`
  - `main() -> None`

- [ ] **Step 1: Write failing tests for baseline labeling and DB-only diagnosis**

Create `tests/test_diagnose_asset_gaps.py` with this content:

```python
import os
import sqlite3
import unittest
from tempfile import TemporaryDirectory

from dlc_mcp.assets import AssetStore
from dlc_mcp.diagnose_asset_gaps import render_gap_diagnosis


class DiagnoseAssetGapsTest(unittest.TestCase):
    def _store(self, db_path):
        store = AssetStore(sqlite3.connect(db_path))
        store.init_schema()
        return store

    def test_report_labels_service_baselines_and_db_only_mode(self):
        with TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "assets.db")
            store = self._store(db_path)
            store.upsert_table({"name": "mystery_table", "layer": "unknown", "owner": "owner-a"})
            store.upsert_table({"name": "ads_revenue", "layer": "ads", "owner": "owner-b"})
            store.upsert_column("ads_revenue", "amount", "decimal", "", 1)

            report = render_gap_diagnosis(
                db_path,
                os.path.join(tmpdir, "sync"),
                report_source="latest service asset inspection",
                quality_rule_count=62,
                unknown_layer_count=2141,
                sample_limit=5,
            )

        self.assertIn("# DLC-MCP 资产缺口诊断报告", report)
        self.assertIn("latest service asset inspection", report)
        self.assertIn("质量规则基线：**62**", report)
        self.assertIn("unknown 层表基线：**2141**", report)
        self.assertIn("raw dump 不存在，只能进行 DB-only 诊断", report)
        self.assertIn("质量规则可能是源头治理不足或同步范围不足", report)
        self.assertIn("真实表缺任务/运行实例诊断", report)
        self.assertIn("不是任务名误造表清理问题", report)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
pytest tests/test_diagnose_asset_gaps.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'dlc_mcp.diagnose_asset_gaps'`.

- [ ] **Step 3: Implement the minimal diagnostic module**

Create `dlc_mcp/diagnose_asset_gaps.py` with this content:

```python
import argparse
import json
import os
import sqlite3
from collections import Counter

from .assets import AssetStore

LAYER_VALUES = {"ods", "dim", "dwd", "dws", "ads"}
RAW_FILES = {
    "tables": "wedata_tables.json",
    "metadata": "wedata_metadata.json",
    "tasks": "wedata_tasks.json",
    "task_instances": "wedata_task_instances.json",
    "table_partitions": "wedata_table_partitions.json",
}


def main():
    args = _parse_args()
    print(
        render_gap_diagnosis(
            args.db,
            args.sync_dir,
            report_source=args.report_source,
            quality_rule_count=args.quality_rule_count,
            unknown_layer_count=args.unknown_layer_count,
            sample_limit=args.sample_limit,
            project_id=args.project_id,
        )
    )


def _parse_args():
    parser = argparse.ArgumentParser(description="Diagnose DLC-MCP asset coverage gaps without mutating data.")
    parser.add_argument("--db", default=os.environ.get("DLC_MCP_DB", "data/assets.db"))
    parser.add_argument("--sync-dir", default=os.environ.get("DLC_MCP_SYNC_DIR", "/data/dlc-mcp/sync"))
    parser.add_argument("--report-source", default="")
    parser.add_argument("--quality-rule-count", type=int, default=None)
    parser.add_argument("--unknown-layer-count", type=int, default=None)
    parser.add_argument("--sample-limit", type=int, default=10)
    parser.add_argument("--project-id", default=os.environ.get("WEDATA_PROJECT_ID", ""))
    return parser.parse_args()


def render_gap_diagnosis(db_path, sync_dir, report_source="", quality_rule_count=None, unknown_layer_count=None, sample_limit=10, project_id=""):
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"asset database not found: {db_path}")
    store = AssetStore(sqlite3.connect(db_path))
    store.init_schema()
    raw = _load_raw_dumps(sync_dir)
    lines = [
        "# DLC-MCP 资产缺口诊断报告",
        "",
        _inspection_section(db_path, sync_dir, raw, report_source, quality_rule_count, unknown_layer_count),
        _quality_section(store, raw),
        _unknown_layer_section(store, raw, sample_limit),
        _partition_section(store, raw, sample_limit, project_id),
        _task_run_section(store, raw, sample_limit),
        _next_actions_section(),
    ]
    return "\n\n".join(section for section in lines if section)


def _load_raw_dumps(sync_dir):
    raw = {}
    for key, filename in RAW_FILES.items():
        path = os.path.join(sync_dir, filename)
        if not os.path.exists(path):
            raw[key] = {"exists": False, "path": path, "data": None, "error": ""}
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            raw[key] = {"exists": True, "path": path, "data": data, "error": ""}
        except (OSError, json.JSONDecodeError) as exc:
            raw[key] = {"exists": True, "path": path, "data": None, "error": str(exc)}
    return raw


def _inspection_section(db_path, sync_dir, raw, report_source, quality_rule_count, unknown_layer_count):
    lines = ["## 巡检来源", f"- 数据库：`{_cell(db_path)}`", f"- raw dump 目录：`{_cell(sync_dir)}`"]
    if report_source:
        lines.append(f"- 来源：{_cell(report_source)}")
    if quality_rule_count is not None:
        lines.append(f"- 质量规则基线：**{quality_rule_count}**（来自最新服务端资产库巡检）")
    if unknown_layer_count is not None:
        lines.append(f"- unknown 层表基线：**{unknown_layer_count}**（来自最新服务端资产库巡检）")
    missing = [item["path"] for item in raw.values() if not item["exists"]]
    bad = [f"{item['path']}: {item['error']}" for item in raw.values() if item["error"]]
    if missing:
        lines.append("- raw dump 不存在，只能进行 DB-only 诊断；无法区分接口未返回和解析/导入丢失。")
    if bad:
        lines.append("- raw dump 解析失败：" + "；".join(_cell(item) for item in bad))
    return "\n".join(lines)


def _quality_section(store, raw):
    counts = store.get_sync_health().get("counts", {})
    coverage = store.get_asset_coverage().get("layers", [])
    db_rules = int(counts.get("quality_rules") or 0)
    raw_rules = _raw_quality_rule_count(raw)
    rows = []
    for row in coverage:
        table_count = int(row.get("table_count") or 0)
        with_rules = int(row.get("tables_with_quality_rules") or 0)
        rows.append([row.get("layer"), table_count, f"{with_rules}/{table_count}"])
    causes = []
    if raw_rules is None:
        causes.append("质量规则可能是源头治理不足或同步范围不足；缺少 raw metadata，暂不能区分。")
    elif raw_rules > db_rules:
        causes.append("raw 质量规则多于 DB，优先排查 `_quality_rule_from_api` 字段映射或入库冲突。")
    elif raw_rules <= db_rules:
        causes.append("raw 质量规则与 DB 接近，优先判断为 WeData 源头治理不足或同步范围太小。")
    return "\n\n".join([
        "## 质量规则覆盖诊断",
        f"- DB 质量规则数：**{db_rules}**",
        f"- raw 质量规则数：**{raw_rules if raw_rules is not None else '未知'}**",
        _table(["层级", "表数", "有质量规则"], rows),
        _bullets(causes),
    ])


def _unknown_layer_section(store, raw, sample_limit):
    rows = _query(store, "select name, database_name, owner, source_guid, data_source_id from tables where coalesce(layer, '') in ('', 'unknown') order by name limit ?", (sample_limit,))
    total = _scalar(store, "select count(*) from tables where coalesce(layer, '') in ('', 'unknown')")
    raw_tables = _raw_items(raw.get("tables", {}).get("data"))
    raw_by_name = {_raw_table_name(item): item for item in raw_tables if _raw_table_name(item)}
    detail_rows = []
    causes = Counter()
    for row in rows:
        raw_item = raw_by_name.get(row["name"], {})
        inferred = _infer_layer(row["name"], row["database_name"], raw_item)
        if inferred:
            causes["parser_fixable"] += 1
        elif raw_item:
            causes["raw_insufficient"] += 1
        else:
            causes["raw_missing"] += 1
        detail_rows.append([row["name"], row["database_name"], inferred or "", "Y" if raw_item else "N"])
    cause_lines = [
        f"抽样中可由名称/库/路径推断：{causes['parser_fixable']}",
        f"抽样中 raw 存在但信息不足：{causes['raw_insufficient']}",
        f"抽样中找不到 raw 记录：{causes['raw_missing']}",
    ]
    return "\n\n".join([
        "## unknown 层诊断",
        f"- DB unknown 层表数：**{total}**",
        _table(["表名", "库名", "可推断层级", "raw 记录"], detail_rows),
        _bullets(cause_lines),
    ])


def _partition_section(store, raw, sample_limit, project_id):
    rows = _query(store, "select name, source_guid, database_name, data_source_id from tables order by name limit ?", (sample_limit,))
    payload_rows = []
    for row in rows:
        for payload in _partition_payloads(row, project_id):
            payload_rows.append([row["name"], json.dumps(payload, ensure_ascii=False, sort_keys=True)])
    partition_raw = raw.get("table_partitions", {})
    raw_count = len(_raw_items(partition_raw.get("data"))) if partition_raw.get("exists") and partition_raw.get("data") is not None else "未知"
    return "\n\n".join([
        "## 分区接口参数诊断",
        "- 默认不调用外部 API，不做全量分区同步，只生成小样本候选 payload。",
        f"- raw 分区 item 数：**{raw_count}**",
        _table(["表名", "候选 payload"], payload_rows),
    ])


def _task_run_section(store, raw, sample_limit):
    rows = _query(
        store,
        """
        select t.name,
               count(distinct tt.task_id) as task_count,
               count(distinct tr.instance_id) as run_count
        from tables t
        left join task_tables tt on tt.table_name = t.name
        left join task_runs tr on tr.task_id = tt.task_id
        group by t.name
        having task_count = 0 or run_count = 0
        order by t.name
        limit ?
        """,
        (sample_limit,),
    )
    detail_rows = []
    for row in rows:
        if int(row["task_count"] or 0) == 0:
            cause = "缺任务映射：排查任务输入输出/SQL 表名解析"
        else:
            cause = "有任务但缺运行实例：排查时间窗口、keyword、max pages 或 task_id 对齐"
        detail_rows.append([row["name"], row["task_count"], row["run_count"], cause])
    raw_instances = _raw_items(raw.get("task_instances", {}).get("data"))
    return "\n\n".join([
        "## 真实表缺任务/运行实例诊断",
        "- 这些是已同步真实表的映射/运行缺口，不是任务名误造表清理问题。",
        f"- raw task instance item 数：**{len(raw_instances) if raw_instances else '未知'}**",
        _table(["表名", "任务数", "运行实例数", "分类"], detail_rows),
    ])


def _next_actions_section():
    return "\n".join([
        "## 建议下一步",
        "- 如果 raw 质量规则数也低，推动 WeData 源头质量规则治理或扩大同步范围。",
        "- 如果 unknown 抽样可推断层级，增强 `dlc_mcp/wedata.py` 的层级解析。",
        "- 用分区候选 payload 在服务端小样本验证参数后，再配置同步。",
        "- 对缺任务/运行实例表，优先排查表名规范化、任务 SQL 解析、实例时间窗口和分页限制。",
    ])


def _partition_payloads(row, project_id):
    base = {"ProjectId": project_id} if project_id else {}
    payloads = []
    if row["name"]:
        payloads.append({**base, "TableName": row["name"]})
    if row["source_guid"]:
        payloads.append({**base, "TableGuid": row["source_guid"]})
    if row["database_name"] and row["name"]:
        payloads.append({**base, "DatabaseName": row["database_name"], "TableName": row["name"]})
    if row["data_source_id"] and row["database_name"] and row["name"]:
        payloads.append({**base, "DataSourceId": row["data_source_id"], "DatabaseName": row["database_name"], "TableName": row["name"]})
    return payloads


def _raw_quality_rule_count(raw):
    metadata = raw.get("metadata", {}).get("data")
    if not metadata:
        return None
    payload = metadata.get("payload", metadata)
    return len(_raw_items(payload.get("quality_rules", {})))


def _raw_items(response):
    if not response:
        return []
    data = response.get("Response", response) if isinstance(response, dict) else response
    for key in ("Data", "Result"):
        if isinstance(data, dict) and key in data:
            data = data[key]
    if isinstance(data, dict):
        for key in ("Items", "Rows", "List", "Records"):
            if isinstance(data.get(key), list):
                return data[key]
    return data if isinstance(data, list) else []


def _raw_table_name(item):
    return str(item.get("TableName") or item.get("Name") or item.get("tableName") or item.get("name") or "")


def _infer_layer(name, database_name, raw_item):
    values = [
        raw_item.get("Layer"), raw_item.get("TableLayer"), raw_item.get("BizLayer"), raw_item.get("DataLayer"), raw_item.get("layer"),
        database_name, raw_item.get("DatabaseName"), raw_item.get("Database"), raw_item.get("DbName"), raw_item.get("SchemaName"),
        raw_item.get("FolderName"), raw_item.get("FolderPath"), raw_item.get("CategoryName"), raw_item.get("ProjectName"),
        raw_item.get("DatasourceName"), raw_item.get("DataSourceName"), name,
    ]
    for value in values:
        layer = _layer_from_text(value)
        if layer:
            return layer
    return ""


def _layer_from_text(value):
    text = str(value or "").lower().replace("-", "_").replace("/", "_").replace(".", "_")
    parts = [part for part in text.split("_") if part]
    for part in parts:
        if part in LAYER_VALUES:
            return part
    for layer in LAYER_VALUES:
        if text.startswith(layer + "_"):
            return layer
    return ""


def _query(store, sql, params=()):
    return [dict(row) for row in store.conn.execute(sql, params).fetchall()]


def _scalar(store, sql, params=()):
    return store.conn.execute(sql, params).fetchone()[0]


def _table(headers, rows):
    if not rows:
        return "_无数据_"
    return "\n".join([
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
        *["| " + " | ".join(_cell(value) for value in row) + " |" for row in rows],
    ])


def _bullets(lines):
    return "\n".join(f"- {line}" for line in lines)


def _cell(value):
    return ("" if value is None else str(value)).replace("|", "\\|").replace("\n", " ")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
pytest tests/test_diagnose_asset_gaps.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit diagnostic module**

```bash
git add dlc_mcp/diagnose_asset_gaps.py tests/test_diagnose_asset_gaps.py
git commit -m "Add asset gap diagnostic report

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: Add Raw-Dump-Backed Diagnosis Tests

**Files:**
- Modify: `tests/test_diagnose_asset_gaps.py`
- Modify: `dlc_mcp/diagnose_asset_gaps.py`

**Interfaces:**
- Consumes: `render_gap_diagnosis(...)` from Task 1.
- Produces: More precise quality parser-loss and unknown-layer classification behavior in the report.

- [ ] **Step 1: Add failing raw dump diagnosis tests**

Append these test methods inside `DiagnoseAssetGapsTest` in `tests/test_diagnose_asset_gaps.py`:

```python
    def test_raw_quality_rules_greater_than_db_reports_parser_loss(self):
        with TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "assets.db")
            sync_dir = os.path.join(tmpdir, "sync")
            os.makedirs(sync_dir)
            store = self._store(db_path)
            store.upsert_table({"name": "ads_revenue", "layer": "ads"})
            with open(os.path.join(sync_dir, "wedata_metadata.json"), "w", encoding="utf-8") as f:
                f.write('{"payload":{"quality_rules":{"Response":{"Data":{"Items":[{"TableName":"ads_revenue","RuleName":"r1"},{"TableName":"ads_revenue","RuleName":"r2"}]}}}}}')

            report = render_gap_diagnosis(db_path, sync_dir)

        self.assertIn("raw 质量规则数：**2**", report)
        self.assertIn("raw 质量规则多于 DB", report)

    def test_unknown_layer_reports_parser_fixable_from_raw_database(self):
        with TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "assets.db")
            sync_dir = os.path.join(tmpdir, "sync")
            os.makedirs(sync_dir)
            store = self._store(db_path)
            store.upsert_table({"name": "revenue_daily", "layer": "unknown", "database": "ads_mart"})
            with open(os.path.join(sync_dir, "wedata_tables.json"), "w", encoding="utf-8") as f:
                f.write('{"Response":{"Data":{"Items":[{"Name":"revenue_daily","DatabaseName":"ads_mart"}]}}}')

            report = render_gap_diagnosis(db_path, sync_dir)

        self.assertIn("revenue_daily", report)
        self.assertIn("ads", report)
        self.assertIn("抽样中可由名称/库/路径推断：1", report)
```

- [ ] **Step 2: Run tests to verify behavior**

Run:

```bash
pytest tests/test_diagnose_asset_gaps.py -v
```

Expected: PASS if Task 1 implementation already covers these; if it fails, failure should point to raw count or inference text.

- [ ] **Step 3: Fix raw count or inference if tests fail**

If the raw quality count test fails, replace `_raw_quality_rule_count` in `dlc_mcp/diagnose_asset_gaps.py` with:

```python
def _raw_quality_rule_count(raw):
    metadata = raw.get("metadata", {}).get("data")
    if not metadata:
        return None
    payload = metadata.get("payload", metadata)
    quality = payload.get("quality_rules", {}) if isinstance(payload, dict) else {}
    return len(_raw_items(quality))
```

If the unknown inference test fails, replace `_layer_from_text` with:

```python
def _layer_from_text(value):
    text = str(value or "").lower().replace("-", "_").replace("/", "_").replace(".", "_")
    parts = [part for part in text.split("_") if part]
    for part in parts:
        if part in LAYER_VALUES:
            return part
    for layer in LAYER_VALUES:
        if text.startswith(layer + "_") or ("_" + layer + "_") in ("_" + text + "_"):
            return layer
    return ""
```

- [ ] **Step 4: Run tests again**

Run:

```bash
pytest tests/test_diagnose_asset_gaps.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit raw-backed diagnosis behavior**

```bash
git add dlc_mcp/diagnose_asset_gaps.py tests/test_diagnose_asset_gaps.py
git commit -m "Classify raw-backed asset gap causes

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: Improve WeData Parser Layer and Rule Mapping

**Files:**
- Modify: `tests/test_wedata_import.py`
- Modify: `dlc_mcp/wedata.py`

**Interfaces:**
- Consumes: `snapshot_from_api_dump(dump: dict) -> dict`.
- Produces: Better table `layer`, normalized task table names, and quality rule fields.

- [ ] **Step 1: Add failing parser regression tests**

Append these methods inside `WeDataImportTest` in `tests/test_wedata_import.py`:

```python
    def test_infers_layer_from_database_path_and_layer_aliases(self):
        snapshot = snapshot_from_api_dump(
            {
                "tables": {
                    "Response": {
                        "Data": {
                            "Items": [
                                {"Name": "revenue_daily", "DatabaseName": "ads_mart"},
                                {"Name": "seat_daily", "FolderPath": "/warehouse/dws/finance"},
                                {"Name": "order_detail", "BizLayer": "dwd"},
                            ]
                        }
                    }
                }
            }
        )

        self.assertEqual([table["layer"] for table in snapshot["tables"]], ["ads", "dws", "dwd"])

    def test_normalizes_db_prefixed_task_tables(self):
        snapshot = snapshot_from_api_dump(
            {
                "tasks": {
                    "Response": {
                        "Data": {
                            "Items": [
                                {
                                    "TaskId": "t1",
                                    "TaskName": "build_ads_revenue",
                                    "Inputs": "`ods_db`.`ods_order`",
                                    "Outputs": "mart.ads_revenue",
                                }
                            ]
                        }
                    }
                }
            }
        )

        self.assertEqual(snapshot["tasks"][0]["inputs"], ["ods_order"])
        self.assertEqual(snapshot["tasks"][0]["outputs"], ["ads_revenue"])

    def test_maps_quality_rule_table_and_field_aliases(self):
        snapshot = snapshot_from_api_dump(
            {
                "quality_rules": {
                    "Response": {
                        "Data": {
                            "Items": [
                                {
                                    "DatasourceTableName": "mart.ads_revenue",
                                    "RuleTemplateName": "amount_not_null",
                                    "CompareRule": "not_null",
                                    "FieldConfig": "amount",
                                    "QualityDim": "passed",
                                }
                            ]
                        }
                    }
                }
            }
        )

        rule = snapshot["quality_rules"][0]
        self.assertEqual(rule["table_name"], "ads_revenue")
        self.assertEqual(rule["rule_name"], "amount_not_null")
        self.assertEqual(rule["rule_type"], "not_null")
        self.assertEqual(rule["target"], "amount")
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_wedata_import.py::WeDataImportTest::test_infers_layer_from_database_path_and_layer_aliases tests/test_wedata_import.py::WeDataImportTest::test_normalizes_db_prefixed_task_tables tests/test_wedata_import.py::WeDataImportTest::test_maps_quality_rule_table_and_field_aliases -v
```

Expected: FAIL on layer aliases, quoted db-prefixed names, or quality rule aliases.

- [ ] **Step 3: Update table layer mapping**

Replace `_table_from_api` in `dlc_mcp/wedata.py` with:

```python
def _table_from_api(item):
    name = _normalize_table_name(_get(item, "TableName", "Name", "tableName", "name"))
    metadata = item.get("TechnicalMetadata") or {}
    data_source_id = _get(item, "DatasourceId", "DataSourceId", "DatasourceID", "DataSourceID", default="")
    data_source_type = _get(item, "DatasourceType", "DataSourceType", default="")
    database = _get(item, "DatabaseName", "Database", "DbName", "SchemaName", "database")
    return {
        "name": name,
        "guid": _get(item, "Guid", "TableGuid", "TableId", "id"),
        "data_source_id": str(data_source_id or data_source_type or ""),
        "database": database,
        "layer": _table_layer(item, name, database),
        "domain": _get(item, "Domain", "BizDomain", "domain", default=_domain_from_tokens(name.lower().split("_"))),
        "owner": _get(item, "Owner", "OwnerName", "ResponsibleUser", "owner", default=metadata.get("Owner") or ""),
        "description": _get(item, "Description", "Comment", "description"),
        "columns": [_column_from_api(column) for column in _get(item, "Columns", "ColumnList", "columns", default=[])],
    }
```

Add this helper near `_layer_from_name`:

```python
def _table_layer(item, name, database):
    explicit = _get(item, "Layer", "TableLayer", "BizLayer", "DataLayer", "layer")
    for value in (
        explicit,
        database,
        _get(item, "FolderName", "FolderPath", "CategoryName", "ProjectName"),
        _get(item, "DatasourceName", "DataSourceName"),
        name,
    ):
        layer = _layer_from_text(value)
        if layer:
            return layer
    return ""
```

- [ ] **Step 4: Update table-name normalization and layer helper**

Replace `_normalize_table_name` and `_layer_from_name` in `dlc_mcp/wedata.py` with:

```python
def _normalize_table_name(name):
    value = str(name or "").strip().strip("`'\"")
    if not value:
        return ""
    value = value.replace("`.", ".").replace(".`", ".").replace("`", "")
    value = value.split(".")[-1].strip().strip("`'\"")
    if value.startswith(("${", "$[")):
        return ""
    return value if _layer_from_name(value) or "_" in value else ""


def _layer_from_name(name):
    return _layer_from_text(name)


def _layer_from_text(value):
    text = str(value or "").lower().replace("-", "_").replace("/", "_").replace(".", "_")
    parts = [part for part in text.split("_") if part]
    for part in parts:
        if part in {"ods", "dim", "dwd", "dws", "ads"}:
            return part
    return ""
```

- [ ] **Step 5: Update quality rule mapping aliases**

Replace `_quality_rule_from_api` in `dlc_mcp/wedata.py` with:

```python
def _quality_rule_from_api(item):
    return {
        "table_name": _normalize_table_name(_get(item, "TableName", "DatasourceTableName", "Table", "tableName")),
        "rule_name": _get(item, "RuleName", "Name", "RuleTemplateName", "ruleName", default=str(_get(item, "RuleId", default=""))),
        "rule_type": str(_get(item, "RuleType", "RuleTemplateContent", "CompareRule", "Type", "ruleType")),
        "target": _get(item, "Target", "ColumnName", "FieldName", "FieldConfig", "SourceObjectValue", "target"),
        "enabled": _get(item, "MonitorStatus", "Enabled", "IsEnabled", "enabled", default=True) not in (False, 0, "0", "false"),
        "last_status": _get(item, "LastStatus", "Status", "DeployStatus", "QualityDim", "lastStatus", default="configured"),
        "last_checked_at": _get(item, "LastCheckedAt", "CheckTime", "UpdateTime", "lastCheckedAt"),
    }
```

- [ ] **Step 6: Run targeted parser tests**

Run:

```bash
pytest tests/test_wedata_import.py::WeDataImportTest::test_infers_layer_from_database_path_and_layer_aliases tests/test_wedata_import.py::WeDataImportTest::test_normalizes_db_prefixed_task_tables tests/test_wedata_import.py::WeDataImportTest::test_maps_quality_rule_table_and_field_aliases -v
```

Expected: PASS.

- [ ] **Step 7: Run full import tests**

Run:

```bash
pytest tests/test_wedata_import.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit parser improvements**

```bash
git add dlc_mcp/wedata.py tests/test_wedata_import.py
git commit -m "Improve WeData layer and rule parsing

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: Add Partition Payload Helper

**Files:**
- Modify: `tests/test_sync_wedata.py`
- Modify: `dlc_mcp/sync_wedata.py`

**Interfaces:**
- Consumes table metadata dicts with `Name`, `TableName`, `Guid`, `DatabaseName`, and `DatasourceId` variants.
- Produces `partition_payload_candidates(project_id: str, table: dict) -> list[dict]`.

- [ ] **Step 1: Add failing partition payload tests**

Modify the import line in `tests/test_sync_wedata.py` to include `partition_payload_candidates`:

```python
from dlc_mcp.sync_wedata import _catalog_table_names, _filter_new_asset_tables, _instance_window, _list_all, _metadata_table_count, _sync_data_source_tasks, _sync_metadata, _sync_partitions, partition_payload_candidates
```

Append this test method inside `SyncWeDataTest`:

```python
    def test_partition_payload_candidates_include_safe_identifier_combinations(self):
        payloads = partition_payload_candidates(
            "project-1",
            {
                "Name": "ads_revenue",
                "Guid": "guid-1",
                "DatabaseName": "ads_mart",
                "DatasourceId": 55975,
            },
        )

        self.assertEqual(
            payloads,
            [
                {"ProjectId": "project-1", "TableName": "ads_revenue"},
                {"ProjectId": "project-1", "TableGuid": "guid-1"},
                {"ProjectId": "project-1", "DatabaseName": "ads_mart", "TableName": "ads_revenue"},
                {"ProjectId": "project-1", "DataSourceId": "55975", "DatabaseName": "ads_mart", "TableName": "ads_revenue"},
            ],
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/test_sync_wedata.py::SyncWeDataTest::test_partition_payload_candidates_include_safe_identifier_combinations -v
```

Expected: FAIL with `ImportError` or missing function.

- [ ] **Step 3: Implement the helper**

Add this function to `dlc_mcp/sync_wedata.py` after `_sync_partitions`:

```python
def partition_payload_candidates(project_id, table):
    name = table.get("Name") or table.get("TableName") or table.get("name") or table.get("tableName") or ""
    guid = table.get("Guid") or table.get("TableGuid") or table.get("TableId") or ""
    database = table.get("DatabaseName") or table.get("Database") or table.get("DbName") or table.get("SchemaName") or ""
    data_source_id = table.get("DatasourceId") or table.get("DataSourceId") or table.get("DatasourceID") or table.get("DataSourceID") or ""
    base = {"ProjectId": project_id}
    payloads = []
    if name:
        payloads.append({**base, "TableName": name})
    if guid:
        payloads.append({**base, "TableGuid": guid})
    if database and name:
        payloads.append({**base, "DatabaseName": database, "TableName": name})
    if data_source_id and database and name:
        payloads.append({**base, "DataSourceId": str(data_source_id), "DatabaseName": database, "TableName": name})
    return payloads
```

- [ ] **Step 4: Run targeted sync test**

Run:

```bash
pytest tests/test_sync_wedata.py::SyncWeDataTest::test_partition_payload_candidates_include_safe_identifier_combinations -v
```

Expected: PASS.

- [ ] **Step 5: Run full sync tests**

Run:

```bash
pytest tests/test_sync_wedata.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit partition helper**

```bash
git add dlc_mcp/sync_wedata.py tests/test_sync_wedata.py
git commit -m "Add partition payload candidates

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: Add Foundation Report Baseline Labeling

**Files:**
- Modify: `dlc_mcp/check_foundation.py`
- Modify: `tests/test_check_foundation.py`

**Interfaces:**
- Consumes existing `render_foundation_report(store, db_path, gap_types=None, gap_limit=20)`.
- Produces backward-compatible signature: `render_foundation_report(store, db_path, gap_types=None, gap_limit=20, report_source="", quality_rule_count=None, unknown_layer_count=None) -> str`.

- [ ] **Step 1: Add failing foundation report source test**

Append this test method inside `CheckFoundationTest` in `tests/test_check_foundation.py`:

```python
    def test_renders_service_inspection_baselines_when_supplied(self):
        conn = sqlite3.connect(":memory:")
        store = AssetStore(conn)
        store.init_schema()

        report = render_foundation_report(
            store,
            "service.db",
            ["quality"],
            5,
            report_source="latest service asset inspection",
            quality_rule_count=62,
            unknown_layer_count=2141,
        )

        self.assertIn("## 巡检来源", report)
        self.assertIn("latest service asset inspection", report)
        self.assertIn("质量规则基线：**62**", report)
        self.assertIn("unknown 层表基线：**2141**", report)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/test_check_foundation.py::CheckFoundationTest::test_renders_service_inspection_baselines_when_supplied -v
```

Expected: FAIL with unexpected keyword argument `report_source`.

- [ ] **Step 3: Update foundation report signature and section**

In `dlc_mcp/check_foundation.py`, replace `render_foundation_report` with:

```python
def render_foundation_report(store, db_path, gap_types=None, gap_limit=20, report_source="", quality_rule_count=None, unknown_layer_count=None):
    health = store.get_sync_health()
    coverage = store.get_asset_coverage()
    gap_types = gap_types or _split_csv(DEFAULT_GAP_TYPES)

    sections = [
        "# DLC-MCP 资产底座检查报告",
        _format_inspection_source(db_path, report_source, quality_rule_count, unknown_layer_count),
        _format_health(health),
        _format_coverage(coverage),
        _format_core_candidates(store.list_core_candidates(limit=gap_limit)),
    ]
    for gap_type in gap_types:
        sections.append(_format_gaps(store.list_asset_coverage_gaps(gap_type=gap_type, limit=gap_limit)))
    sections.append(_format_next_actions(health, coverage))
    return "\n\n".join(section for section in sections if section)
```

Add this helper above `_format_health`:

```python
def _format_inspection_source(db_path, report_source="", quality_rule_count=None, unknown_layer_count=None):
    lines = [f"数据库：`{_cell(db_path)}`"]
    if report_source:
        lines.append(f"来源：{_cell(report_source)}")
    if quality_rule_count is not None:
        lines.append(f"质量规则基线：**{quality_rule_count}**（来自最新服务端资产库巡检）")
    if unknown_layer_count is not None:
        lines.append(f"unknown 层表基线：**{unknown_layer_count}**（来自最新服务端资产库巡检）")
    return _section("巡检来源", lines)
```

- [ ] **Step 4: Run foundation tests**

Run:

```bash
pytest tests/test_check_foundation.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit foundation report labeling**

```bash
git add dlc_mcp/check_foundation.py tests/test_check_foundation.py
git commit -m "Label service inspection baselines in reports

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: Final Integration and Documentation Check

**Files:**
- Modify only if test failures reveal issues: `dlc_mcp/diagnose_asset_gaps.py`, `dlc_mcp/wedata.py`, `dlc_mcp/sync_wedata.py`, `dlc_mcp/check_foundation.py`

**Interfaces:**
- Consumes all deliverables from Tasks 1-5.
- Produces a passing test suite and a verified CLI smoke command.

- [ ] **Step 1: Run the new diagnostic command against local demo DB**

Run:

```bash
python3 -m dlc_mcp.diagnose_asset_gaps \
  --db data/assets.db \
  --sync-dir data/missing-sync-dir \
  --report-source "latest service asset inspection" \
  --quality-rule-count 62 \
  --unknown-layer-count 2141 \
  --sample-limit 3
```

Expected: command exits 0 and prints Markdown containing:

```text
# DLC-MCP 资产缺口诊断报告
质量规则基线：**62**
unknown 层表基线：**2141**
raw dump 不存在，只能进行 DB-only 诊断
```

- [ ] **Step 2: Run focused tests**

Run:

```bash
pytest tests/test_diagnose_asset_gaps.py tests/test_wedata_import.py tests/test_sync_wedata.py tests/test_check_foundation.py -v
```

Expected: PASS.

- [ ] **Step 3: Run full test suite**

Run:

```bash
pytest -q
```

Expected: PASS.

- [ ] **Step 4: Inspect git diff**

Run:

```bash
git diff --stat HEAD~5..HEAD
```

Expected: Shows only the diagnostic module, tests, and targeted parser/report/sync changes from this plan.

- [ ] **Step 5: Commit any final fixes if needed**

If Step 2 or Step 3 required fixes, commit them:

```bash
git add dlc_mcp tests
git commit -m "Stabilize asset gap diagnostics

Co-Authored-By: Claude <noreply@anthropic.com>"
```

If no fixes were needed, skip this commit.

## Self-Review

- Spec coverage: Task 1 covers read-only diagnostic CLI and baseline labels. Task 2 covers raw-backed classification. Task 3 covers layer, table-name, and quality-rule parser improvements. Task 4 covers bounded partition payload generation. Task 5 covers foundation report source labeling. Task 6 covers smoke and regression verification.
- Placeholder scan: No `TBD`, `TODO`, or unspecified implementation steps remain.
- Type consistency: `render_gap_diagnosis`, `partition_payload_candidates`, and `render_foundation_report` signatures are consistent across tasks and tests.
