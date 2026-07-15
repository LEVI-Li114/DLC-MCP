# DLC/WeData Technical Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stabilize DLC/WeData daily incremental sync, expose MCP cache/live query freshness, and add execution-oriented governance report fields.

**Architecture:** Keep the existing shell → `dlc_mcp.sync_wedata` → SQLite/`AssetStore` → `dlc_mcp.mcp` flow. Add small, testable helpers for changed-table aliases, changed-task enrichment, bounded repair targets, MCP query metadata, and daily report execution summaries without introducing a new sync framework.

**Tech Stack:** Bash, Python 3, SQLite, pytest/unittest, existing `AssetStore`, existing JSON-RPC MCP server.

## Global Constraints

- Do not add a ticket table.
- Do not persist solved/ignored state.
- Do not add a daily report push/notification workflow.
- Do not add a full trend dashboard.
- Do not perform a large sync framework rewrite.
- Do not assume sparse quality rules are a sync failure.
- Do not change JSON-RPC envelopes.
- Do not remove existing daily report keys.
- Do not rename existing store methods.
- Keep old table increment variables working.
- Keep quality-rule gaps visible.
- Keep default daily sync bounded through limits.
- `ListTablePartitions InvalidAction` remains action/version unsupported, not a parameter bug.

---

## File Structure

- Modify: `deploy/sync-wedata-incremental.sh`
  - Owns production daily defaults for changed table fields, task change windows, partition date, instance window, and health checks.
- Modify: `dlc_mcp/sync_wedata.py`
  - Owns WeData API pulls, changed-table/changed-task filtering, enrichment, repair target resolution, raw dumps, and SQLite import orchestration.
- Modify: `dlc_mcp/mcp.py`
  - Owns JSON-RPC tool dispatch and Markdown formatting. Add query metadata without changing the JSON-RPC envelope.
- Modify: `dlc_mcp/assets.py`
  - Owns cached asset facts and governance report generation. Add execution summary, responsibility buckets, and acceptance criteria.
- Modify: `tests/test_sync_wedata.py`
  - Covers shell-compatible defaults indirectly through env helpers, changed-task filtering, enrichment limits, repair target resolution, and partition regression.
- Modify: `tests/test_mcp.py`
  - Covers query metadata for cache hit, live success, live failure, and snapshot-only tools.
- Modify: `tests/test_assets.py`
  - Covers daily report execution summary, responsibility buckets, acceptance criteria, and prioritization.

---

### Task 1: Daily Increment Defaults and Table Change Aliases

**Files:**
- Modify: `deploy/sync-wedata-incremental.sh:31-58`
- Modify: `dlc_mcp/sync_wedata.py:41-45, 521-553`
- Test: `tests/test_sync_wedata.py`

**Interfaces:**
- Consumes: existing `_filter_new_asset_tables(table_names, catalog_tables, start, end) -> list[str]`.
- Produces: `_table_change_start() -> str`, `_table_change_end() -> str`, `_table_change_date_fields() -> str`, `_table_change_strict() -> str`.
- Produces: alias-aware `_item_dates(item: dict) -> list[date]` using `WEDATA_TABLE_CHANGE_DATE_FIELDS` before `WEDATA_NEW_ASSET_DATE_FIELDS`.

- [ ] **Step 1: Write failing tests for table change aliases and structure-update fields**

Add the import names to `tests/test_sync_wedata.py` line 10:

```python
from dlc_mcp.sync_wedata import (
    _catalog_table_names,
    _filter_new_asset_tables,
    _instance_window,
    _item_dates,
    _list_all,
    _metadata_table_count,
    _partition_payload,
    _sync_data_source_tasks,
    _sync_metadata,
    _sync_partitions,
    _table_change_date_fields,
    _table_change_end,
    _table_change_start,
    _table_change_strict,
    main,
    partition_payload_candidates,
)
```

Add these tests inside `class SyncWeDataTest(unittest.TestCase):` after `test_catalog_table_names_reads_name_variants`:

```python
    def test_table_change_aliases_prefer_new_env_names(self):
        with patch.dict(
            os.environ,
            {
                "WEDATA_CHANGED_TABLE_START": "2026-07-14",
                "WEDATA_NEW_ASSET_START": "2026-07-01",
                "WEDATA_CHANGED_TABLE_END": "2026-07-15",
                "WEDATA_NEW_ASSET_END": "2026-07-02",
                "WEDATA_TABLE_CHANGE_DATE_FIELDS": "structure_update,update",
                "WEDATA_NEW_ASSET_DATE_FIELDS": "create",
                "WEDATA_TABLE_CHANGE_STRICT": "0",
                "WEDATA_NEW_ASSET_STRICT": "1",
            },
            clear=False,
        ):
            self.assertEqual(_table_change_start(), "2026-07-14")
            self.assertEqual(_table_change_end(), "2026-07-15")
            self.assertEqual(_table_change_date_fields(), "structure_update,update")
            self.assertEqual(_table_change_strict(), "0")

    def test_table_change_date_fields_default_to_structure_update_update_create(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(_table_change_date_fields(), "structure_update,update,create")

    def test_item_dates_reads_structure_update_alias_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            dates = _item_dates({"StructUpdateTime": "2026-07-14 03:04:05"})

        self.assertEqual([str(value) for value in dates], ["2026-07-14"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python3 -m pytest tests/test_sync_wedata.py::SyncWeDataTest::test_table_change_aliases_prefer_new_env_names tests/test_sync_wedata.py::SyncWeDataTest::test_table_change_date_fields_default_to_structure_update_update_create tests/test_sync_wedata.py::SyncWeDataTest::test_item_dates_reads_structure_update_alias_by_default -q
```

Expected: FAIL because `_table_change_*` helpers are not defined and default date fields still come from the old env lookup.

- [ ] **Step 3: Implement alias-aware table change helpers**

In `dlc_mcp/sync_wedata.py`, add these helpers immediately before `_filter_new_asset_tables`:

```python
def _env_first(*names, default=""):
    for name in names:
        value = os.environ.get(name)
        if value not in (None, ""):
            return value
    return default


def _table_change_start():
    return _env_first("WEDATA_CHANGED_TABLE_START", "WEDATA_NEW_ASSET_START")


def _table_change_end():
    return _env_first("WEDATA_CHANGED_TABLE_END", "WEDATA_NEW_ASSET_END")


def _table_change_date_fields():
    return _env_first("WEDATA_TABLE_CHANGE_DATE_FIELDS", "WEDATA_NEW_ASSET_DATE_FIELDS", default="structure_update,update,create")


def _table_change_strict():
    return _env_first("WEDATA_TABLE_CHANGE_STRICT", "WEDATA_NEW_ASSET_STRICT", default="1")
```

Update the metadata filter block in `main()` from:

```python
        if os.environ.get("WEDATA_NEW_ASSET_START") and os.environ.get("WEDATA_NEW_ASSET_END"):
            table_names = _filter_new_asset_tables(table_names, catalog_tables, os.environ["WEDATA_NEW_ASSET_START"], os.environ["WEDATA_NEW_ASSET_END"])
```

to:

```python
        table_change_start = _table_change_start()
        table_change_end = _table_change_end()
        if table_change_start and table_change_end:
            table_names = _filter_new_asset_tables(table_names, catalog_tables, table_change_start, table_change_end)
```

Update `_filter_new_asset_tables()` strict checks:

```python
def _filter_new_asset_tables(table_names, catalog_tables, start, end):
    if not catalog_tables:
        if _table_change_strict() == "1":
            raise RuntimeError("WEDATA_CHANGED_TABLE_START requires WEDATA_SYNC_TABLE_CATALOG=1")
        return []
    window_start = _parse_date(start)
    window_end = _parse_date(end)
    if not any(_item_dates(item) for item in catalog_tables.values()) and _table_change_strict() == "1":
        raise RuntimeError("ListTable response has no recognized create/update/structure_update time fields for changed asset sync")
    names = set(table_names)
    return sorted(
        name
        for name, item in catalog_tables.items()
        if name in names and any(_date_in_window(value, window_start, window_end) for value in _item_dates(item))
    )
```

