# Partition Metadata and DLC Partition Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separate partition-table detection from partition fact availability, then sync partition facts from DLC `DescribeTablePartitions` in full and incremental modes.

**Architecture:** Add a focused partition metadata helper module used by both `AssetStore` profile code and `sync_wedata` filtering. `table_partitions` remains the concrete fact table; `is_partitioned` comes from metadata/schema evidence. DLC partition sync runs only for tables proven partitioned and supports `full` and `incremental` modes without deleting historical facts.

**Tech Stack:** Python 3 standard library, SQLite via `sqlite3`, existing `unittest` test suite, existing Tencent Cloud client abstraction.

## Global Constraints

- Partitioning is a table property proven by table metadata or schema, not by the existence of `table_partitions` rows.
- DLC `DescribeTablePartitions` is the authoritative partition sync API for this workflow.
- WeData `ListTablePartitions InvalidAction` remains action/version unsupported, not a payload parameter problem.
- Do not introduce a new schema table in this iteration.
- Do not delete historical partition facts during sync.
- Do not perform expensive live row counts against business tables.
- Use TDD: each production change starts with a failing test.
- Existing response fields should remain where possible; change semantics and add fields rather than removing fields.

---

## File Structure

- Create `dlc_mcp/partitioning.py`
  - Owns partition metadata inference and date matching helpers.
  - Exposes pure functions that do not depend on `AssetStore` or network clients.
- Create `tests/test_partitioning.py`
  - Unit tests for metadata evidence extraction, `dt` fallback, non-partitioned tables, and date default/matching helpers.
- Modify `dlc_mcp/assets.py`
  - Use `partitioning.partition_metadata_for_table()` in `get_table_partition_profile()`.
  - Return `partition_fact_available`, `partition_fact_status`, `partition_keys`, `partition_evidence`, and `partition_confidence`.
- Modify `tests/test_assets.py`
  - Add tests for profile semantics when a table has `dt` but no partition facts, has no partition evidence, and has explicit raw partition keys.
- Modify `dlc_mcp/sync_wedata.py`
  - Add `WEDATA_PARTITION_SYNC_MODE=full|incremental` behavior.
  - Default incremental target date to yesterday when `WEDATA_PARTITION_DATE` is absent.
  - Filter partition sync calls to partitioned tables only.
  - Keep DLC full mode from sending `PartitionDate` and keep incremental date matching as client-side filtering.
- Modify `tests/test_sync_wedata.py`
  - Add failing tests for DLC full mode, incremental default date, date matching, and filtering non-partitioned tables before DLC calls.
- Modify `dlc_mcp/mcp.py`
  - Update Markdown formatter for partition profiles to display fact availability and partition evidence.
- Modify `tests/test_mcp.py`
  - Assert readable partition profile output includes partition fact status and does not describe missing facts as non-partitioned.
- Modify `docs/server-mcp-wedata-flow.md`
  - Document DLC partition sync settings and full/incremental commands.
- Modify `docs/superpowers/specs/2026-07-16-partition-metadata-sync-design.md` only if implementation discoveries require clarifying the approved design.

---

### Task 1: Add Pure Partition Metadata Helpers

**Files:**
- Create: `dlc_mcp/partitioning.py`
- Create: `tests/test_partitioning.py`

**Interfaces:**
- Produces: `partition_metadata_for_table(table: dict, columns: list[dict], partition_rows: list[dict] | None = None) -> dict`
- Produces: `partition_sync_target_date(today: date | None = None) -> str`
- Produces: `partition_matches_date(item: dict, partition_date: str) -> bool`
- Consumes: no project-local functions.

- [ ] **Step 1: Write failing tests for metadata inference**

Create `tests/test_partitioning.py` with:

```python
import unittest
from datetime import date

from dlc_mcp.partitioning import (
    partition_matches_date,
    partition_metadata_for_table,
    partition_sync_target_date,
)


class PartitioningTest(unittest.TestCase):
    def test_dt_column_proves_partitioned_table_without_partition_facts(self):
        metadata = partition_metadata_for_table(
            {"name": "ods_cloud_cost_baidu_day_di", "raw": {}},
            [{"name": "dt", "type": "string"}, {"name": "id", "type": "bigint"}],
            [],
        )

        self.assertTrue(metadata["is_partitioned"])
        self.assertEqual(metadata["partition_keys"], ["dt"])
        self.assertIn("column:dt", metadata["partition_evidence"])
        self.assertEqual(metadata["partition_confidence"], "medium")

    def test_raw_partition_keys_are_high_confidence_evidence(self):
        metadata = partition_metadata_for_table(
            {"name": "ads_revenue", "raw": {"PartitionKeys": [{"Name": "biz_date"}]}},
            [{"name": "biz_date", "type": "string"}],
            [],
        )

        self.assertTrue(metadata["is_partitioned"])
        self.assertEqual(metadata["partition_keys"], ["biz_date"])
        self.assertIn("raw:PartitionKeys:biz_date", metadata["partition_evidence"])
        self.assertEqual(metadata["partition_confidence"], "high")

    def test_table_without_partition_metadata_columns_or_facts_is_not_partitioned(self):
        metadata = partition_metadata_for_table(
            {"name": "dim_customer", "raw": {}},
            [{"name": "customer_id", "type": "string"}],
            [],
        )

        self.assertFalse(metadata["is_partitioned"])
        self.assertEqual(metadata["partition_keys"], [])
        self.assertEqual(metadata["partition_evidence"], [])
        self.assertEqual(metadata["partition_confidence"], "none")

    def test_existing_partition_rows_are_supporting_evidence(self):
        metadata = partition_metadata_for_table(
            {"name": "ads_revenue", "raw": {}},
            [{"name": "id", "type": "bigint"}],
            [{"partition_name": "dt=20260715"}],
        )

        self.assertTrue(metadata["is_partitioned"])
        self.assertEqual(metadata["partition_keys"], [])
        self.assertIn("facts:table_partitions", metadata["partition_evidence"])
        self.assertEqual(metadata["partition_confidence"], "low")

    def test_incremental_target_date_defaults_to_yesterday(self):
        self.assertEqual(partition_sync_target_date(date(2026, 7, 16)), "2026-07-15")

    def test_partition_date_matching_supports_dashed_and_compact_dt(self):
        self.assertTrue(partition_matches_date({"Partition": "dt=20260715"}, "2026-07-15"))
        self.assertTrue(partition_matches_date({"PartitionName": "dt=2026-07-15"}, "2026-07-15"))
        self.assertFalse(partition_matches_date({"Partition": "dt=20260714"}, "2026-07-15"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python3 -m unittest tests.test_partitioning -v
```

Expected: FAIL or ERROR with `ModuleNotFoundError: No module named 'dlc_mcp.partitioning'`.

- [ ] **Step 3: Implement the helper module**

Create `dlc_mcp/partitioning.py`:

```python
from datetime import date, timedelta


COMMON_PARTITION_COLUMNS = {"dt"}
RAW_PARTITION_FIELDS = (
    "PartitionKeys",
    "PartitionColumns",
    "PartitionFields",
    "Partitions",
    "PartitionInfo",
    "TablePartition",
)
PARTITION_NAME_FIELDS = ("PartitionName", "Partition", "PartitionSpec", "Name", "partition_name")


def partition_metadata_for_table(table, columns, partition_rows=None):
    partition_rows = partition_rows or []
    raw = table.get("raw") or {}
    keys = []
    evidence = []

    for field in RAW_PARTITION_FIELDS:
        for key in _partition_keys_from_raw_value(raw.get(field)):
            if key not in keys:
                keys.append(key)
                evidence.append(f"raw:{field}:{key}")

    if keys:
        return {
            "is_partitioned": True,
            "partition_keys": keys,
            "partition_evidence": evidence,
            "partition_confidence": "high",
        }

    for column in columns or []:
        name = str(column.get("name") or "").strip()
        if name in COMMON_PARTITION_COLUMNS and name not in keys:
            keys.append(name)
            evidence.append(f"column:{name}")

    if keys:
        return {
            "is_partitioned": True,
            "partition_keys": keys,
            "partition_evidence": evidence,
            "partition_confidence": "medium",
        }

    if partition_rows:
        return {
            "is_partitioned": True,
            "partition_keys": [],
            "partition_evidence": ["facts:table_partitions"],
            "partition_confidence": "low",
        }

    return {
        "is_partitioned": False,
        "partition_keys": [],
        "partition_evidence": [],
        "partition_confidence": "none",
    }


def partition_sync_target_date(today=None):
    today = today or date.today()
    return f"{today - timedelta(days=1):%Y-%m-%d}"


def partition_matches_date(item, partition_date):
    if not partition_date:
        return True
    expected = {partition_date, partition_date.replace("-", "")}
    for field in PARTITION_NAME_FIELDS:
        value = str(item.get(field) or "")
        if any(f"dt={candidate}" in value or value == candidate for candidate in expected):
            return True
    return False


def _partition_keys_from_raw_value(value):
    if not value:
        return []
    if isinstance(value, str):
        return [value] if _looks_like_partition_key(value) else []
    if isinstance(value, dict):
        names = []
        for key in ("Name", "ColumnName", "FieldName", "name", "columnName", "fieldName"):
            if _looks_like_partition_key(value.get(key)):
                names.append(str(value[key]))
        for key in RAW_PARTITION_FIELDS + ("Keys", "Columns", "Fields", "items", "Items"):
            names.extend(_partition_keys_from_raw_value(value.get(key)))
        return _dedupe(names)
    if isinstance(value, list):
        names = []
        for item in value:
            names.extend(_partition_keys_from_raw_value(item))
        return _dedupe(names)
    return []


def _looks_like_partition_key(value):
    text = str(value or "").strip()
    return bool(text and text not in {"[]", "{}"})


def _dedupe(values):
    result = []
    seen = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
python3 -m unittest tests.test_partitioning -v
```

