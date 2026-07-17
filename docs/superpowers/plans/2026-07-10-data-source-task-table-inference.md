# Data Source Task Parsing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When building a data source inventory, resolve each related WeData task to its real parsed input/output tables (from task payload / SQL), so a task named `m2c_ods_cloud_cost_aliyun_day_di` maps to the real output table `ods_cloud_cost_aliyun_day_di` instead of inventing a table named after the task.

**Architecture:** Keep `GetDataSourceRelatedTasks` as the source of data-source → task relationships, but enrich those related tasks by importing their real task definitions before generating inventory mappings. The import layer should reuse the existing `_task_from_api()` / `_task_table_names()` parser in `dlc_mcp/wedata.py`, so output tables come from explicit task fields or SQL (`insert into`, `insert overwrite`, `create table`) instead of task-name heuristics. The asset store should then link data-source related tasks to already-parsed `task_tables` rows and never create table assets from task names alone.

**Tech Stack:** Python 3, SQLite, unittest/pytest, existing TencentCloud WeData API client wrapper.

## Global Constraints

- Do not invent table facts from task names alone.
- Related task names such as `m2c_ods_cloud_cost_aliyun_day_di` must remain task names, not table names.
- Real table mappings must come from parsed task payload / SQL fields already supported by `dlc_mcp/wedata.py` (`Outputs`, `TargetTables`, `Sql`, `TaskExt`, etc.).
- If a related task cannot be resolved to a task payload with parsed tables, it must remain `未解析` in the data source inventory.
- Preserve existing high-confidence data source → task edges from `GetDataSourceRelatedTasks`.
- Keep cleanup of historical task-name-derived fake tables out of the main import path; use the existing cleanup command separately if needed.

---

## File Structure

- Modify `dlc_mcp/assets.py`
  - Responsibility: persist asset facts and build data source inventory.
  - Remove the unsafe task-name → output-table inference from `replace_data_source_tasks()`.
  - Link data-source related tasks to output tables only when `task_tables` already contains parsed rows for the same `task_id`.

- Modify `dlc_mcp/sync_wedata.py`
  - Responsibility: batch WeData sync job.
  - After `GetDataSourceRelatedTasks`, fetch/import matching task definitions so the existing task parser can extract real outputs.

- Modify `dlc_mcp/live.py`
  - Responsibility: live MCP refresh path.
  - When syncing data sources live, fetch/import matching task definitions before importing `data_source_tasks`.

- Modify `tests/test_wedata_import.py`
  - Responsibility: import and store behavior tests.
  - Add regression coverage that related task names alone do not create fake tables, while parsed task outputs do produce mappings.

- Modify `tests/test_sync_wedata.py`
  - Responsibility: batch sync orchestration tests.
  - Add coverage that data-source related tasks trigger task-definition fetches and those definitions are included in the import dump.

- Modify `tests/test_mcp.py`
  - Responsibility: MCP rendering tests.
  - Seed parsed task outputs explicitly before asserting inventory DDL output.

---

### Task 1: Change Store Behavior to Use Parsed Task Tables Only

**Files:**
- Modify: `dlc_mcp/assets.py:357-429`
- Modify: `dlc_mcp/assets.py:2729-2738`
- Modify: `tests/test_wedata_import.py:399-418`

**Interfaces:**
- Consumes: `task_tables(task_id, table_name, direction)` rows created by `AssetStore.upsert_task()` from parsed task definitions.
- Produces: `AssetStore.replace_data_source_tasks(data_source_id: str, tasks: list[dict]) -> None` that preserves related task rows and edges but does not create tables from `task_name`.
- Produces: data-source → table and task → table edges for existing parsed output mappings.

- [ ] **Step 1: Write the failing tests in `tests/test_wedata_import.py`**

Replace `test_data_source_related_layer_task_maps_output_table_without_global_task` with these two tests:

```python
    def test_data_source_related_layer_task_name_alone_stays_unresolved(self):
        store = AssetStore(sqlite3.connect(":memory:"))
        store.init_schema()
        import_wedata_snapshot(
            store,
            {
                "data_sources": [{"id": "ds_001", "name": "crm_fxiaoke_tx"}],
                "data_source_tasks": [
                    {
                        "data_source_id": "ds_001",
                        "tasks": [{"task_id": "sync_001", "task_name": "m2c_ods_crm_payment_plan_df"}],
                    }
                ],
            },
        )

        inventory = store.get_data_source_inventory(data_source_name="crm_fxiaoke_tx")

        self.assertEqual(store.search_tasks("m2c_ods_crm_payment_plan_df")["results"], [])
        self.assertEqual(store.search_assets("m2c_ods_crm_payment_plan_df")["results"], [])
        self.assertEqual(inventory["tasks"][0]["parse_status"], "未解析")
        self.assertEqual(inventory["tables"], [])
        edges = [dict(row) for row in store._all("select source_type, source_id, target_type, target_id, relation_type, evidence_source, confidence from asset_edges order by relation_type")]
        self.assertIn(
            {
                "source_type": "data_source",
                "source_id": "ds_001",
                "target_type": "task",
                "target_id": "sync_001",
                "relation_type": "has_related_task",
                "evidence_source": "wedata_get_data_source_related_tasks",
                "confidence": "high",
            },
            edges,
        )
        self.assertFalse(any(edge["target_id"] == "m2c_ods_crm_payment_plan_df" and edge["target_type"] == "table" for edge in edges))

    def test_data_source_related_task_uses_parsed_task_output_table(self):
        store = AssetStore(sqlite3.connect(":memory:"))
        store.init_schema()
        import_wedata_snapshot(
            store,
            {
                "tasks": {
                    "Response": {
                        "Data": {
                            "Items": [
                                {
                                    "TaskId": "sync_aliyun",
                                    "TaskName": "m2c_ods_cloud_cost_aliyun_day_di",
                                    "Sql": "insert overwrite table ods_cloud_cost_aliyun_day_di select * from raw_bill;",
                                }
                            ]
                        }
                    }
                },
                "data_sources": [{"id": "ds_001", "name": "crm_fxiaoke_tx"}],
                "data_source_tasks": [
                    {
                        "data_source_id": "ds_001",
                        "tasks": [{"task_id": "sync_aliyun", "task_name": "m2c_ods_cloud_cost_aliyun_day_di"}],
                    }
                ],
            },
        )

        inventory = store.get_data_source_inventory(data_source_name="crm_fxiaoke_tx")

        self.assertEqual(store.search_assets("m2c_ods_cloud_cost_aliyun_day_di")["results"], [])
        self.assertEqual(inventory["tasks"][0]["parse_status"], "已解析")
        self.assertEqual(inventory["tasks"][0]["tables"], [{"table_name": "ods_cloud_cost_aliyun_day_di", "direction": "output"}])
        self.assertEqual([table["name"] for table in inventory["tables"]], ["ods_cloud_cost_aliyun_day_di"])
        self.assertEqual(inventory["tables"][0]["parse_status"], "缺字段")
```

- [ ] **Step 2: Run the new store tests and verify failure**

Run:

```bash
python3 -m pytest tests/test_wedata_import.py::WedataImportTest::test_data_source_related_layer_task_name_alone_stays_unresolved tests/test_wedata_import.py::WedataImportTest::test_data_source_related_task_uses_parsed_task_output_table -v
```

Expected before implementation:

```text
FAILED tests/test_wedata_import.py::WedataImportTest::test_data_source_related_layer_task_name_alone_stays_unresolved
FAILED tests/test_wedata_import.py::WedataImportTest::test_data_source_related_task_uses_parsed_task_output_table
```

- [ ] **Step 3: Replace unsafe inference in `AssetStore.replace_data_source_tasks()`**

In `dlc_mcp/assets.py`, replace the block starting with:

```python
            table_name = _data_source_task_output_table(item.get("task_name", ""))
```

through the end of that `if table_name:` block with:

```python
            for table_name in _parsed_output_tables_for_task(self.conn, item["task_id"]):
                self.upsert_asset_edge(
                    "data_source",
                    data_source_id,
                    "table",
                    table_name,
                    "inferred_output_table",
                    "parsed_wedata_task_output",
                    "high",
                    {"task_id": item["task_id"], "task_name": item.get("task_name", "")},
                    commit=False,
                )
                self.upsert_asset_edge(
                    "task",
                    item["task_id"],
                    "table",
                    table_name,
                    "writes_table",
                    "parsed_wedata_task_output",
                    "high",
                    {"data_source_id": data_source_id, "task_name": item.get("task_name", "")},
                    commit=False,
                )
```

This deliberately does not insert into `tables`; the table row is created by `upsert_task()` when it parses outputs from the real task definition.

- [ ] **Step 4: Replace `_data_source_task_output_table()` helper**

Replace `dlc_mcp/assets.py:2729-2738` with:

```python
def _parsed_output_tables_for_task(conn, task_id):
    return [
        row["table_name"]
        for row in conn.execute(
            """
            select table_name
            from task_tables
            where task_id = ? and direction = 'output'
            order by table_name
            """,
            (task_id,),
        )
    ]
```