Update `_item_dates()` to use the alias helper:

```python
def _item_dates(item):
    dates = []
    date_groups = {part.strip().lower() for part in _table_change_date_fields().split(",") if part.strip()}
    fields = []
    if "create" in date_groups:
        fields.extend(("CreateTime", "CreateDate", "CreatedAt", "CreateAt", "GmtCreate"))
    if "update" in date_groups:
        fields.extend(("UpdateTime", "ModifyTime", "ModifiedAt", "LastModifyTime"))
    if "structure_update" in date_groups:
        fields.extend(("StructUpdateTime",))
    for field in fields:
        if item.get(field):
            value = _parse_date(str(item[field]))
            if value:
                dates.append(value)
    return dates
```

- [ ] **Step 4: Update the daily incremental shell defaults and logs**

In `deploy/sync-wedata-incremental.sh`, replace line 39:

```bash
export WEDATA_NEW_ASSET_DATE_FIELDS="${DLC_MCP_DAILY_NEW_ASSET_DATE_FIELDS:-create}"
```

with:

```bash
export WEDATA_NEW_ASSET_DATE_FIELDS="${DLC_MCP_DAILY_NEW_ASSET_DATE_FIELDS:-structure_update,update,create}"
export WEDATA_CHANGED_TABLE_START="${WEDATA_CHANGED_TABLE_START:-$WEDATA_NEW_ASSET_START}"
export WEDATA_CHANGED_TABLE_END="${WEDATA_CHANGED_TABLE_END:-$WEDATA_NEW_ASSET_END}"
export WEDATA_TABLE_CHANGE_DATE_FIELDS="${WEDATA_TABLE_CHANGE_DATE_FIELDS:-$WEDATA_NEW_ASSET_DATE_FIELDS}"
export WEDATA_TABLE_CHANGE_STRICT="${WEDATA_TABLE_CHANGE_STRICT:-$WEDATA_NEW_ASSET_STRICT}"
export WEDATA_TASK_CHANGE_START="${WEDATA_TASK_CHANGE_START:-$YESTERDAY}"
export WEDATA_TASK_CHANGE_END="${WEDATA_TASK_CHANGE_END:-$YESTERDAY}"
export WEDATA_TASK_CHANGE_DATE_FIELDS="${DLC_MCP_DAILY_TASK_CHANGE_DATE_FIELDS:-update,modify,create}"
export WEDATA_TASK_CHANGE_STRICT="${WEDATA_TASK_CHANGE_STRICT:-0}"
```

After the existing metadata log line at line 54, add:

```bash
echo "table_change_window: $WEDATA_CHANGED_TABLE_START..$WEDATA_CHANGED_TABLE_END"
echo "task_change_window: $WEDATA_TASK_CHANGE_START..$WEDATA_TASK_CHANGE_END"
echo "task_change_date_fields: $WEDATA_TASK_CHANGE_DATE_FIELDS"
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
python3 -m pytest tests/test_sync_wedata.py::SyncWeDataTest::test_table_change_aliases_prefer_new_env_names tests/test_sync_wedata.py::SyncWeDataTest::test_table_change_date_fields_default_to_structure_update_update_create tests/test_sync_wedata.py::SyncWeDataTest::test_item_dates_reads_structure_update_alias_by_default -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add deploy/sync-wedata-incremental.sh dlc_mcp/sync_wedata.py tests/test_sync_wedata.py
git commit -m "feat: default daily table sync to changed assets

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: Changed Task Filtering and Enrichment

**Files:**
- Modify: `dlc_mcp/sync_wedata.py:20-28, 167-205, 271-314, 340-351`
- Test: `tests/test_sync_wedata.py`

**Interfaces:**
- Consumes: `_list_all(client, action, payload, page_size, max_pages=None) -> dict`.
- Consumes: `_enrich_related_task_definition(client, project_id, item, related, page_size) -> dict`.
- Produces: `_task_item_dates(item: dict) -> list[date]`.
- Produces: `_filter_changed_tasks(tasks_response: dict, start: str, end: str) -> list[dict]`.
- Produces: `_enrich_changed_task_definitions(client, project_id: str, changed_tasks: list[dict], page_size: int) -> dict` returning `{"Response": {"Data": {"Items": [...]}}}`.
- Produces: `_sync_changed_task_codes(client, project_id: str, changed_tasks: list[dict]) -> tuple[dict, list[dict]]` returning task-code response map and failures.
- Produces: `_sync_changed_task_relations(client, project_id: str, changed_tasks: list[dict], page_size: int) -> tuple[dict, list[dict]]` returning relation response map and failures.

- [ ] **Step 1: Write failing tests for changed task date filtering**

Add these names to the import from `dlc_mcp.sync_wedata` in `tests/test_sync_wedata.py`:

```python
    _filter_changed_tasks,
    _task_item_dates,
```

Add these tests inside `class SyncWeDataTest(unittest.TestCase):`:

```python
    def test_task_item_dates_reads_update_modify_and_create_fields(self):
        with patch.dict(os.environ, {"WEDATA_TASK_CHANGE_DATE_FIELDS": "update,modify,create"}, clear=False):
            dates = _task_item_dates(
                {
                    "UpdateTime": "2026-07-14 11:22:33",
                    "ModifyTime": "2026-07-15 01:02:03",
                    "CreateTime": "2026-07-13 04:05:06",
                }
            )

        self.assertEqual([str(value) for value in dates], ["2026-07-14", "2026-07-15", "2026-07-13"])

    def test_filter_changed_tasks_uses_update_window_and_keeps_only_matching_items(self):
        tasks_response = {
            "Response": {
                "Data": {
                    "Items": [
                        {"TaskId": "task_changed", "TaskName": "changed", "UpdateTime": "2026-07-14 10:00:00"},
                        {"TaskId": "task_old", "TaskName": "old", "UpdateTime": "2026-07-10 10:00:00"},
                        {"TaskId": "task_no_date", "TaskName": "no_date"},
                    ]
                }
            }
        }
        with patch.dict(os.environ, {"WEDATA_TASK_CHANGE_DATE_FIELDS": "update", "WEDATA_TASK_CHANGE_STRICT": "0"}, clear=False):
            changed = _filter_changed_tasks(tasks_response, "2026-07-14", "2026-07-14")

        self.assertEqual([task["TaskId"] for task in changed], ["task_changed"])

    def test_filter_changed_tasks_missing_dates_returns_empty_when_not_strict(self):
        tasks_response = {"Response": {"Data": {"Items": [{"TaskId": "task_no_date", "TaskName": "no_date"}]}}}
        with patch.dict(os.environ, {"WEDATA_TASK_CHANGE_DATE_FIELDS": "update", "WEDATA_TASK_CHANGE_STRICT": "0"}, clear=False):
            changed = _filter_changed_tasks(tasks_response, "2026-07-14", "2026-07-14")

        self.assertEqual(changed, [])

    def test_filter_changed_tasks_missing_dates_raises_when_strict(self):
        tasks_response = {"Response": {"Data": {"Items": [{"TaskId": "task_no_date", "TaskName": "no_date"}]}}}
        with patch.dict(os.environ, {"WEDATA_TASK_CHANGE_DATE_FIELDS": "update", "WEDATA_TASK_CHANGE_STRICT": "1"}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "ListTasks response has no recognized task change time fields"):
                _filter_changed_tasks(tasks_response, "2026-07-14", "2026-07-14")
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python3 -m pytest tests/test_sync_wedata.py::SyncWeDataTest::test_task_item_dates_reads_update_modify_and_create_fields tests/test_sync_wedata.py::SyncWeDataTest::test_filter_changed_tasks_uses_update_window_and_keeps_only_matching_items tests/test_sync_wedata.py::SyncWeDataTest::test_filter_changed_tasks_missing_dates_returns_empty_when_not_strict tests/test_sync_wedata.py::SyncWeDataTest::test_filter_changed_tasks_missing_dates_raises_when_strict -q
```

Expected: FAIL because changed-task helpers do not exist.

- [ ] **Step 3: Implement changed task date helpers**

In `dlc_mcp/sync_wedata.py`, add these helpers immediately after `_item_dates()`:

```python
def _task_change_date_fields():
    return os.environ.get("WEDATA_TASK_CHANGE_DATE_FIELDS", "update,modify,create")