Expected: PASS all 6 tests.

- [ ] **Step 5: Commit**

```bash
git add dlc_mcp/partitioning.py tests/test_partitioning.py
git commit -m "feat: infer partition metadata from table schema"
```

---

### Task 2: Update Table Partition Profile Semantics

**Files:**
- Modify: `dlc_mcp/assets.py:1659-1685`
- Test: `tests/test_assets.py`

**Interfaces:**
- Consumes: `partition_metadata_for_table(table: dict, columns: list[dict], partition_rows: list[dict] | None = None) -> dict`
- Produces: `AssetStore.get_table_partition_profile(table_name: str, partition_date: str = "") -> dict` with new keys `partition_fact_available`, `partition_fact_status`, `partition_keys`, `partition_evidence`, `partition_confidence`.

- [ ] **Step 1: Write failing tests for profile semantics**

In `tests/test_assets.py`, add these methods inside `AssetStoreTest`:

```python
    def test_partition_profile_uses_dt_column_even_without_partition_facts(self):
        store = make_store()
        store.upsert_table({"name": "ods_cloud_cost_baidu_day_di", "database": "byai_bigdata"})
        store.upsert_column("ods_cloud_cost_baidu_day_di", "dt", "string", "", 1)
        store.upsert_column("ods_cloud_cost_baidu_day_di", "id", "bigint", "", 2)

        profile = store.get_table_partition_profile("ods_cloud_cost_baidu_day_di")

        self.assertTrue(profile["is_partitioned"])
        self.assertFalse(profile["partition_fact_available"])
        self.assertEqual(profile["partition_fact_status"], "missing")
        self.assertEqual(profile["partition_keys"], ["dt"])
        self.assertIn("column:dt", profile["partition_evidence"])
        self.assertEqual(profile["partition_count"], 0)
        self.assertIn("未同步到分区统计事实", "；".join(profile["reasons"]))

    def test_partition_profile_reports_not_partitioned_without_metadata_or_facts(self):
        store = make_store()
        store.upsert_table({"name": "dim_customer", "database": "byai_bigdata"})
        store.upsert_column("dim_customer", "customer_id", "string", "", 1)

        profile = store.get_table_partition_profile("dim_customer")

        self.assertFalse(profile["is_partitioned"])
        self.assertFalse(profile["partition_fact_available"])
        self.assertEqual(profile["partition_fact_status"], "not_partitioned")
        self.assertEqual(profile["partition_keys"], [])

    def test_partition_profile_uses_raw_partition_keys(self):
        store = make_store()
        store.upsert_table({"name": "ads_revenue", "database": "byai_bigdata", "raw": {"PartitionKeys": [{"Name": "biz_date"}]}})
        store.upsert_column("ads_revenue", "biz_date", "string", "", 1)

        profile = store.get_table_partition_profile("ads_revenue")

        self.assertTrue(profile["is_partitioned"])
        self.assertEqual(profile["partition_keys"], ["biz_date"])
        self.assertEqual(profile["partition_confidence"], "high")
        self.assertEqual(profile["partition_fact_status"], "missing")
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python3 -m unittest tests.test_assets.AssetStoreTest.test_partition_profile_uses_dt_column_even_without_partition_facts tests.test_assets.AssetStoreTest.test_partition_profile_reports_not_partitioned_without_metadata_or_facts tests.test_assets.AssetStoreTest.test_partition_profile_uses_raw_partition_keys -v
```

Expected: FAIL with missing keys such as `partition_fact_available` or wrong `is_partitioned` value.

- [ ] **Step 3: Update `assets.py` imports**

Near the top of `dlc_mcp/assets.py`, after standard imports, add:

```python
from .partitioning import partition_metadata_for_table
```

- [ ] **Step 4: Replace `get_table_partition_profile()` implementation**

In `dlc_mcp/assets.py`, replace the body of `get_table_partition_profile()` with:

```python
    def get_table_partition_profile(self, table_name, partition_date=""):
        table = self._one("select * from tables where name = ?", (table_name,))
        if not table:
            return {"error": "table_not_found", "table_name": table_name}
        table_data = self._table_dict(table)
        columns = [dict(row) for row in self._all("select name, type, description from columns where table_name = ? order by ordinal, name", (table_name,))]
        all_rows = [dict(row) for row in self._all("select * from table_partitions where table_name = ? order by partition_date desc, partition_name desc", (table_name,))]
        partition_metadata = partition_metadata_for_table(table_data, columns, all_rows)
        recent = all_rows[:30]
        target = None
        if partition_date:
            target = next((row for row in all_rows if row.get("partition_date") == partition_date or partition_date in row.get("partition_name", "")), None)
        elif all_rows:
            target = all_rows[0]
        fact_available = bool(all_rows)
        fact_status = _partition_fact_status(partition_metadata["is_partitioned"], fact_available)
        status = _partition_health_status(target, recent, partition_date) if fact_available else "unknown"
        reasons = _partition_health_reasons(status, target, recent, partition_date)
        if partition_metadata["is_partitioned"] and not fact_available:
            reasons = ["表元数据/字段显示为分区表，但未同步到分区统计事实。"]
        elif not partition_metadata["is_partitioned"]:
            reasons = ["未发现分区字段、分区元数据或分区统计事实。"]
        suggestions = _partition_health_suggestions(status)
        if partition_metadata["is_partitioned"] and not fact_available:
            suggestions = ["运行 DLC 分区同步后再判断分区健康。"]
        return {
            "table_name": table_name,
            "partition_date": partition_date,
            "is_partitioned": partition_metadata["is_partitioned"],
            "partition_keys": partition_metadata["partition_keys"],
            "partition_evidence": partition_metadata["partition_evidence"],
            "partition_confidence": partition_metadata["partition_confidence"],
            "partition_fact_available": fact_available,
            "partition_fact_status": fact_status,
            "partition_count": len(all_rows),
            "latest_partition": all_rows[0] if all_rows else None,
            "earliest_partition": all_rows[-1] if all_rows else None,
            "target_partition": target,
            "recent_partitions": recent,
            "total_rows": sum(row.get("row_count") or 0 for row in all_rows),
            "total_storage_bytes": sum(row.get("storage_bytes") or 0 for row in all_rows),
            "health_status": status,
            "health_label": _partition_health_label(status),
            "reasons": reasons,
            "suggestions": suggestions,
        }
```

Add this helper near `_partition_health_status()`:

```python
def _partition_fact_status(is_partitioned, fact_available):
    if fact_available:
        return "available"
    if is_partitioned:
        return "missing"
    return "not_partitioned"
```

- [ ] **Step 5: Run profile tests to verify they pass**

Run:

```bash
python3 -m unittest tests.test_assets.AssetStoreTest.test_partition_profile_uses_dt_column_even_without_partition_facts tests.test_assets.AssetStoreTest.test_partition_profile_reports_not_partitioned_without_metadata_or_facts tests.test_assets.AssetStoreTest.test_partition_profile_uses_raw_partition_keys -v
```

Expected: PASS.

- [ ] **Step 6: Run existing partition profile tests**

Run:

```bash
python3 -m unittest tests.test_assets.AssetStoreTest.test_table_partition_profile_reports_volume_and_health tests.test_assets.AssetStoreTest.test_table_partition_profile_flags_missing_and_empty_partitions -v
```

Expected: PASS; existing fact-backed health behavior remains intact.

- [ ] **Step 7: Commit**

```bash
git add dlc_mcp/assets.py tests/test_assets.py
git commit -m "fix: separate partition metadata from partition facts"
```

---

### Task 3: Add DLC Full and Incremental Partition Sync Modes

**Files:**
- Modify: `dlc_mcp/sync_wedata.py:0-662`
- Test: `tests/test_sync_wedata.py`

**Interfaces:**
- Consumes: `partition_matches_date(item: dict, partition_date: str) -> bool`
- Consumes: `partition_sync_target_date(today: date | None = None) -> str`
- Consumes: `partition_metadata_for_table(table: dict, columns: list[dict], partition_rows: list[dict] | None = None) -> dict`
- Produces: `_partition_sync_mode() -> str`
- Produces: `_partition_date_for_sync() -> str`
- Produces: `_filter_partition_table_names(table_names: list[str], catalog_tables: dict, store: AssetStore | None = None) -> list[str]`

- [ ] **Step 1: Write failing tests for sync mode and filtering**

In `tests/test_sync_wedata.py`, add these imports:

```python
from dlc_mcp.sync_wedata import (
    _filter_partition_table_names,
    _partition_date_for_sync,
    _partition_sync_mode,
)
```

Add these test methods to `SyncWeDataTest`:

```python
    def test_partition_sync_mode_defaults_to_incremental(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(_partition_sync_mode(), "incremental")

    def test_partition_date_for_sync_defaults_to_yesterday(self):
        with patch.dict(os.environ, {}, clear=True), patch("dlc_mcp.sync_wedata.date") as fake_date:
            fake_date.today.return_value = datetime(2026, 7, 16).date()
            self.assertEqual(_partition_date_for_sync(), "2026-07-15")

    def test_dlc_full_partition_sync_keeps_all_partitions(self):
        with patch.dict(os.environ, {"WEDATA_PARTITION_SERVICE": "dlc", "DLC_CATALOG": "DataLakeCatalog", "WEDATA_PARTITION_SYNC_MODE": "full"}, clear=False), patch("dlc_mcp.sync_wedata._partition_client", return_value=FakeDlcPartitionClient()):
            response = _sync_partitions(
                FakePartitionClient(),
                "project",
                ["ads_revenue"],
                1,
                progress_every=0,
                catalog_tables={"ads_revenue": {"DatabaseName": "ads_mart"}},
            )

        self.assertEqual([item["Partition"] for item in response["Response"]["Data"]["Items"]], ["dt=20260708", "dt=20260709"])

    def test_dlc_incremental_partition_sync_defaults_to_yesterday(self):
        with patch.dict(os.environ, {"WEDATA_PARTITION_SERVICE": "dlc", "DLC_CATALOG": "DataLakeCatalog", "WEDATA_PARTITION_SYNC_MODE": "incremental"}, clear=False), patch("dlc_mcp.sync_wedata._partition_client", return_value=FakeDlcPartitionClient()), patch("dlc_mcp.sync_wedata.date") as fake_date:
            fake_date.today.return_value = datetime(2026, 7, 9).date()
            response = _sync_partitions(
                FakePartitionClient(),
                "project",
                ["ads_revenue"],
                1,
                progress_every=0,
                catalog_tables={"ads_revenue": {"DatabaseName": "ads_mart"}},
            )

        self.assertEqual([item["Partition"] for item in response["Response"]["Data"]["Items"]], ["dt=20260708"])

    def test_partition_sync_filters_to_partitioned_tables_from_store(self):
        conn = sqlite3.connect(":memory:")
        store = AssetStore(conn)
        store.init_schema()
        store.upsert_table({"name": "ods_partitioned", "database": "byai_bigdata"})
        store.upsert_column("ods_partitioned", "dt", "string", "", 1)
        store.upsert_table({"name": "dim_customer", "database": "byai_bigdata"})
        store.upsert_column("dim_customer", "customer_id", "string", "", 1)

        filtered = _filter_partition_table_names(["dim_customer", "ods_partitioned"], {}, store)

        self.assertEqual(filtered, ["ods_partitioned"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python3 -m unittest tests.test_sync_wedata.SyncWeDataTest.test_partition_sync_mode_defaults_to_incremental tests.test_sync_wedata.SyncWeDataTest.test_partition_date_for_sync_defaults_to_yesterday tests.test_sync_wedata.SyncWeDataTest.test_dlc_full_partition_sync_keeps_all_partitions tests.test_sync_wedata.SyncWeDataTest.test_dlc_incremental_partition_sync_defaults_to_yesterday tests.test_sync_wedata.SyncWeDataTest.test_partition_sync_filters_to_partitioned_tables_from_store -v
```

Expected: FAIL or ERROR because helper functions are missing and full/incremental behavior is not implemented.

- [ ] **Step 3: Update imports in `sync_wedata.py`**

At the top of `dlc_mcp/sync_wedata.py`, change:

```python
from datetime import datetime, timedelta
```

to:

```python
from datetime import date, datetime, timedelta
```

Add:

```python
from .partitioning import partition_matches_date, partition_metadata_for_table, partition_sync_target_date
```

- [ ] **Step 4: Add sync mode helper functions**

Add these functions near the existing partition helpers:

```python
def _partition_sync_mode():
    mode = os.environ.get("WEDATA_PARTITION_SYNC_MODE", "incremental").strip().lower()
    return mode if mode in {"full", "incremental"} else "incremental"


def _partition_date_for_sync():
    return os.environ.get("WEDATA_PARTITION_DATE", "") or partition_sync_target_date(date.today())


def _filter_partition_table_names(table_names, catalog_tables=None, store=None):
    catalog_tables = catalog_tables or {}
    result = []
    for table_name in sorted(set(table_names)):
        table = _partition_table_metadata(table_name, catalog_tables, store)
        columns = _partition_table_columns(table_name, store)
        rows = _partition_table_fact_rows(table_name, store)
        metadata = partition_metadata_for_table(table, columns, rows)
        if metadata["is_partitioned"]:
            result.append(table_name)
    return result


def _partition_table_metadata(table_name, catalog_tables, store):
    if store:
        row = store._one("select * from tables where name = ?", (table_name,))
        if row:
            return store._table_dict(row)
    item = catalog_tables.get(table_name) or {}
    return {"name": table_name, "raw": item, "database": item.get("DatabaseName") or item.get("Database") or item.get("DbName", "")}


def _partition_table_columns(table_name, store):
    if not store:
        return []
    return [dict(row) for row in store._all("select name, type, description from columns where table_name = ? order by ordinal, name", (table_name,))]


def _partition_table_fact_rows(table_name, store):
    if not store:
        return []
    return [dict(row) for row in store._all("select * from table_partitions where table_name = ? order by partition_date desc, partition_name desc", (table_name,))]
```

