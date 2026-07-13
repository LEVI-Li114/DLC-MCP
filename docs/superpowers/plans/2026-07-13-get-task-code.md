# get_task_code MCP Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a cached `get_task_code(task_id, task_name, live)` MCP tool that returns decoded Tencent Cloud WeData task SQL/code content.

**Architecture:** Add an independent `task_codes` SQLite cache in `AssetStore`, a `LiveWeData.sync_task_code()` refresher that calls Tencent Cloud `GetTaskCode`, and an MCP tool branch/formatter in `dlc_mcp/mcp.py`. The tool reads cache first and refreshes from WeData when `live=true` or when cached code is missing.

**Tech Stack:** Python 3, SQLite via `sqlite3`, existing JSON-RPC MCP handler, Tencent Cloud TC3 client, `unittest`/`pytest` test suite.

## Global Constraints

- Tencent Cloud action must be `GetTaskCode`.
- Tencent Cloud API version remains configured by existing `TencentCloudClient.wedata_from_env()` default `2025-08-06`.
- `GetTaskCode` live calls must send `ProjectId` and `TaskId`.
- Tool input schema contains optional `task_id`, optional `task_name`, and optional `live`.
- If both `task_id` and `task_name` are missing, return `missing_task_identity`.
- If only `task_name` is provided, use exact cached task-name matching; live mode may sync `ListTasks` by task name before retrying.
- Decode Base64 `CodeInfo` as UTF-8 when possible; if decoding fails, return raw `CodeInfo` with `encoding='raw'`.
- Do not implement task-code editing, publishing, version history, fuzzy task name matching, or production cron changes.

---

## File Structure

- Modify `dlc_mcp/assets.py`
  - Add `task_codes` schema.
  - Add cache read/write methods and exact task resolution.
  - Add code decoding helper functions near other module-level helpers.
  - Add `GetTaskCode` to the cloud API catalog.
- Modify `dlc_mcp/live.py`
  - Add `sync_task_code()` to resolve task identity, call `GetTaskCode`, decode code, and cache it.
- Modify `dlc_mcp/mcp.py`
  - Register `get_task_code` in `TOOLS`.
  - Add `_call_tool` branch and Markdown formatter.
  - Add code-fence language helper.
- Modify `tests/test_mcp.py`
  - Extend `FakeWeDataClient` with `GetTaskCode` response.
  - Add MCP cache, validation, live-refresh, name-resolution, and tool-list tests.
- Create or modify `tests/test_assets.py`
  - Add focused tests for Base64 decode and raw fallback if not already covered in `test_mcp.py`.

---

### Task 1: Add Task Code Cache to AssetStore

**Files:**
- Modify: `dlc_mcp/assets.py:19-80`
- Modify: `dlc_mcp/assets.py:89-273`
- Modify: `dlc_mcp/assets.py:631-688`
- Test: `tests/test_assets.py`

**Interfaces:**
- Consumes: existing `AssetStore.init_schema()`, `AssetStore.upsert_task()`, `_one()`, `_all()`.
- Produces:
  - `decode_task_code_info(code_info: str) -> tuple[str, str]`
  - `AssetStore.resolve_task(task_id: str = '', task_name: str = '') -> dict | None`
  - `AssetStore.upsert_task_code(project_id: str, task_id: str, task_name: str = '', code_info: str = '', code_text: str = '', code_file_size: int = 0, encoding: str = '', raw: dict | None = None) -> None`
  - `AssetStore.get_task_code(project_id: str = '', task_id: str = '', task_name: str = '') -> dict`

- [ ] **Step 1: Write failing decode/cache tests**

Add these tests to `tests/test_assets.py`:

```python
import sqlite3

from dlc_mcp.assets import AssetStore, decode_task_code_info


def test_decode_task_code_info_base64_and_raw_fallback():
    code_text, encoding = decode_task_code_info("c2VsZWN0IDE7")
    assert code_text == "select 1;"
    assert encoding == "base64"

    raw_text, raw_encoding = decode_task_code_info("select * from dim_customer")
    assert raw_text == "select * from dim_customer"
    assert raw_encoding == "raw"


def test_task_code_cache_resolves_by_id_and_name():
    conn = sqlite3.connect(":memory:")
    store = AssetStore(conn)
    store.init_schema()
    store.upsert_task({"id": "task_001", "name": "build_dim_customer"})
    store.upsert_task_code(
        "project",
        "task_001",
        "build_dim_customer",
        "c2VsZWN0IDE7",
        "select 1;",
        9,
        "base64",
        {"CodeInfo": "c2VsZWN0IDE7", "CodeFileSize": 9},
    )

    by_id = store.get_task_code(project_id="project", task_id="task_001")
    by_name = store.get_task_code(project_id="project", task_name="build_dim_customer")

    assert by_id["task_id"] == "task_001"
    assert by_id["task_name"] == "build_dim_customer"
    assert by_id["code_text"] == "select 1;"
    assert by_id["encoding"] == "base64"
    assert by_name["task_id"] == "task_001"
    assert by_name["code_text"] == "select 1;"


def test_task_code_cache_reports_missing_identity_and_missing_code():
    conn = sqlite3.connect(":memory:")
    store = AssetStore(conn)
    store.init_schema()
    store.upsert_task({"id": "task_001", "name": "build_dim_customer"})

    missing_identity = store.get_task_code(project_id="project")
    missing_code = store.get_task_code(project_id="project", task_id="task_001")
    missing_task = store.get_task_code(project_id="project", task_name="unknown_task")

    assert missing_identity["error"] == "missing_task_identity"
    assert missing_code["error"] == "task_code_not_found"
    assert missing_task["error"] == "task_not_found"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_assets.py::test_decode_task_code_info_base64_and_raw_fallback tests/test_assets.py::test_task_code_cache_resolves_by_id_and_name tests/test_assets.py::test_task_code_cache_reports_missing_identity_and_missing_code -v
```

Expected: FAIL with import/attribute errors for `decode_task_code_info`, `upsert_task_code`, or `get_task_code`.

- [ ] **Step 3: Add `GetTaskCode` to the API catalog**

In `dlc_mcp/assets.py`, add this object to `TENCENT_CLOUD_API_CATALOG` after the `GetTable` entry:

```python
    {
        "service": "wedata",
        "action": "GetTaskCode",
        "provider": "Tencent Cloud",
        "product": "WeData",
        "doc_category": "数据开发相关接口",
        "source_url": "https://cloud.tencent.com/document/api/1267/123630",
        "description": "获取任务代码。",
        "usage": "按任务 ID 拉取 SQL/code 内容，支撑任务逻辑审查和血缘缺口排查。",
    },
```

- [ ] **Step 4: Add the `task_codes` schema**

In `AssetStore.init_schema()` SQL block, after `task_runs`, add:

```sql
            create table if not exists task_codes (
                project_id text not null,
                task_id text not null,
                task_name text not null default '',
                code_info text not null default '',
                code_text text not null default '',
                code_file_size integer not null default 0,
                encoding text not null default '',
                raw_json text not null default '{}',
                updated_at text not null default '',
                primary key (project_id, task_id)
            );
```

- [ ] **Step 5: Add task resolution and cache methods**

In `AssetStore`, after `upsert_task()`, add:

```python
    def resolve_task(self, task_id="", task_name=""):
        if task_id:
            row = self._one("select id, name, task_type, cycle, schedule_time, schedule_desc, owner, status from tasks where id = ?", (task_id,))
            if row:
                return dict(row)
            return {"id": task_id, "name": task_name or "", "task_type": "", "cycle": "", "schedule_time": "", "schedule_desc": "", "owner": "", "status": ""}
        if not task_name:
            return None
        row = self._one(
            "select id, name, task_type, cycle, schedule_time, schedule_desc, owner, status from tasks where name = ? order by id limit 1",
            (task_name,),
        )
        return dict(row) if row else None

    def upsert_task_code(self, project_id, task_id, task_name="", code_info="", code_text="", code_file_size=0, encoding="", raw=None):
        self.conn.execute(
            """
            insert into task_codes
                (project_id, task_id, task_name, code_info, code_text, code_file_size, encoding, raw_json, updated_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            on conflict(project_id, task_id) do update set
                task_name = excluded.task_name,
                code_info = excluded.code_info,
                code_text = excluded.code_text,
                code_file_size = excluded.code_file_size,
                encoding = excluded.encoding,
                raw_json = excluded.raw_json,
                updated_at = excluded.updated_at
            """,
            (
                project_id,
                task_id,
                task_name,
                code_info,
                code_text,
                int(code_file_size or 0),
                encoding,
                json.dumps(raw or {}, ensure_ascii=False, sort_keys=True),
            ),
        )
        self.conn.commit()

    def get_task_code(self, project_id="", task_id="", task_name=""):
        if not task_id and not task_name:
            return {"error": "missing_task_identity"}
        task = self.resolve_task(task_id, task_name)
        if not task:
            return {"error": "task_not_found", "task_id": task_id, "task_name": task_name}
        resolved_task_id = task["id"]
        row = self._one(
            """
            select project_id, task_id, task_name, code_info, code_text, code_file_size, encoding, raw_json, updated_at
            from task_codes
            where (? = '' or project_id = ?) and task_id = ?
            order by updated_at desc
            limit 1
            """,
            (project_id, project_id, resolved_task_id),
        )
        if not row:
            return {"error": "task_code_not_found", "project_id": project_id, "task_id": resolved_task_id, "task_name": task.get("name") or task_name}
        data = dict(row)
        data["task_name"] = data.get("task_name") or task.get("name", "")
        data["raw"] = _json_dict(data.pop("raw_json", "{}"))
        return data
```

- [ ] **Step 6: Add the decoder helper**

Near other module-level helpers in `dlc_mcp/assets.py`, add:

```python
def decode_task_code_info(code_info):
    text = code_info or ""
    if not text:
        return "", "raw"
    try:
        import base64

        decoded = base64.b64decode(text, validate=True)
        return decoded.decode("utf-8"), "base64"
    except Exception:
        return text, "raw"
```

- [ ] **Step 7: Run focused tests**

Run:

```bash
pytest tests/test_assets.py::test_decode_task_code_info_base64_and_raw_fallback tests/test_assets.py::test_task_code_cache_resolves_by_id_and_name tests/test_assets.py::test_task_code_cache_reports_missing_identity_and_missing_code -v
```

Expected: PASS.

- [ ] **Step 8: Commit Task 1**

```bash
git add dlc_mcp/assets.py tests/test_assets.py
git commit -m "Add WeData task code cache

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: Add LiveWeData GetTaskCode Refresh

**Files:**
- Modify: `dlc_mcp/live.py:1-124`
- Test: `tests/test_mcp.py`

**Interfaces:**
- Consumes:
  - `AssetStore.resolve_task(task_id='', task_name='') -> dict | None`
  - `AssetStore.upsert_task_code(...) -> None`
  - `decode_task_code_info(code_info: str) -> tuple[str, str]`
- Produces:
  - `LiveWeData.sync_task_code(task_id: str = '', task_name: str = '', project_id: str = '') -> None`

- [ ] **Step 1: Write failing live sync test**

In `tests/test_mcp.py`, add `import base64` at the top if needed. Extend `FakeWeDataClient.call()` before its default return:

```python
        if action == "GetTaskCode":
            return {
                "Response": {
                    "Data": {
                        "CodeInfo": "c2VsZWN0ICogZnJvbSBkaW1fY3VzdG9tZXI7",
                        "CodeFileSize": 27,
                    },
                    "RequestId": "req-task-code",
                }
            }