def _task_change_strict():
    return os.environ.get("WEDATA_TASK_CHANGE_STRICT", "0")


def _task_item_dates(item):
    dates = []
    date_groups = {part.strip().lower() for part in _task_change_date_fields().split(",") if part.strip()}
    fields = []
    if "create" in date_groups:
        fields.extend(("CreateTime", "CreateDate", "CreatedAt", "CreateAt", "GmtCreate"))
    if "update" in date_groups or "modify" in date_groups:
        fields.extend(("UpdateTime", "ModifyTime", "ModifiedAt", "LastModifyTime", "UpdateDate"))
    if "schedule" in date_groups:
        fields.extend(("ScheduleTime", "ScheduleUpdateTime"))
    for field in fields:
        if item.get(field):
            value = _parse_date(str(item[field]))
            if value:
                dates.append(value)
    return dates


def _filter_changed_tasks(tasks_response, start, end):
    items = tasks_response.get("Response", {}).get("Data", {}).get("Items") or []
    if not start or not end:
        return []
    if not any(_task_item_dates(item) for item in items):
        message = "ListTasks response has no recognized task change time fields; changed task enrichment skipped"
        if _task_change_strict() == "1":
            raise RuntimeError(message)
        print(message, flush=True)
        return []
    window_start = _parse_date(start)
    window_end = _parse_date(end)
    changed = [
        item
        for item in items
        if any(_date_in_window(value, window_start, window_end) for value in _task_item_dates(item))
    ]
    limit = int(os.environ.get("WEDATA_CHANGED_TASK_LIMIT", "500"))
    return changed[:limit]
```

- [ ] **Step 4: Run changed task date tests**

Run:

```bash
python3 -m pytest tests/test_sync_wedata.py::SyncWeDataTest::test_task_item_dates_reads_update_modify_and_create_fields tests/test_sync_wedata.py::SyncWeDataTest::test_filter_changed_tasks_uses_update_window_and_keeps_only_matching_items tests/test_sync_wedata.py::SyncWeDataTest::test_filter_changed_tasks_missing_dates_returns_empty_when_not_strict tests/test_sync_wedata.py::SyncWeDataTest::test_filter_changed_tasks_missing_dates_raises_when_strict -q
```

Expected: PASS.

- [ ] **Step 5: Write failing tests for changed task enrichment**

Add these names to the import from `dlc_mcp.sync_wedata`:

```python
    _enrich_changed_task_definitions,
    _merge_task_responses,
    _sync_changed_task_codes,
    _sync_changed_task_relations,
```

Add this fake client above `class SyncWeDataTest(unittest.TestCase):`:

```python
class FakeChangedTaskClient:
    def __init__(self):
        self.calls = []

    def call(self, action, payload):
        self.calls.append((action, dict(payload)))
        if action == "ListProcessLineage":
            return {
                "Response": {
                    "Data": {
                        "Items": [
                            {
                                "Source": [{"ResourceName": "ods_source", "ResourceType": "TABLE"}],
                                "Target": [{"ResourceName": "ads_changed_output", "ResourceType": "TABLE"}],
                            }
                        ],
                        "TotalPageNumber": 1,
                    }
                }
            }
        if action == "GetTaskCode":
            return {"Response": {"Data": {"CodeInfo": "c2VsZWN0IDE7", "CodeFileSize": 9}, "RequestId": "req"}}
        if action == "ListUpstreamTasks":
            return {"Response": {"Data": {"Items": [{"TaskId": "task_up", "TaskName": "upstream"}], "TotalPageNumber": 1}}}
        if action == "ListDownstreamTasks":
            return {"Response": {"Data": {"Items": [{"TaskId": "task_down", "TaskName": "downstream"}], "TotalPageNumber": 1}}}
        if action == "GetTask":
            return {"Response": {"Data": {"TaskId": payload.get("TaskId"), "TaskName": "changed_task"}}}
        return {"Response": {"Data": {"Items": [], "TotalPageNumber": 1}}}
```

Add tests inside `class SyncWeDataTest(unittest.TestCase):`:

```python
    def test_enrich_changed_task_definitions_adds_lineage_outputs_without_dropping_catalog(self):
        client = FakeChangedTaskClient()
        primary = {
            "Response": {
                "Data": {
                    "Items": [
                        {"TaskId": "task_changed", "TaskName": "changed_task", "UpdateTime": "2026-07-14 10:00:00"},
                        {"TaskId": "task_old", "TaskName": "old_task", "UpdateTime": "2026-07-10 10:00:00"},
                    ]
                }
            }
        }
        changed = [primary["Response"]["Data"]["Items"][0]]

        enriched = _enrich_changed_task_definitions(client, "project", changed, 100)
        merged = _merge_task_responses(primary, enriched)
        by_id = {item["TaskId"]: item for item in merged["Response"]["Data"]["Items"]}

        self.assertIn("task_old", by_id)
        self.assertEqual(by_id["task_changed"]["OutputTables"], ["ads_changed_output"])
        self.assertEqual(by_id["task_changed"]["InputTables"], ["ods_source"])
        self.assertTrue(any(action == "ListProcessLineage" for action, payload in client.calls))

    def test_sync_changed_task_codes_obeys_limit_and_returns_failures(self):
        client = FakeChangedTaskClient()
        changed = [
            {"TaskId": "task_1", "TaskName": "one"},
            {"TaskId": "task_2", "TaskName": "two"},
        ]
        with patch.dict(os.environ, {"WEDATA_CHANGED_TASK_CODE_LIMIT": "1", "WEDATA_SYNC_CHANGED_TASK_CODES": "1"}, clear=False):
            codes, failures = _sync_changed_task_codes(client, "project", changed)

        self.assertEqual(sorted(codes), ["task_1"])
        self.assertEqual(failures, [])
        self.assertEqual([action for action, payload in client.calls].count("GetTaskCode"), 1)

    def test_sync_changed_task_relations_fetches_upstream_and_downstream(self):
        client = FakeChangedTaskClient()
        relations, failures = _sync_changed_task_relations(client, "project", [{"TaskId": "task_1", "TaskName": "one"}], 100)

        self.assertEqual(failures, [])
        self.assertIn("task_1", relations["upstream"])
        self.assertIn("task_1", relations["downstream"])
        self.assertIn("ListUpstreamTasks", [action for action, payload in client.calls])
        self.assertIn("ListDownstreamTasks", [action for action, payload in client.calls])
```

- [ ] **Step 6: Run enrichment tests to verify they fail**

Run:

```bash
python3 -m pytest tests/test_sync_wedata.py::SyncWeDataTest::test_enrich_changed_task_definitions_adds_lineage_outputs_without_dropping_catalog tests/test_sync_wedata.py::SyncWeDataTest::test_sync_changed_task_codes_obeys_limit_and_returns_failures tests/test_sync_wedata.py::SyncWeDataTest::test_sync_changed_task_relations_fetches_upstream_and_downstream -q
```

Expected: FAIL because enrichment helpers do not exist.

- [ ] **Step 7: Implement changed task enrichment helpers**

In `dlc_mcp/sync_wedata.py`, add these helpers after `_merge_task_responses()`:

```python
def _task_identity(item):
    task_id = str(item.get("TaskId") or item.get("Id") or item.get("id") or item.get("task_id") or "")
    task_name = item.get("TaskName") or item.get("Name") or item.get("name") or item.get("task_name") or ""
    return task_id, task_name