- [ ] **Step 5: Update `_sync_partitions()` mode behavior**

In `_sync_partitions()`, replace:

```python
    partition_date = os.environ.get("WEDATA_PARTITION_DATE", "")
```

with:

```python
    mode = _partition_sync_mode()
    partition_date = "" if mode == "full" else _partition_date_for_sync()
```

Keep the existing WeData payload date branch, but rely on `partition_matches_date()` for item filtering:

```python
            if partition_matches_date(item, partition_date):
                items.append(item)
```

Do not send `PartitionDate` to DLC. The current branch already avoids this when `WEDATA_PARTITION_SERVICE=dlc`; keep that behavior.

- [ ] **Step 6: Filter partition tables in `main()`**

In `main()`, before the `if os.environ.get("WEDATA_SYNC_PARTITIONS") == "1":` block, ensure `store` exists before partition sync:

```python
    store = AssetStore(sqlite3.connect(db_path))
    store.init_schema()
```

Move the existing later `store = AssetStore(...)` block so it is not duplicated.

Inside the partition sync block, replace:

```python
        partitions_response = _sync_partitions(client, project_id, table_names, page_size, catalog_tables=catalog_tables)
```

with:

```python
        partition_table_names = _filter_partition_table_names(table_names, catalog_tables, store)
        partitions_response = _sync_partitions(client, project_id, partition_table_names, page_size, catalog_tables=catalog_tables)
```

- [ ] **Step 7: Run sync tests to verify they pass**

Run:

```bash
python3 -m unittest tests.test_sync_wedata -v
```

Expected: PASS all sync tests.

- [ ] **Step 8: Commit**

```bash
git add dlc_mcp/sync_wedata.py tests/test_sync_wedata.py
git commit -m "feat: sync DLC partitions in full and incremental modes"
```

---

### Task 4: Update MCP Markdown Output for Partition Profiles

**Files:**
- Modify: `dlc_mcp/mcp.py:1434-1457`
- Test: `tests/test_mcp.py`

**Interfaces:**
- Consumes: `get_table_partition_profile()` response fields from Task 2.
- Produces: `_format_table_partition_profile(data: dict) -> str` output that includes partition keys, evidence, and fact status.

- [ ] **Step 1: Write failing formatter test**

In `tests/test_mcp.py`, add this test inside `McpTest`:

```python
    def test_table_partition_profile_shows_partition_metadata_without_facts(self):
        self.store.upsert_table({"name": "ods_cloud_cost_baidu_day_di", "database": "byai_bigdata"})
        self.store.upsert_column("ods_cloud_cost_baidu_day_di", "dt", "string", "", 1)

        response = handle_request(
            self.store,
            {
                "jsonrpc": "2.0",
                "id": 99,
                "method": "tools/call",
                "params": {"name": "get_table_partition_profile", "arguments": {"table_name": "ods_cloud_cost_baidu_day_di"}},
            },
        )

        text = response["result"]["content"][0]["text"]
        self.assertIn("是否分区表：**True**", text)
        self.assertIn("分区字段：`dt`", text)
        self.assertIn("分区事实：`missing`", text)
        self.assertIn("表元数据/字段显示为分区表，但未同步到分区统计事实", text)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python3 -m unittest tests.test_mcp.McpTest.test_table_partition_profile_shows_partition_metadata_without_facts -v
```

Expected: FAIL because formatter does not include the new metadata/fact status lines.

- [ ] **Step 3: Update `_format_table_partition_profile()`**

In `dlc_mcp/mcp.py`, update the section lines in `_format_table_partition_profile(data)` so the first `_section()` includes:

```python
                    f"是否分区表：**{data.get('is_partitioned')}**",
                    f"分区字段：`{', '.join(data.get('partition_keys') or [])}`",
                    f"分区证据：{_cell('、'.join(data.get('partition_evidence') or []))}",
                    f"分区事实：`{_cell(data.get('partition_fact_status', ''))}`",
                    f"分区事实可用：**{data.get('partition_fact_available', False)}**",
```

Keep the existing partition count, latest partition, earliest partition, rows, storage, and health lines.

- [ ] **Step 4: Run formatter test to verify it passes**

Run:

```bash
python3 -m unittest tests.test_mcp.McpTest.test_table_partition_profile_shows_partition_metadata_without_facts -v
```

Expected: PASS.

- [ ] **Step 5: Run all MCP tests**

Run:

```bash
python3 -m unittest tests.test_mcp -v
```

Expected: PASS all MCP tests. If an existing unrelated assertion depends on old wording, update the assertion to the new explicit wording rather than removing coverage.

- [ ] **Step 6: Commit**

```bash
git add dlc_mcp/mcp.py tests/test_mcp.py
git commit -m "feat: show partition metadata and fact status"
```

---

### Task 5: Update Governance/Workbook Semantics for Missing Partition Facts