```

Then add this test method to `McpTest`:

```python
    def test_live_wedata_syncs_task_code(self):
        client = FakeWeDataClient()
        with patch.dict(os.environ, {"WEDATA_PROJECT_ID": "project"}, clear=False):
            live = LiveWeData(self.store, client=client)
            live.sync_task_code(task_id="task_001")

        actions = [action for action, payload in client.calls]
        get_task_code_payloads = [payload for action, payload in client.calls if action == "GetTaskCode"]
        cached = self.store.get_task_code(project_id="project", task_id="task_001")

        self.assertIn("GetTaskCode", actions)
        self.assertEqual(get_task_code_payloads[0]["ProjectId"], "project")
        self.assertEqual(get_task_code_payloads[0]["TaskId"], "task_001")
        self.assertEqual(cached["code_text"], "select * from dim_customer;")
        self.assertEqual(cached["encoding"], "base64")
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/test_mcp.py::McpTest::test_live_wedata_syncs_task_code -v
```

Expected: FAIL with `AttributeError: 'LiveWeData' object has no attribute 'sync_task_code'`.

- [ ] **Step 3: Import decoder in live.py**

Change imports at the top of `dlc_mcp/live.py` from:

```python
from .assets import AssetStore
```

to:

```python
from .assets import AssetStore, decode_task_code_info
```

- [ ] **Step 4: Add `sync_task_code()` implementation**

In `LiveWeData`, after `sync_task_runs()`, add:

```python
    def sync_task_code(self, task_id="", task_name="", project_id=""):
        resolved_project_id = self.project_id_or_default(project_id)
        task = self.store.resolve_task(task_id, task_name)
        if not task and task_name:
            self.sync_tasks(task_name)
            task = self.store.resolve_task("", task_name)
        if not task:
            raise RuntimeError("task_not_found")
        response = self.client.call("GetTaskCode", {"ProjectId": resolved_project_id, "TaskId": task["id"]})
        if "Error" in response.get("Response", {}):
            error = response["Response"]["Error"]
            raise RuntimeError(f"GetTaskCode failed: {error.get('Code')} {error.get('Message')}")
        data = response.get("Response", {}).get("Data", {}) or {}
        code_info = data.get("CodeInfo", "")
        code_text, encoding = decode_task_code_info(code_info)
        self.store.upsert_task_code(
            resolved_project_id,
            task["id"],
            task.get("name") or task_name,
            code_info,
            code_text,
            int(data.get("CodeFileSize") or 0),
            encoding,
            data,
        )
```

- [ ] **Step 5: Run focused live test**

Run:

```bash
pytest tests/test_mcp.py::McpTest::test_live_wedata_syncs_task_code -v
```

Expected: PASS.

- [ ] **Step 6: Commit Task 2**

```bash
git add dlc_mcp/live.py tests/test_mcp.py
git commit -m "Add live WeData task code sync

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: Register and Format the MCP Tool

**Files:**
- Modify: `dlc_mcp/mcp.py:5-221`
- Modify: `dlc_mcp/mcp.py:245-447`
- Modify: `dlc_mcp/mcp.py:465-746`
- Test: `tests/test_mcp.py`

**Interfaces:**
- Consumes:
  - `AssetStore.get_task_code(project_id='', task_id='', task_name='') -> dict`
  - `LiveWeData.sync_task_code(task_id='', task_name='', project_id='') -> None`
- Produces:
  - MCP tool `get_task_code`
  - Formatter branch `_format_markdown('get_task_code', data)`
  - Helper `_code_fence_language(code_text: str) -> str`

- [ ] **Step 1: Write failing MCP tests**

Add these methods to `McpTest` in `tests/test_mcp.py`:

```python
    def test_tools_list_includes_get_task_code(self):
        response = handle_request(self.store, {"jsonrpc": "2.0", "id": 40, "method": "tools/list"})
        names = [tool["name"] for tool in response["result"]["tools"]]
        self.assertIn("get_task_code", names)

    def test_get_task_code_returns_cached_sql(self):
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
            {"jsonrpc": "2.0", "id": 41, "method": "tools/call", "params": {"name": "get_task_code", "arguments": {"task_id": "task_001"}}},
        )
        text = response["result"]["content"][0]["text"]

        self.assertIn("任务代码", text)
        self.assertIn("task_001", text)
        self.assertIn("build_dim_customer", text)
        self.assertIn("```sql", text)
        self.assertIn("select 1;", text)

    def test_get_task_code_validates_missing_identity(self):
        response = handle_request(
            self.store,
            {"jsonrpc": "2.0", "id": 42, "method": "tools/call", "params": {"name": "get_task_code", "arguments": {}}},
        )
        self.assertIn("missing_task_identity", response["result"]["content"][0]["text"])

    def test_get_task_code_live_refreshes_and_returns_decoded_sql(self):
        client = FakeWeDataClient()
        with patch.dict(os.environ, {"WEDATA_PROJECT_ID": "project"}, clear=False):
            live = LiveWeData(self.store, client=client)
            response = handle_request(
                self.store,
                {"jsonrpc": "2.0", "id": 43, "method": "tools/call", "params": {"name": "get_task_code", "arguments": {"task_id": "task_001", "live": True}}},
                live=live,
            )

        text = response["result"]["content"][0]["text"]
        self.assertIn("select * from dim_customer;", text)
        self.assertIn("base64", text)
        self.assertIn("GetTaskCode", [action for action, payload in client.calls])

    def test_get_task_code_resolves_cached_task_name(self):
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
            {"jsonrpc": "2.0", "id": 44, "method": "tools/call", "params": {"name": "get_task_code", "arguments": {"task_name": "build_dim_customer"}}},
        )
        text = response["result"]["content"][0]["text"]

        self.assertIn("task_001", text)
        self.assertIn("select 1;", text)
```

- [ ] **Step 2: Run MCP tests to verify they fail**

Run:

```bash
pytest tests/test_mcp.py::McpTest::test_tools_list_includes_get_task_code tests/test_mcp.py::McpTest::test_get_task_code_returns_cached_sql tests/test_mcp.py::McpTest::test_get_task_code_validates_missing_identity tests/test_mcp.py::McpTest::test_get_task_code_live_refreshes_and_returns_decoded_sql tests/test_mcp.py::McpTest::test_get_task_code_resolves_cached_task_name -v
```

Expected: FAIL because tool is not registered or is unknown.

- [ ] **Step 3: Register `get_task_code` in `TOOLS`**

In `dlc_mcp/mcp.py`, after the existing `get_task_runs` tool, add:

```python
    "get_task_code": {
        "description": "Return SQL/code content for a WeData task from cache or live GetTaskCode refresh.",
        "schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "task_name": {"type": "string"},
                "live": {"type": "boolean"},
            },
        },
    },
```

- [ ] **Step 4: Add `_call_tool` branch**

In `_call_tool()`, after the `get_task_runs` branch and before `list_data_sources`, add:

```python
    elif name == "get_task_code":
        if not args.get("task_id") and not args.get("task_name"):
            data = _error_data("missing_task_identity")
        else:
            project_id = os.environ.get("WEDATA_PROJECT_ID", "")
            data = store.get_task_code(project_id, args.get("task_id", ""), args.get("task_name", ""))
            if live and (args.get("live") or data.get("error") == "task_code_not_found" or (args.get("task_name") and data.get("error") == "task_not_found")):
                live.sync_task_code(task_id=args.get("task_id", ""), task_name=args.get("task_name", ""), project_id=project_id)
                data = store.get_task_code(project_id, args.get("task_id", ""), args.get("task_name", ""))