def _enrich_changed_task_definitions(client, project_id, changed_tasks, page_size, progress_every=20):
    definitions = []
    total = len(changed_tasks)
    for index, item in enumerate(changed_tasks, start=1):
        task_id, task_name = _task_identity(item)
        related = {"task_id": task_id, "task_name": task_name}
        enriched = _enrich_related_task_definition(client, project_id, dict(item), related, page_size)
        definitions.append(enriched)
        if progress_every and (index == total or index % progress_every == 0):
            print(f"enriched changed tasks for {index}/{total}", flush=True)
    return {"Response": {"Data": {"Items": definitions}}}


def _sync_changed_task_codes(client, project_id, changed_tasks):
    if os.environ.get("WEDATA_SYNC_CHANGED_TASK_CODES", "1") != "1":
        return {}, []
    limit = int(os.environ.get("WEDATA_CHANGED_TASK_CODE_LIMIT", "200"))
    responses = {}
    failures = []
    for item in changed_tasks[:limit]:
        task_id, task_name = _task_identity(item)
        payload = {"ProjectId": project_id}
        if task_id:
            payload["TaskId"] = task_id
        elif task_name:
            payload["TaskName"] = task_name
        else:
            continue
        try:
            response = client.call("GetTaskCode", payload)
            error = response.get("Response", {}).get("Error")
            if error:
                failures.append({"task_id": task_id, "task_name": task_name, "action": "GetTaskCode", "error": f"{error.get('Code')} {error.get('Message')}"})
                continue
            responses[task_id or task_name] = response
        except Exception as exc:
            failures.append({"task_id": task_id, "task_name": task_name, "action": "GetTaskCode", "error": str(exc)})
    return responses, failures


def _sync_changed_task_relations(client, project_id, changed_tasks, page_size):
    relations = {"upstream": {}, "downstream": {}}
    failures = []
    for item in changed_tasks:
        task_id, task_name = _task_identity(item)
        if not task_id:
            continue
        for direction, action in (("upstream", "ListUpstreamTasks"), ("downstream", "ListDownstreamTasks")):
            try:
                response = _list_all(client, action, {"ProjectId": project_id, "TaskId": task_id}, page_size)
                relations[direction][task_id] = response
            except Exception as exc:
                failures.append({"task_id": task_id, "task_name": task_name, "action": action, "error": str(exc)})
    return relations, failures
```

- [ ] **Step 8: Wire changed task enrichment into `main()`**

In `main()`, immediately after `dump = {"tasks": tasks_response}`, add:

```python
    changed_tasks = []
    task_change_start = os.environ.get("WEDATA_TASK_CHANGE_START", "")
    task_change_end = os.environ.get("WEDATA_TASK_CHANGE_END", "")
    if task_change_start and task_change_end:
        changed_tasks = _filter_changed_tasks(tasks_response, task_change_start, task_change_end)
        print(f"found {len(changed_tasks)} changed WeData tasks", flush=True)
        if changed_tasks:
            changed_task_definitions = _enrich_changed_task_definitions(client, project_id, changed_tasks, page_size)
            dump["tasks"] = _merge_task_responses(dump["tasks"], changed_task_definitions)
            changed_task_codes, code_failures = _sync_changed_task_codes(client, project_id, changed_tasks)
            changed_task_relations, relation_failures = _sync_changed_task_relations(client, project_id, changed_tasks, page_size)
            dump["changed_task_codes"] = changed_task_codes
            dump["changed_task_relations"] = changed_task_relations
            dump["task_enrichment_failures"] = [*code_failures, *relation_failures]
            if dump["task_enrichment_failures"]:
                print(f"changed task enrichment failures: {len(dump['task_enrichment_failures'])}", flush=True)
```

Do not yet import `changed_task_codes` or `changed_task_relations` into SQLite in this task unless existing importer already consumes those keys. Task 3 adds repair/import storage behavior.

- [ ] **Step 9: Run enrichment tests**

Run:

```bash
python3 -m pytest tests/test_sync_wedata.py::SyncWeDataTest::test_enrich_changed_task_definitions_adds_lineage_outputs_without_dropping_catalog tests/test_sync_wedata.py::SyncWeDataTest::test_sync_changed_task_codes_obeys_limit_and_returns_failures tests/test_sync_wedata.py::SyncWeDataTest::test_sync_changed_task_relations_fetches_upstream_and_downstream -q
```

Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add dlc_mcp/sync_wedata.py tests/test_sync_wedata.py
git commit -m "feat: enrich changed WeData tasks during sync

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: Bounded Repair Targets for Mapping and Run Gaps

**Files:**
- Modify: `dlc_mcp/sync_wedata.py`
- Test: `tests/test_sync_wedata.py`

**Interfaces:**
- Consumes: `AssetStore.get_table_tasks(table_name: str) -> dict`.
- Consumes: `_enrich_changed_task_definitions(...)`, `_sync_changed_task_codes(...)`, `_sync_changed_task_relations(...)` from Task 2.
- Produces: `_repair_task_targets_from_env(store: AssetStore) -> list[dict]` where each item has `TaskId` and `TaskName` keys.
- Produces: `_sync_repair_task_runs(client, project_id: str, repair_tasks: list[dict], page_size: int) -> tuple[dict, list[dict]]`.

- [ ] **Step 1: Write failing tests for repair target resolution**

Add this import name to `tests/test_sync_wedata.py`:

```python
    _repair_task_targets_from_env,