**Files:**
- Modify: `dlc_mcp/assets.py`
- Test: `tests/test_assets.py`

**Interfaces:**
- Consumes: `get_table_partition_profile()` response fields from Task 2.
- Produces: any existing governance helper that uses partition profile treats missing facts as insufficiency, not no-data evidence.

- [ ] **Step 1: Write failing governance semantics test**

In `tests/test_assets.py`, add this method inside `AssetStoreTest`:

```python
    def test_partition_fact_missing_is_not_zero_data_evidence(self):
        store = make_store()
        store.upsert_table({"name": "ods_cloud_cost_baidu_day_di", "database": "byai_bigdata"})
        store.upsert_column("ods_cloud_cost_baidu_day_di", "dt", "string", "", 1)

        profile = store.get_table_partition_profile("ods_cloud_cost_baidu_day_di")

        self.assertTrue(profile["is_partitioned"])
        self.assertFalse(profile["partition_fact_available"])
        self.assertEqual(profile["partition_fact_status"], "missing")
        self.assertNotIn("总行数为0", "；".join(profile["reasons"]))
        self.assertNotIn("最近", "；".join(profile["reasons"]))
```

- [ ] **Step 2: Run test to verify it fails if Task 2 did not already cover it**

Run:

```bash
python3 -m unittest tests.test_assets.AssetStoreTest.test_partition_fact_missing_is_not_zero_data_evidence -v
```

Expected before Task 2 implementation: FAIL with old no-facts/no-data reasons. Expected after Task 2: PASS. If it already passes, keep the test as regression coverage.

- [ ] **Step 3: Inspect and update any partition-based useless-table helper in `assets.py`**

Search within `dlc_mcp/assets.py` for references to these labels or keys:

```text
recently no partition
最近一个月无分区
partition_count
is_partitioned
total_rows
```

If a helper computes “no recent partition” or “partition no data” from missing facts, update it to use this rule:

```python
partition_fact_available = partition.get("partition_fact_available", False)
recent_no_partition = bool(partition_fact_available and computed_recent_partition_count == 0)
recent_partition_no_data = bool(partition_fact_available and computed_recent_partition_row_count == 0)
partition_fact_insufficient = bool(partition.get("is_partitioned") and not partition_fact_available)
```

- [ ] **Step 4: Run asset tests**

Run:

```bash
python3 -m unittest tests.test_assets -v
```

Expected: PASS all asset tests.

- [ ] **Step 5: Commit**

```bash
git add dlc_mcp/assets.py tests/test_assets.py
git commit -m "fix: treat missing partition facts as insufficient evidence"
```

---

### Task 6: Document DLC Partition Sync Commands

**Files:**
- Modify: `docs/server-mcp-wedata-flow.md:269-321`
- Test: manual docs review through grep.

**Interfaces:**
- Consumes: environment variables implemented in Task 3.
- Produces: operator runbook for full and incremental partition sync.

- [ ] **Step 1: Update the runbook with full and incremental commands**

In `docs/server-mcp-wedata-flow.md`, add this section after the existing partition support note near line 278:

```markdown
### DLC partition sync

Partition-table status is a table metadata property. The MCP partition profile uses table metadata/schema to decide whether a table is partitioned, and uses `table_partitions` only for concrete partition facts.

Use DLC `DescribeTablePartitions` as the authoritative partition sync path:

```bash
cd /opt/dlc-mcp/DLC-MCP
set -a
. /etc/dlc-mcp/env
set +a
WEDATA_SYNC_PARTITIONS=1 \
WEDATA_PARTITION_SERVICE=dlc \
DLC_API_VERSION=2021-01-25 \
DLC_CATALOG=DataLakeCatalog \
WEDATA_PARTITION_SYNC_MODE=full \
python3 -m dlc_mcp.sync_wedata
```

For scheduled incremental sync, omit `WEDATA_PARTITION_DATE` to update yesterday by default:

```bash
cd /opt/dlc-mcp/DLC-MCP
set -a
. /etc/dlc-mcp/env
set +a
WEDATA_SYNC_PARTITIONS=1 \
WEDATA_PARTITION_SERVICE=dlc \
DLC_API_VERSION=2021-01-25 \
DLC_CATALOG=DataLakeCatalog \
WEDATA_PARTITION_SYNC_MODE=incremental \
python3 -m dlc_mcp.sync_wedata
```

To backfill one explicit date:

```bash
WEDATA_SYNC_PARTITIONS=1 \
WEDATA_PARTITION_SERVICE=dlc \
WEDATA_PARTITION_SYNC_MODE=incremental \
WEDATA_PARTITION_DATE=2026-07-15 \
python3 -m dlc_mcp.sync_wedata
```
```

- [ ] **Step 2: Check docs mention both modes**

Run:

```bash
grep -n "WEDATA_PARTITION_SYNC_MODE" docs/server-mcp-wedata-flow.md
```