```

- [ ] **Step 5: Add Markdown formatter**

In `_format_markdown()`, before the `get_task_runs` branch, add:

```python
    if tool_name == "get_task_code":
        code_text = data.get("code_text", "")
        language = _code_fence_language(code_text)
        return _section(
            "任务代码",
            [
                f"项目ID：`{_cell(data.get('project_id'))}`",
                f"TaskId：`{_cell(data.get('task_id'))}`",
                f"任务名：**{_cell(data.get('task_name'))}**",
                f"代码大小：{data.get('code_file_size', 0)}",
                f"编码：`{_cell(data.get('encoding'))}`",
                f"更新时间：{_cell(data.get('updated_at'))}",
            ],
        ) + f"\n\n```{language}\n{code_text}\n```"
```

Near `_section()`, add:

```python
def _code_fence_language(code_text):
    lowered = (code_text or "").lower()
    if any(token in lowered for token in ("select ", "insert ", "update ", "delete ", "create ", "with ")):
        return "sql"
    return ""
```

- [ ] **Step 6: Run focused MCP tests**

Run:

```bash
pytest tests/test_mcp.py::McpTest::test_tools_list_includes_get_task_code tests/test_mcp.py::McpTest::test_get_task_code_returns_cached_sql tests/test_mcp.py::McpTest::test_get_task_code_validates_missing_identity tests/test_mcp.py::McpTest::test_get_task_code_live_refreshes_and_returns_decoded_sql tests/test_mcp.py::McpTest::test_get_task_code_resolves_cached_task_name -v
```

Expected: PASS.

- [ ] **Step 7: Commit Task 3**

```bash
git add dlc_mcp/mcp.py tests/test_mcp.py
git commit -m "Add get_task_code MCP tool

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: Run Full Regression and Update Graph

**Files:**
- Modify only if tests reveal a defect: `dlc_mcp/assets.py`, `dlc_mcp/live.py`, `dlc_mcp/mcp.py`, `tests/test_assets.py`, `tests/test_mcp.py`

**Interfaces:**
- Consumes: all outputs from Tasks 1-3.
- Produces: verified working implementation and updated code-review graph.

- [ ] **Step 1: Run full test suite**

Run:

```bash
pytest -q
```

Expected: all tests pass.

- [ ] **Step 2: If full suite fails, fix only the failing behavior**

Use the failure output to identify the exact failing test. For example, if a formatter assertion fails because Markdown changed, update only the relevant assertion or formatter. Do not broaden the feature scope.

- [ ] **Step 3: Update the code-review graph**

Run the graph updater:

```bash
python -m code_review_graph build --repo-root /Users/leve/Documents/DLC-Agent --incremental
```

If the CLI is unavailable, skip this command and rely on the repository hook to update the graph.

- [ ] **Step 4: Review final git diff**

Run:

```bash
git diff --stat HEAD~3..HEAD
```

Expected: changes are limited to the planned Python files and tests.

- [ ] **Step 5: Commit any regression fixes**

If Step 2 required changes after the Task 3 commit, commit them:

```bash
git add dlc_mcp/assets.py dlc_mcp/live.py dlc_mcp/mcp.py tests/test_assets.py tests/test_mcp.py
git commit -m "Fix get_task_code regression issues

Co-Authored-By: Claude <noreply@anthropic.com>"
```

If no fixes were required, do not create an empty commit.

---

## Self-Review

- Spec coverage: Tasks cover schema, exact task-name resolution, Base64/raw decode, live `GetTaskCode`, MCP registration, Markdown output, validation errors, and tests.
- Placeholder scan: No TBD/TODO/fill-in placeholders remain; each code-changing step includes concrete code.
- Type consistency: Method names and signatures match across tasks: `decode_task_code_info`, `resolve_task`, `upsert_task_code`, `get_task_code`, and `sync_task_code`.