```

Add tests inside `class SyncWeDataTest(unittest.TestCase):`:

```python
    def test_repair_task_targets_reads_direct_task_ids_and_table_related_tasks(self):
        conn = sqlite3.connect(":memory:")
        store = AssetStore(conn)
        store.init_schema()
        store.upsert_table({"name": "ads_repair", "layer": "ads"})
        store.upsert_task({"id": "task_from_table", "name": "build_ads_repair", "outputs": ["ads_repair"]})
        with patch.dict(
            os.environ,
            {
                "WEDATA_REPAIR_TASK_IDS": "task_direct,task_extra",
                "WEDATA_REPAIR_TABLES": "ads_repair",
                "WEDATA_REPAIR_TASK_LIMIT": "10",
            },
            clear=False,
        ):
            targets = _repair_task_targets_from_env(store)

        self.assertEqual(
            sorted((item["TaskId"], item["TaskName"]) for item in targets),
            [("task_direct", ""), ("task_extra", ""), ("task_from_table", "build_ads_repair")],
        )

    def test_repair_task_targets_obeys_limit(self):
        conn = sqlite3.connect(":memory:")
        store = AssetStore(conn)
        store.init_schema()
        with patch.dict(os.environ, {"WEDATA_REPAIR_TASK_IDS": "task_1,task_2,task_3", "WEDATA_REPAIR_TASK_LIMIT": "2"}, clear=False):
            targets = _repair_task_targets_from_env(store)

        self.assertEqual([item["TaskId"] for item in targets], ["task_1", "task_2"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python3 -m pytest tests/test_sync_wedata.py::SyncWeDataTest::test_repair_task_targets_reads_direct_task_ids_and_table_related_tasks tests/test_sync_wedata.py::SyncWeDataTest::test_repair_task_targets_obeys_limit -q
```

Expected: FAIL because `_repair_task_targets_from_env` does not exist.

- [ ] **Step 3: Implement repair target resolver**

In `dlc_mcp/sync_wedata.py`, add this helper after `_task_identity()`:

```python
def _repair_task_targets_from_env(store):
    limit = int(os.environ.get("WEDATA_REPAIR_TASK_LIMIT", "200"))
    targets = []
    seen = set()

    def add_target(task_id, task_name=""):
        key = task_id or task_name
        if not key or key in seen:
            return
        seen.add(key)
        targets.append({"TaskId": task_id, "TaskName": task_name})

    for task_id in [part.strip() for part in os.environ.get("WEDATA_REPAIR_TASK_IDS", "").split(",") if part.strip()]:
        add_target(task_id, "")

    for table_name in [part.strip() for part in os.environ.get("WEDATA_REPAIR_TABLES", "").split(",") if part.strip()]:
        table_tasks = store.get_table_tasks(table_name).get("tasks") or []
        for task in table_tasks:
            add_target(str(task.get("id") or task.get("task_id") or ""), task.get("name") or task.get("task_name") or "")

    return targets[:limit]
```

- [ ] **Step 4: Run repair target tests**

Run:

```bash
python3 -m pytest tests/test_sync_wedata.py::SyncWeDataTest::test_repair_task_targets_reads_direct_task_ids_and_table_related_tasks tests/test_sync_wedata.py::SyncWeDataTest::test_repair_task_targets_obeys_limit -q
```

Expected: PASS.

- [ ] **Step 5: Write failing test for repair run sync**

Add this import name to `tests/test_sync_wedata.py`:

```python
    _sync_repair_task_runs,
```

Extend `FakeChangedTaskClient.call()` with this branch before the final return:

```python
        if action == "ListTaskInstances":
            return {
                "Response": {
                    "Data": {
                        "Items": [
                            {
                                "TaskId": payload.get("TaskId"),
                                "InstanceId": "inst_repair",
                                "InstanceDate": "2026-07-14",
                                "Status": "COMPLETED",
                            }
                        ],
                        "TotalPageNumber": 1,
                    }
                }
            }
```

Add this test inside `class SyncWeDataTest(unittest.TestCase):`:

```python
    def test_sync_repair_task_runs_fetches_runs_for_repair_tasks(self):
        client = FakeChangedTaskClient()
        with patch.dict(os.environ, {"WEDATA_INSTANCE_START": "2026-07-14 00:00:00", "WEDATA_INSTANCE_END": "2026-07-14 23:59:59"}, clear=False):
            runs, failures = _sync_repair_task_runs(client, "project", [{"TaskId": "task_1", "TaskName": "one"}], 100)

        self.assertEqual(failures, [])
        self.assertIn("task_1", runs)
        payloads = [payload for action, payload in client.calls if action == "ListTaskInstances"]
        self.assertEqual(payloads[0]["TaskId"], "task_1")
        self.assertEqual(payloads[0]["ScheduleTimeFrom"], "2026-07-14 00:00:00")
```

- [ ] **Step 6: Run repair run test to verify it fails**

Run:

```bash
python3 -m pytest tests/test_sync_wedata.py::SyncWeDataTest::test_sync_repair_task_runs_fetches_runs_for_repair_tasks -q
```

Expected: FAIL because `_sync_repair_task_runs` does not exist.

- [ ] **Step 7: Implement repair run sync**

In `dlc_mcp/sync_wedata.py`, add this helper after `_sync_changed_task_relations()`:

```python
def _sync_repair_task_runs(client, project_id, repair_tasks, page_size):
    responses = {}
    failures = []
    start_time, end_time = _instance_window()
    for item in repair_tasks:
        task_id, task_name = _task_identity(item)
        if not task_id:
            continue
        payload = {
            "ProjectId": project_id,
            "TaskId": task_id,
            "ScheduleTimeFrom": start_time,
            "ScheduleTimeTo": end_time,
            "TimeZone": os.environ.get("WEDATA_INSTANCE_TIMEZONE", "UTC+8"),
        }
        try:
            responses[task_id] = _list_all(client, "ListTaskInstances", payload, page_size)
        except Exception as exc:
            failures.append({"task_id": task_id, "task_name": task_name, "action": "ListTaskInstances", "error": str(exc)})
    return responses, failures
```

- [ ] **Step 8: Wire repair targets into `main()` after store initialization**

In `main()`, immediately after:

```python
    store = AssetStore(sqlite3.connect(db_path))
    store.init_schema()
```

add:

```python
    repair_tasks = _repair_task_targets_from_env(store)
    if repair_tasks:
        print(f"repairing {len(repair_tasks)} WeData task targets", flush=True)
        repair_definitions = _enrich_changed_task_definitions(client, project_id, repair_tasks, page_size)
        dump["tasks"] = _merge_task_responses(dump.get("tasks", {}), repair_definitions)
        repair_codes, repair_code_failures = _sync_changed_task_codes(client, project_id, repair_tasks)
        repair_relations, repair_relation_failures = _sync_changed_task_relations(client, project_id, repair_tasks, page_size)
        repair_runs, repair_run_failures = _sync_repair_task_runs(client, project_id, repair_tasks, page_size)
        dump["repair_task_codes"] = repair_codes
        dump["repair_task_relations"] = repair_relations
        dump["repair_task_runs"] = repair_runs
        dump["task_enrichment_failures"] = [
            *dump.get("task_enrichment_failures", []),
            *repair_code_failures,
            *repair_relation_failures,
            *repair_run_failures,
        ]
```

Keep the existing `import_wedata_snapshot(store, snapshot_from_api_dump(dump))` after this block so the updated dump is imported once.

- [ ] **Step 9: Run repair tests**

Run:

```bash
python3 -m pytest tests/test_sync_wedata.py::SyncWeDataTest::test_repair_task_targets_reads_direct_task_ids_and_table_related_tasks tests/test_sync_wedata.py::SyncWeDataTest::test_repair_task_targets_obeys_limit tests/test_sync_wedata.py::SyncWeDataTest::test_sync_repair_task_runs_fetches_runs_for_repair_tasks -q
```

Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add dlc_mcp/sync_wedata.py tests/test_sync_wedata.py
git commit -m "feat: add bounded WeData repair targets

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: MCP Query Metadata for Cache and Live Fallback

**Files:**
- Modify: `dlc_mcp/mcp.py:256-490`
- Test: `tests/test_mcp.py`

**Interfaces:**
- Consumes: existing `_format_markdown(tool_name: str, data: dict) -> str`.
- Produces: `_new_query_meta(snapshot=False) -> dict`.
- Produces: `_maybe_live_refresh(meta: dict, args: dict, data: dict, predicate: callable, refresh_fn: callable, reason: str) -> bool`.
- Produces: `_format_query_meta(meta: dict) -> str`.
- Produces: `_format_with_meta(tool_name: str, data: dict, meta: dict) -> str`.

- [ ] **Step 1: Write failing cache metadata test**

Add this test inside `class McpTest(unittest.TestCase):` in `tests/test_mcp.py` after `test_get_task_code_returns_cached_sql`:

```python
    def test_get_task_code_cache_hit_includes_query_metadata(self):
        self.store.upsert_task_code(
            "project",
            "task_001",
            "build_dim_customer",
            "c2VsZWN0IDE7",
            "select 1;",
            9,
            "base64",
            {"CodeInfo": "c2VsZWN0IDE7", "CodeFileSize": 9},
        )

        response = handle_request(
            self.store,
            {"jsonrpc": "2.0", "id": 141, "method": "tools/call", "params": {"name": "get_task_code", "arguments": {"task_id": "task_001"}}},
        )
        text = response["result"]["content"][0]["text"]

        self.assertIn("查询元信息", text)
        self.assertIn("数据来源：cache", text)
        self.assertIn("实时刷新：否", text)
```

- [ ] **Step 2: Run cache metadata test to verify it fails**

Run:

```bash
python3 -m pytest tests/test_mcp.py::McpTest::test_get_task_code_cache_hit_includes_query_metadata -q
```

Expected: FAIL because query metadata is not rendered.

- [ ] **Step 3: Add metadata helper functions**

In `dlc_mcp/mcp.py`, add these helpers after `_table_detail_incomplete()`:

```python
def _new_query_meta(snapshot=False):
    return {
        "source": "cache_snapshot" if snapshot else "cache",
        "live_attempted": False,
        "live_reason": "",
        "live_error": "",
    }


def _maybe_live_refresh(meta, args, data, predicate, refresh_fn, reason=""):
    if not args.get("live") and not predicate(data):
        return False
    if reason:
        live_reason = reason
    elif args.get("live"):
        live_reason = "user_requested"
    else:
        live_reason = "cache_miss"
    meta["live_attempted"] = True
    meta["live_reason"] = live_reason
    had_cache = not _has_error(data)
    try:
        refresh_fn()
        meta["source"] = "cache_after_live_refresh"
        return True
    except Exception as exc:
        meta["live_error"] = str(exc)
        meta["source"] = "live_refresh_failed_cache" if had_cache else "live_refresh_failed_no_cache"
        return False


def _format_query_meta(meta):
    if meta.get("live_error"):
        live_status = "失败"
    else:
        live_status = "是" if meta.get("live_attempted") else "否"
    lines = [
        "**查询元信息**",
        "",
        f"- 数据来源：{_cell(meta.get('source'))}",
        f"- 实时刷新：{live_status}",
    ]
    if meta.get("live_reason"):
        lines.append(f"- 触发原因：{_cell(meta.get('live_reason'))}")
    if meta.get("live_error"):
        lines.append(f"- 失败原因：{_cell(meta.get('live_error'))}")
    return "\n".join(lines)


def _format_with_meta(tool_name, data, meta):
    return _format_query_meta(meta) + "\n\n" + _format_markdown(tool_name, data)
```

- [ ] **Step 4: Initialize meta in `_call_tool()` and wrap output**

At the start of `_call_tool()` after `args = params.get("arguments") or {}`, add:

```python
    snapshot_tools = {"get_sync_health", "get_asset_coverage", "get_asset_governance_issue_inventory", "get_asset_governance_daily_report"}
    meta = _new_query_meta(snapshot=name in snapshot_tools)
```

Replace the final return line:

```python
    return _result(request, {"content": [{"type": "text", "text": _format_markdown(name, data)}]})
```

with:

```python
    return _result(request, {"content": [{"type": "text", "text": _format_with_meta(name, data, meta)}]})
```

- [ ] **Step 5: Run cache metadata test**

Run:

```bash
python3 -m pytest tests/test_mcp.py::McpTest::test_get_task_code_cache_hit_includes_query_metadata -q
```

Expected: PASS.

- [ ] **Step 6: Write failing live success and live failure metadata tests**

Add this fake live class near `FakeWeDataClient` in `tests/test_mcp.py`:

```python
class FailingLive:
    def sync_task_code(self, **kwargs):
        raise RuntimeError("live unavailable")
```

Add these tests inside `class McpTest(unittest.TestCase):`:

```python
    def test_get_task_code_live_success_includes_refresh_metadata(self):
        client = FakeWeDataClient()
        with patch.dict(os.environ, {"WEDATA_PROJECT_ID": "project"}, clear=False):
            live = LiveWeData(self.store, client=client)
            response = handle_request(
                self.store,
                {"jsonrpc": "2.0", "id": 142, "method": "tools/call", "params": {"name": "get_task_code", "arguments": {"task_id": "task_001", "live": True}}},
                live=live,
            )

        text = response["result"]["content"][0]["text"]
        self.assertIn("数据来源：cache_after_live_refresh", text)
        self.assertIn("实时刷新：是", text)
        self.assertIn("触发原因：user_requested", text)
        self.assertIn("select * from dim_customer;", text)

    def test_get_task_code_live_failure_keeps_cached_data_and_reports_error(self):
        self.store.upsert_task_code(
            "project",
            "task_001",
            "build_dim_customer",
            "c2VsZWN0IDE7",
            "select 1;",
            9,
            "base64",
            {"CodeInfo": "c2VsZWN0IDE7", "CodeFileSize": 9},
        )
        with patch.dict(os.environ, {"WEDATA_PROJECT_ID": "project"}, clear=False):
            response = handle_request(
                self.store,
                {"jsonrpc": "2.0", "id": 143, "method": "tools/call", "params": {"name": "get_task_code", "arguments": {"task_id": "task_001", "live": True}}},
                live=FailingLive(),
            )

        text = response["result"]["content"][0]["text"]
        self.assertIn("数据来源：live_refresh_failed_cache", text)
        self.assertIn("实时刷新：失败", text)
        self.assertIn("失败原因：live unavailable", text)
        self.assertIn("select 1;", text)

    def test_daily_report_uses_snapshot_metadata_without_live_refresh(self):
        response = handle_request(
            self.store,
            {"jsonrpc": "2.0", "id": 144, "method": "tools/call", "params": {"name": "get_asset_governance_daily_report", "arguments": {}}},
            live=FailingLive(),
        )

        text = response["result"]["content"][0]["text"]
        self.assertIn("数据来源：cache_snapshot", text)
        self.assertIn("实时刷新：否", text)
```

- [ ] **Step 7: Run live metadata tests to verify they fail**

Run:

```bash
python3 -m pytest tests/test_mcp.py::McpTest::test_get_task_code_live_success_includes_refresh_metadata tests/test_mcp.py::McpTest::test_get_task_code_live_failure_keeps_cached_data_and_reports_error tests/test_mcp.py::McpTest::test_daily_report_uses_snapshot_metadata_without_live_refresh -q
```

Expected: FAIL because the existing branches do not call `_maybe_live_refresh()`.

- [ ] **Step 8: Convert the `get_task_code` branch to `_maybe_live_refresh()`**

In `dlc_mcp/mcp.py`, replace the `get_task_code` live block with:

```python
    elif name == "get_task_code":
        if not args.get("task_id") and not args.get("task_name"):
            data = _error_data("missing_task_identity")
        else:
            project_id = os.environ.get("WEDATA_PROJECT_ID", "")
            data = store.get_task_code(project_id, args.get("task_id", ""), args.get("task_name", ""))
            if live:
                refreshed = _maybe_live_refresh(
                    meta,
                    args,
                    data,
                    lambda item: item.get("error") in {"task_code_not_found", "task_not_found"},
                    lambda: live.sync_task_code(task_id=args.get("task_id", ""), task_name=args.get("task_name", ""), project_id=project_id),
                )
                if refreshed:
                    data = store.get_task_code(project_id, args.get("task_id", ""), args.get("task_name", ""))
```

- [ ] **Step 9: Convert key high-trust branches to `_maybe_live_refresh()`**

Update these branches using the same pattern; keep each branch's existing post-refresh store query unchanged:

```python
# search_tasks
refreshed = _maybe_live_refresh(meta, args, data, _empty_list("results"), lambda: live.sync_tasks(args["query"]))

# get_table_profile
refreshed = _maybe_live_refresh(meta, args, data, lambda item: _has_error(item) or not item.get("columns"), lambda: live.sync_table(args["table_name"]), reason="incomplete" if not data.get("columns") else "")

# list_table_columns
refreshed = _maybe_live_refresh(meta, args, data, _empty_list("columns"), lambda: live.sync_table(args["table_name"]))

# get_quality_status
refreshed = _maybe_live_refresh(meta, args, data, lambda item: _has_error(item) or not item.get("has_quality_monitoring"), lambda: live.sync_table(args["table_name"]), reason="incomplete" if not data.get("has_quality_monitoring") else "")

# get_table_lineage
refreshed = _maybe_live_refresh(meta, args, data, lambda item: not item.get("downstream"), lambda: live.sync_table(args["table_name"]), reason="incomplete" if not data.get("downstream") else "")

# get_table_tasks
refreshed = _maybe_live_refresh(meta, args, data, _empty_list("tasks"), lambda: live.sync_table(args["table_name"]))

# get_table_production_status
refreshed = _maybe_live_refresh(meta, args, data, lambda item: _has_error(item) or item.get("status") in {"not_run", "unknown"}, lambda: live.sync_table(args["table_name"]), reason=data.get("status", ""))

# get_table_production_risk_detail
refreshed = _maybe_live_refresh(meta, args, data, lambda item: _has_error(item) or item.get("status") in {"not_run", "unknown"}, lambda: live.sync_table(args["table_name"]), reason=data.get("status", ""))

# get_data_source
refreshed = _maybe_live_refresh(meta, args, data, _has_error, lambda: live.sync_data_sources(args["data_source_id"]))

# list_data_source_tasks
refreshed = _maybe_live_refresh(meta, args, data, _empty_list("tasks"), lambda: live.sync_data_sources(args["data_source_id"]))
```

For `get_task_runs`, preserve the task-name/task-id split and use:

```python
refreshed = _maybe_live_refresh(meta, args, data, _empty_list("runs"), lambda: live.sync_task_runs(task_name=args["task_name"], instance_date=args.get("instance_date", "")))
```

or:

```python
refreshed = _maybe_live_refresh(meta, args, data, _empty_list("runs"), lambda: live.sync_task_runs(task_id=args["task_id"], instance_date=args.get("instance_date", "")))
```

For `get_table`, preserve the GUID logic and wrap the `live.sync_table_detail(...)` call with `_maybe_live_refresh()`.

- [ ] **Step 10: Run MCP metadata tests**

Run:

```bash
python3 -m pytest tests/test_mcp.py::McpTest::test_get_task_code_cache_hit_includes_query_metadata tests/test_mcp.py::McpTest::test_get_task_code_live_success_includes_refresh_metadata tests/test_mcp.py::McpTest::test_get_task_code_live_failure_keeps_cached_data_and_reports_error tests/test_mcp.py::McpTest::test_daily_report_uses_snapshot_metadata_without_live_refresh -q
```

Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add dlc_mcp/mcp.py tests/test_mcp.py
git commit -m "feat: show MCP query freshness metadata

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: Daily Governance Execution Summary

**Files:**
- Modify: `dlc_mcp/assets.py`
- Modify: `dlc_mcp/mcp.py`
- Test: `tests/test_assets.py`
- Test: `tests/test_mcp.py`

**Interfaces:**
- Consumes: `AssetStore.get_asset_governance_daily_report(instance_date='', layer='', core_level='') -> dict` existing fields.
- Produces: report key `execution_summary: dict[str, list[dict]]` with keys `p0`, `p1`, `p2`.
- Produces: report key `responsibility_buckets: dict[str, list[dict]]` with keys `data_platform`, `warehouse_owner`, `bi_owner`, `business_owner`, `unknown_owner`.
- Produces: report key `acceptance_criteria: list[str]`.
- Produces: Markdown sections `治理执行摘要`, `按责任方拆解`, and `验收标准`.

- [ ] **Step 1: Write failing structured report test**

Add this test inside `class AssetStoreTest(unittest.TestCase):` in `tests/test_assets.py`:

```python
    def test_daily_report_includes_execution_summary_buckets_and_acceptance_criteria(self):
        store = make_store()
        store.upsert_table({"name": "ads_not_run", "layer": "ads", "owner": ""})
        store.upsert_task({"id": "task_not_run", "name": "build_ads_not_run", "outputs": ["ads_not_run"]})
        store.upsert_table({"name": "dwd_quality_gap", "layer": "dwd", "owner": "tencent"})
        for index in range(3):
            store.upsert_lineage("dwd_quality_gap", f"downstream_{index}", "lineage")

        report = store.get_asset_governance_daily_report(instance_date="2026-07-14")

        self.assertIn("execution_summary", report)
        self.assertIn("p0", report["execution_summary"])
        self.assertIn("p1", report["execution_summary"])
        self.assertIn("p2", report["execution_summary"])
        self.assertIn("responsibility_buckets", report)
        self.assertIn("data_platform", report["responsibility_buckets"])
        self.assertIn("warehouse_owner", report["responsibility_buckets"])
        self.assertIn("unknown_owner", report["responsibility_buckets"])
        self.assertIn("acceptance_criteria", report)
        self.assertTrue(any("任务映射覆盖率" in item for item in report["acceptance_criteria"]))
        flattened = report["execution_summary"]["p0"] + report["execution_summary"]["p1"] + report["execution_summary"]["p2"]
        self.assertTrue(flattened)
        self.assertTrue(all("action" in item for item in flattened))
```

- [ ] **Step 2: Run structured report test to verify it fails**

Run:

```bash
python3 -m pytest tests/test_assets.py::AssetStoreTest::test_daily_report_includes_execution_summary_buckets_and_acceptance_criteria -q
```

Expected: FAIL because the report keys are not present.

- [ ] **Step 3: Implement execution summary helpers**

In `dlc_mcp/assets.py`, add these module-level helpers near existing governance report helper functions:

```python
def _daily_execution_summary(manual_review_top_items, production_risks, quality_gaps):
    summary = {"p0": [], "p1": [], "p2": []}
    for item in manual_review_top_items[:10]:
        severity = str(item.get("severity") or "P1").lower()
        if severity not in summary:
            severity = "p1"
        summary[severity].append(
            {
                "name": item.get("name", ""),
                "issue": item.get("issue_label") or item.get("issue_type", ""),
                "owner_bucket": item.get("owner_bucket", "unknown_owner"),
                "action": item.get("daily_action") or item.get("recommended_next_check", ""),
                "evidence": {
                    "downstream_count": item.get("downstream_count", 0),
                    "task_count": item.get("task_count", 0),
                    "producer_task_count": item.get("producer_task_count", 0),
                    "run_count": item.get("run_count", 0),
                },
            }
        )
    for risk in production_risks[:5]:
        bucket = "p0" if risk.get("status") in {"failed", "not_run"} else "p1"
        summary[bucket].append(
            {
                "name": risk.get("name", ""),
                "issue": "产出风险",
                "owner_bucket": "data_platform" if risk.get("producer_task_count", 0) else "unknown_owner",
                "action": "确认昨日产出任务实例、调度状态和任务负责人。",
                "evidence": {
                    "status": risk.get("status_label") or risk.get("status", ""),
                    "producer_task_count": risk.get("producer_task_count", 0),
                },
            }
        )
    if not summary["p0"] and quality_gaps:
        first_quality = quality_gaps[0]
        summary["p1"].append(
            {
                "name": first_quality.get("name", ""),
                "issue": "质量规则缺口",
                "owner_bucket": "warehouse_owner",
                "action": "确认源质量规则是否应补齐；不要把规则稀疏直接判定为同步失败。",
                "evidence": {
                    "downstream_count": first_quality.get("downstream_count", 0),
                    "quality_rule_count": first_quality.get("quality_rule_count", 0),
                },
            }
        )
    return summary


def _daily_responsibility_buckets(execution_summary):
    buckets = {"data_platform": [], "warehouse_owner": [], "bi_owner": [], "business_owner": [], "unknown_owner": []}
    for items in execution_summary.values():
        for item in items:
            bucket = item.get("owner_bucket") or "unknown_owner"
            if bucket not in buckets:
                bucket = "unknown_owner"
            buckets[bucket].append(item)
    return buckets


def _daily_acceptance_criteria():
    return [
        "任务映射覆盖率较上次巡检提升，missing_task_mapping P0/P1 数量下降。",
        "运行实例关联覆盖率较上次巡检提升，missing_task_runs P0/P1 数量下降。",
        "昨日分区和昨日运行实例可通过 MCP 查询到，并显示查询元信息。",
        "P0 产出风险均有任务负责人、实例状态或明确的待补拉原因。",
        "质量规则缺口继续展示，但不被误判为同步失败。",
    ]
```

- [ ] **Step 4: Add fields to `get_asset_governance_daily_report()`**

In `AssetStore.get_asset_governance_daily_report()`, after existing `manual_review_sections` and `manual_review_top_items` are computed, add:

```python
        execution_summary = _daily_execution_summary(manual_review_top_items, production_risks, quality_gaps)
        responsibility_buckets = _daily_responsibility_buckets(execution_summary)
        acceptance_criteria = _daily_acceptance_criteria()
```

In the returned dictionary, add:

```python
            "execution_summary": execution_summary,
            "responsibility_buckets": responsibility_buckets,
            "acceptance_criteria": acceptance_criteria,
```

Do not remove any existing keys from the returned dictionary.

- [ ] **Step 5: Run structured report test**

Run:

```bash
python3 -m pytest tests/test_assets.py::AssetStoreTest::test_daily_report_includes_execution_summary_buckets_and_acceptance_criteria -q
```

Expected: PASS.

- [ ] **Step 6: Write failing MCP Markdown test**

Add this test inside `class McpTest(unittest.TestCase):` in `tests/test_mcp.py`:

```python
    def test_daily_report_markdown_renders_execution_sections(self):
        response = handle_request(
            self.store,
            {"jsonrpc": "2.0", "id": 145, "method": "tools/call", "params": {"name": "get_asset_governance_daily_report", "arguments": {}}},
        )
        text = response["result"]["content"][0]["text"]

        self.assertIn("治理执行摘要", text)
        self.assertIn("按责任方拆解", text)
        self.assertIn("验收标准", text)
```

- [ ] **Step 7: Run Markdown test to verify it fails**

Run:

```bash
python3 -m pytest tests/test_mcp.py::McpTest::test_daily_report_markdown_renders_execution_sections -q
```

Expected: FAIL because the Markdown formatter does not render the new sections.

- [ ] **Step 8: Add daily execution Markdown helpers**

In `dlc_mcp/mcp.py`, add these helpers near other formatter helpers:

```python
def _format_daily_execution_summary(data):
    summary = data.get("execution_summary") or {}
    rows = []
    for severity in ("p0", "p1", "p2"):
        for item in summary.get(severity, []):
            rows.append([severity.upper(), item.get("name"), item.get("issue"), item.get("owner_bucket"), item.get("action")])
    return _section("治理执行摘要", ["按 P0/P1/P2 汇总今日优先治理动作。"] ) + "\n\n" + _table(
        ["级别", "资产", "问题", "责任桶", "动作"],
        rows,
    )


def _format_daily_responsibility_buckets(data):
    buckets = data.get("responsibility_buckets") or {}
    rows = [[bucket, len(items), "、".join(item.get("name", "") for item in items[:5])] for bucket, items in buckets.items()]
    return _section("按责任方拆解", ["只基于确定性证据分桶；Owner 不足时进入 unknown_owner。"] ) + "\n\n" + _table(
        ["责任桶", "数量", "示例资产"],
        rows,
    )


def _format_daily_acceptance_criteria(data):
    return _section("验收标准", data.get("acceptance_criteria") or [])
```

In the `get_asset_governance_daily_report` Markdown branch, insert these helpers before existing issue tables:

```python
                _format_daily_execution_summary(data),
                _format_daily_responsibility_buckets(data),
                _format_daily_acceptance_criteria(data),
```

- [ ] **Step 9: Run report tests**

Run:

```bash
python3 -m pytest tests/test_assets.py::AssetStoreTest::test_daily_report_includes_execution_summary_buckets_and_acceptance_criteria tests/test_mcp.py::McpTest::test_daily_report_markdown_renders_execution_sections -q
```

Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add dlc_mcp/assets.py dlc_mcp/mcp.py tests/test_assets.py tests/test_mcp.py
git commit -m "feat: add governance execution summary

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: Regression, Smoke Checks, and Final Review

**Files:**
- Modify only if tests expose defects:
  - `deploy/sync-wedata-incremental.sh`
  - `dlc_mcp/sync_wedata.py`
  - `dlc_mcp/mcp.py`
  - `dlc_mcp/assets.py`
  - tests touched in earlier tasks

**Interfaces:**
- Consumes: all functions and fields produced by Tasks 1-5.
- Produces: passing targeted test suite and final working tree summary.

- [ ] **Step 1: Run sync tests**

Run:

```bash
python3 -m pytest tests/test_sync_wedata.py -q
```

Expected: PASS. If a test fails, fix only the failing behavior in `dlc_mcp/sync_wedata.py` or `tests/test_sync_wedata.py`, then rerun the same command.

- [ ] **Step 2: Run MCP tests**

Run:

```bash
python3 -m pytest tests/test_mcp.py -q
```

Expected: PASS. If a test fails, fix only the failing behavior in `dlc_mcp/mcp.py` or `tests/test_mcp.py`, then rerun the same command.

- [ ] **Step 3: Run asset tests**

Run:

```bash
python3 -m pytest tests/test_assets.py -q
```

Expected: PASS. If a test fails, fix only the failing behavior in `dlc_mcp/assets.py` or `tests/test_assets.py`, then rerun the same command.

- [ ] **Step 4: Run targeted combined tests**

Run:

```bash
python3 -m pytest tests/test_sync_wedata.py tests/test_mcp.py tests/test_assets.py -q
```

Expected: PASS.

- [ ] **Step 5: Run full test suite**

Run:

```bash
python3 -m pytest -q
```

Expected: PASS. If unrelated pre-existing failures appear, capture the failing test names and output in the final report instead of hiding them.

- [ ] **Step 6: Run shell syntax checks**

Run:

```bash
bash -n deploy/sync-wedata-incremental.sh
bash -n deploy/sync-wedata-full.sh
```

Expected: both commands exit with status 0 and no output.

- [ ] **Step 7: Inspect git diff**

Run:

```bash
git diff --stat
git diff -- deploy/sync-wedata-incremental.sh dlc_mcp/sync_wedata.py dlc_mcp/mcp.py dlc_mcp/assets.py
```

Expected: diff contains only the planned changes: sync defaults/enrichment/repair, MCP metadata, and daily report execution fields.

- [ ] **Step 8: Commit final fixes if any**

If Step 1-7 required extra fixes after the task commits, commit them:

```bash
git add deploy/sync-wedata-incremental.sh dlc_mcp/sync_wedata.py dlc_mcp/mcp.py dlc_mcp/assets.py tests/test_sync_wedata.py tests/test_mcp.py tests/test_assets.py
git commit -m "fix: stabilize DLC WeData technical closure

Co-Authored-By: Claude <noreply@anthropic.com>"
```

If no extra fixes were needed, skip this commit.

- [ ] **Step 9: Final status report**

Run:

```bash
git status --short
git log --oneline -5
```

Expected: only unrelated pre-existing untracked files remain. The final user-facing report must include:

```text
Implemented:
- Daily table increment defaults to structure_update,update,create.
- Changed-task filtering and bounded enrichment.
- Repair entry points for task mapping/run gaps.
- MCP query metadata for cache/live status.
- Daily governance execution summary, responsibility buckets, and acceptance criteria.

Verification:
- tests/test_sync_wedata.py: PASS
- tests/test_mcp.py: PASS
- tests/test_assets.py: PASS
- full pytest: PASS or listed failures
- bash syntax checks: PASS
```

---

## Self-Review

Spec coverage:

- Daily table increment defaults: Task 1.
- Task change-time enrichment: Task 2.
- Refresh changed task relations/code/input-output mapping: Task 2.
- Bounded repair entry points: Task 3.
- MCP query metadata: Task 4.
- Daily execution report fields and Markdown: Task 5.
- Regression and smoke checks: Task 6.

Placeholder scan:

- No placeholder sections remain.
- All steps include concrete files, commands, code, and expected results.

Type consistency:

- `_filter_changed_tasks()` returns `list[dict]` and feeds `_enrich_changed_task_definitions()`, `_sync_changed_task_codes()`, and `_sync_changed_task_relations()`.
- `_repair_task_targets_from_env()` returns items with `TaskId`/`TaskName`, compatible with `_task_identity()`.
- MCP metadata helpers return dictionaries consumed by `_format_with_meta()`.
- Daily report keys match Markdown formatter inputs.