Expected: output includes `full` and `incremental` examples.

- [ ] **Step 3: Commit**

```bash
git add docs/server-mcp-wedata-flow.md
git commit -m "docs: document DLC partition sync modes"
```

---

### Task 7: Run Final Verification and Remote Dry Run

**Files:**
- No source file changes expected.
- Uses existing test suite and MCP tools.

**Interfaces:**
- Consumes all prior task outputs.
- Produces verified local behavior and a safe remote dry-run procedure.

- [ ] **Step 1: Run focused local tests**

Run:

```bash
python3 -m unittest tests.test_partitioning tests.test_assets tests.test_sync_wedata tests.test_mcp -v
```

Expected: PASS all tests.

- [ ] **Step 2: Verify Baidu table profile locally if local DB has data**

Run:

```bash
python3 - <<'PY'
import sqlite3
from dlc_mcp.assets import AssetStore
store = AssetStore(sqlite3.connect('/Users/leve/Documents/DLC-Agent/data/assets.db'))
store.init_schema()
print(store.get_table_partition_profile('ods_cloud_cost_baidu_day_di'))
PY
```

Expected if the local DB has the table and `dt` column: `is_partitioned` is `True` and `partition_fact_status` is `missing` or `available`. If local DB does not have the table, use MCP after deployment.

- [ ] **Step 3: Remote deployment dry run only**

After code is deployed to the remote server, run only profile and sync dry checks first:

```bash
ssh root@64.186.234.87 'cd /opt/dlc-mcp/DLC-MCP && python3 -m unittest tests.test_partitioning tests.test_assets.AssetStoreTest.test_partition_profile_uses_dt_column_even_without_partition_facts tests.test_sync_wedata.SyncWeDataTest.test_dlc_incremental_partition_sync_defaults_to_yesterday -v'
```

Expected: PASS.

- [ ] **Step 4: Query MCP partition profile before partition sync**

Use the native `dlc-mcp` MCP tool:

```text
get_table_partition_profile(table_name="ods_cloud_cost_baidu_day_di")
```

Expected:

```text
是否分区表：True
分区事实：missing
分区字段：dt
```

- [ ] **Step 5: Run one explicit-date incremental sync on server**

Use a date known to exist for the table. Example command shape:

```bash
ssh root@64.186.234.87 'cd /opt/dlc-mcp/DLC-MCP && set -a && . /etc/dlc-mcp/env && set +a && WEDATA_SYNC_PARTITIONS=1 WEDATA_PARTITION_SERVICE=dlc WEDATA_PARTITION_SYNC_MODE=incremental WEDATA_PARTITION_DATE=2026-07-15 python3 -m dlc_mcp.sync_wedata'
```

Expected: command completes, writes `/data/dlc-mcp/sync/wedata_table_partitions.json`, and reports synced partitions or bounded per-table failures.

- [ ] **Step 6: Query MCP partition profile after partition sync**

Use the native `dlc-mcp` MCP tool again:

```text
get_table_partition_profile(table_name="ods_cloud_cost_baidu_day_di")
```

Expected if DLC returned the table's partition: `partition_fact_available=True`, `partition_count>0`, and latest/recent partition details show rows or empty partition status based on returned facts.

- [ ] **Step 7: Commit final verification notes if docs changed during verification**

If no files changed, do not create a commit. If docs were adjusted based on remote findings:

```bash
git add docs/server-mcp-wedata-flow.md docs/superpowers/specs/2026-07-16-partition-metadata-sync-design.md
git commit -m "docs: clarify partition sync verification"
```

---

## Self-Review

### Spec coverage

- Partition property from metadata/schema: Task 1 and Task 2.
- `table_partitions` as facts only: Task 2 and Task 5.
- DLC authoritative sync: Task 3 and Task 6.
- Full sync: Task 3 tests and implementation.
- Incremental yesterday-default sync: Task 1 date helper and Task 3 sync behavior.
- No deletion of historical facts: Task 3 keeps upsert-only behavior; no delete step is introduced.
- Excel/governance semantics: Task 5 updates missing-fact reasoning so downstream workbook generation does not get no-partition/no-data evidence from missing facts.
- Error handling: Task 3 preserves per-table `PartitionFailures` and existing InvalidAction behavior; Task 6 documents operational usage.
- Verification: Task 7.

### Placeholder scan

The plan contains no TBD, TODO, “implement later”, or unspecified test steps. All code steps include concrete snippets or exact commands.

### Type consistency

- `partition_metadata_for_table()` return keys match Task 2 and Task 3 usage.
- `partition_matches_date()` replaces existing `_partition_matches_date()` behavior with the same item/date boolean contract.
- `partition_sync_target_date()` returns `YYYY-MM-DD` strings consumed by `_partition_date_for_sync()`.
- `get_table_partition_profile()` new keys match formatter and test assertions.