- [ ] **Step 5: Run the targeted store tests**

Run:

```bash
python3 -m pytest tests/test_wedata_import.py::WedataImportTest::test_data_source_related_layer_task_name_alone_stays_unresolved tests/test_wedata_import.py::WedataImportTest::test_data_source_related_task_uses_parsed_task_output_table -v
```

Expected:

```text
2 passed
```

- [ ] **Step 6: Run all WeData import tests**

Run:

```bash
python3 -m pytest tests/test_wedata_import.py -v
```

Expected:

```text
passed
```

- [ ] **Step 7: Commit Task 1**

```bash
git add dlc_mcp/assets.py tests/test_wedata_import.py
git commit -m "fix: map data source tasks from parsed outputs"
```

---

### Task 2: Fetch Related Task Definitions During Batch Data Source Sync

**Files:**
- Modify: `dlc_mcp/sync_wedata.py:55-65`
- Add helper functions near `dlc_mcp/sync_wedata.py:146-156`
- Modify: `tests/test_sync_wedata.py`

**Interfaces:**
- Consumes: `_sync_data_source_tasks(client, data_sources_response) -> dict[str, dict]`
- Produces: `_sync_related_task_definitions(client, project_id: str, related_tasks: dict, page_size: int) -> dict`
- Produces: `dump["tasks"]` containing both the original `ListTasks` results and fetched related task definitions before `snapshot_from_api_dump(dump)` is imported.

- [ ] **Step 1: Add a failing batch-sync test**

In `tests/test_sync_wedata.py`, add a fake-client test that verifies related task definitions are fetched. Use the test file’s existing fake client / monkeypatch style. The test body should assert these facts:

```python
    assert any(call[0] == "GetDataSourceRelatedTasks" for call in client.calls)
    assert any(call[0] == "ListTasks" and call[1].get("TaskName") == "m2c_ods_cloud_cost_aliyun_day_di" for call in client.calls)
```

The fake `ListTasks` response for that task name must include:

```python
{
    "TaskId": "20250808124139850",
    "TaskName": "m2c_ods_cloud_cost_aliyun_day_di",
    "Sql": "insert overwrite table ods_cloud_cost_aliyun_day_di select * from raw_bill",
}
```

After the sync runs against a temporary DB, assert:

```python
    store = AssetStore(sqlite3.connect(db_path))
    inventory = store.get_data_source_inventory(data_source_name="crm_fxiaoke_tx")
    assert inventory["tasks"][0]["parse_status"] == "已解析"
    assert inventory["tasks"][0]["tables"] == [{"table_name": "ods_cloud_cost_aliyun_day_di", "direction": "output"}]
    assert [table["name"] for table in inventory["tables"]] == ["ods_cloud_cost_aliyun_day_di"]
```

- [ ] **Step 2: Run the new batch-sync test and verify failure**

Run the exact new test by node id, for example:

```bash
python3 -m pytest tests/test_sync_wedata.py::test_sync_data_sources_fetches_related_task_definitions -v
```

Expected before implementation:

```text
FAILED ... expected ListTasks call for related task definition
```

- [ ] **Step 3: Implement related task definition fetch in `sync_wedata.py`**

After this existing block:

```python
        dump["data_sources"] = data_sources_response
        related_tasks = _sync_data_source_tasks(client, data_sources_response)
        related_tasks_path = os.path.join(work_dir, "wedata_data_source_tasks.json")
        with open(related_tasks_path, "w", encoding="utf-8") as f:
            json.dump(related_tasks, f, ensure_ascii=False, indent=2)
        dump["data_source_tasks"] = related_tasks
```

add:

```python
        related_task_definitions = _sync_related_task_definitions(client, project_id, related_tasks, page_size)
        if _response_item_count(related_task_definitions):
            related_tasks_definitions_path = os.path.join(work_dir, "wedata_data_source_task_definitions.json")
            with open(related_tasks_definitions_path, "w", encoding="utf-8") as f:
                json.dump(related_task_definitions, f, ensure_ascii=False, indent=2)
            dump["tasks"] = _merge_task_responses(dump.get("tasks", {}), related_task_definitions)
```

- [ ] **Step 4: Add helper functions to `sync_wedata.py`**

Add these helpers near `_sync_data_source_tasks()`:

```python
def _sync_related_task_definitions(client, project_id, related_tasks, page_size, progress_every=20):
    definitions = []
    seen_task_ids = set()
    tasks = _flatten_related_tasks(related_tasks)
    total = len(tasks)
    for index, task in enumerate(tasks, start=1):
        task_id = str(task.get("task_id") or "")
        task_name = task.get("task_name") or ""
        if task_id and task_id in seen_task_ids:
            continue
        response = _list_all(client, "ListTasks", {"ProjectId": project_id, "TaskName": task_name}, page_size)
        for item in response.get("Response", {}).get("Data", {}).get("Items") or []:
            if _task_matches_related_item(item, task):
                definitions.append(item)
                if task_id:
                    seen_task_ids.add(task_id)
                break
        if progress_every and (index == total or index % progress_every == 0):
            print(f"synced definitions for {index}/{total} data source related tasks", flush=True)
    return {"Response": {"Data": {"Items": definitions}}}


def _flatten_related_tasks(related_tasks):
    tasks = []
    for response in related_tasks.values():
        for project in response.get("Response", {}).get("Data") or []:
            for group in project.get("TaskInfo") or []:
                for item in group.get("TaskList") or []:
                    tasks.append(
                        {
                            "task_id": str(item.get("TaskId") or item.get("Id") or item.get("id") or ""),
                            "task_name": item.get("TaskName") or item.get("Name") or item.get("name") or "",
                        }
                    )
    return tasks


def _task_matches_related_item(item, related):
    task_id = str(item.get("TaskId") or item.get("Id") or item.get("id") or "")
    task_name = item.get("TaskName") or item.get("Name") or item.get("name") or ""
    related_id = str(related.get("task_id") or "")
    related_name = related.get("task_name") or ""
    return bool((related_id and task_id == related_id) or (related_name and task_name == related_name))


def _merge_task_responses(primary, extra):
    primary_items = primary.get("Response", {}).get("Data", {}).get("Items") or []
    extra_items = extra.get("Response", {}).get("Data", {}).get("Items") or []
    by_id = {}
    for item in [*primary_items, *extra_items]:
        task_id = str(item.get("TaskId") or item.get("Id") or item.get("id") or "")
        key = task_id or item.get("TaskName") or item.get("Name") or item.get("name") or ""
        if key:
            by_id[key] = {**by_id.get(key, {}), **item}
    merged = primary or {"Response": {"Data": {}}}
    merged.setdefault("Response", {}).setdefault("Data", {})["Items"] = list(by_id.values())
    return merged
```

- [ ] **Step 5: Run the batch-sync tests**

Run:

```bash
python3 -m pytest tests/test_sync_wedata.py -v
```

Expected:

```text
passed
```

- [ ] **Step 6: Commit Task 2**

```bash
git add dlc_mcp/sync_wedata.py tests/test_sync_wedata.py
git commit -m "fix: fetch data source related task definitions"
```

---

### Task 3: Fetch Related Task Definitions During Live Data Source Sync

**Files:**
- Modify: `dlc_mcp/live.py:54-64`
- Modify: `tests/test_mcp.py` or existing live tests if present

**Interfaces:**
- Consumes: `LiveWeData.sync_data_sources(query: str = "") -> None`
- Produces: live data-source refresh that imports task definitions before `data_source_tasks` mappings.

- [ ] **Step 1: Add a failing live-sync test**

Add or update a test using a fake live client so calling the MCP `get_data_source_inventory` tool with `live=True` imports:

```python
{
    "TaskId": "20250808124139850",
    "TaskName": "m2c_ods_cloud_cost_aliyun_day_di",
    "Sql": "insert overwrite table ods_cloud_cost_aliyun_day_di select * from raw_bill",
}
```

Assert the rendered MCP output includes:

```python
self.assertIn("m2c_ods_cloud_cost_aliyun_day_di", text)
self.assertIn("ods_cloud_cost_aliyun_day_di", text)
self.assertNotIn("| m2c_ods_cloud_cost_aliyun_day_di | 缺字段 |", text)
```

Also assert the fake client saw a `ListTasks` call with `TaskName == "m2c_ods_cloud_cost_aliyun_day_di"`.

- [ ] **Step 2: Run the new live-sync test and verify failure**

Run the exact new test by node id, for example:

```bash
python3 -m pytest tests/test_mcp.py::McpTest::test_live_data_source_inventory_fetches_related_task_definition -v
```

Expected before implementation:

```text
FAILED ... expected ListTasks call for related task definition
```

- [ ] **Step 3: Implement live related task definition fetch**

In `dlc_mcp/live.py`, add imports:

```python
from .sync_wedata import _merge_task_responses, _sync_related_task_definitions
```

Then replace `sync_data_sources()` body tail:

```python
        self._import({"data_sources": data, "data_source_tasks": related})
```

with:

```python
        task_definitions = _sync_related_task_definitions(self.client, self.project_id, related, self.page_size)
        payload = {"data_sources": data, "data_source_tasks": related}
        if task_definitions.get("Response", {}).get("Data", {}).get("Items"):
            payload["tasks"] = _merge_task_responses({}, task_definitions)
        self._import(payload)
```

- [ ] **Step 4: Run live/MCP tests**

Run:

```bash
python3 -m pytest tests/test_mcp.py -v
```

Expected:

```text
passed
```

- [ ] **Step 5: Commit Task 3**

```bash
git add dlc_mcp/live.py tests/test_mcp.py
git commit -m "fix: parse live data source related tasks"
```

---

### Task 4: Verify Regression and Document Operational Cleanup

**Files:**
- Modify: `docs/server-mcp-wedata-flow.md` or `docs/data-asset-foundation.md` if those docs already describe data-source inventory behavior.
- No generated inventory file should be committed unless explicitly requested.

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces: test evidence and operator guidance that existing fake rows may require `cleanup_derived_tables` or a resync.

- [ ] **Step 1: Run targeted regression tests**

Run:

```bash
python3 -m pytest tests/test_wedata_import.py tests/test_sync_wedata.py tests/test_mcp.py -v
```

Expected:

```text
passed
```

- [ ] **Step 2: Run the full test suite**

Run:

```bash
python3 -m pytest -v
```

Expected:

```text
passed
```

- [ ] **Step 3: Manually verify the exact reported case with an in-memory reproduction**

Run:

```bash
python3 - <<'PY'
import sqlite3
from dlc_mcp.assets import AssetStore
from dlc_mcp.wedata import import_wedata_snapshot

store = AssetStore(sqlite3.connect(':memory:'))
store.init_schema()
import_wedata_snapshot(
    store,
    {
        'tasks': {
            'Response': {
                'Data': {
                    'Items': [
                        {
                            'TaskId': '20250808124139850',
                            'TaskName': 'm2c_ods_cloud_cost_aliyun_day_di',
                            'Sql': 'insert overwrite table ods_cloud_cost_aliyun_day_di select * from raw_bill',
                        }
                    ]
                }
            }
        },
        'data_sources': [{'id': '57738', 'name': 'crm_fxiaoke_tx'}],
        'data_source_tasks': [
            {
                'data_source_id': '57738',
                'tasks': [{'task_id': '20250808124139850', 'task_name': 'm2c_ods_cloud_cost_aliyun_day_di'}],
            }
        ],
    },
)
inventory = store.get_data_source_inventory(data_source_name='crm_fxiaoke_tx')
print(inventory['tasks'][0]['tables'])
print([table['name'] for table in inventory['tables']])
print(store.search_assets('m2c_ods_cloud_cost_aliyun_day_di')['results'])
PY
```

Expected output:

```text
[{'table_name': 'ods_cloud_cost_aliyun_day_di', 'direction': 'output'}]
['ods_cloud_cost_aliyun_day_di']
[]
```

- [ ] **Step 4: Add operational note for existing bad rows**

Add this note to the relevant docs file:

```markdown
### Data source related task parsing

`GetDataSourceRelatedTasks` only proves that a data source is related to a WeData task. The inventory does not treat the related task name as a table name. The sync first fetches/imports the related task definition and then uses the task parser to extract input/output tables from explicit task fields or SQL.

If an older sync created fake tables derived from task names such as `m2c_ods_*`, run `python3 -m dlc_mcp.cleanup_derived_tables --apply` against the affected database after verifying the dry-run output.
```

- [ ] **Step 5: Commit Task 4**

```bash
git add docs/server-mcp-wedata-flow.md docs/data-asset-foundation.md
git commit -m "docs: explain data source task parsing"
```

Only add the doc file that was actually modified.

---

## Self-Review

**Spec coverage:**
- User requested parsing tasks to get real tables: Tasks 1–3 fetch/import task definitions and use existing SQL/output parser.
- Prevents `m2c_...` task names from becoming fake tables: Task 1.
- Handles live MCP inventory and batch sync: Tasks 2 and 3.
- Provides verification for exact reported case: Task 4.

**Placeholder scan:**
- No `TBD`, `TODO`, or unspecified “handle edge cases” steps remain.
- Where test scaffolding depends on existing local fake-client style, the exact assertions and fake response payload are specified.

**Type consistency:**
- `_parsed_output_tables_for_task(conn, task_id) -> list[str]` is used by `replace_data_source_tasks()`.
- `_sync_related_task_definitions(client, project_id, related_tasks, page_size) -> dict` returns a WeData-shaped response consumable by `_merge_task_responses()` and `snapshot_from_api_dump()`.
- Live sync imports the same dump shape as batch sync.
