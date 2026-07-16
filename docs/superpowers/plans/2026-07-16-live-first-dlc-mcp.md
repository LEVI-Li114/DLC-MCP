# Live-first DLC MCP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make DLC MCP interactive diagnostics live-first while keeping SQLite as a registry and adding patrol snapshots for daily governance reporting.

**Architecture:** Implement this incrementally: first add explicit source semantics and live-first behavior for the highest-risk dynamic tools, then introduce focused service boundaries, then add patrol snapshot storage and report reads. SQLite remains the registry for tables/tasks/data sources; legacy dynamic cache remains accessible only through explicit `source=legacy_cache`.

**Tech Stack:** Python 3, SQLite, pytest, existing `dlc_mcp` package, Tencent Cloud WeData/DLC clients, MCP JSON-RPC tool handler.

## Global Constraints

- Use the code-review-graph MCP tools before file scanning when exploring code relationships.
- Do not treat absent data as healthy.
- Do not treat query failures as confirmed missing partitions, missing task runs, missing quality rules, or missing lineage.
- Single-table and single-task dynamic MCP tools default to live under `source=auto`.
- Search/list registry tools default to registry under `source=auto`.
- Governance report/inventory tools default to patrol snapshot under `source=auto` once patrol snapshots exist.
- Old dynamic SQLite facts must be labelled `legacy_cache` and must not be presented as current truth unless explicitly requested.
- Preserve existing table/task/data-source registry synchronization.
- Keep each task independently testable.

---

## File Structure

### Modify: `dlc_mcp/mcp.py`

Responsibilities after this plan:

- Define MCP tool schemas with `source` support.
- Resolve source behavior consistently.
- Format query metadata with `registry`, `live`, `partial_live`, `patrol_snapshot`, `legacy_cache`, and `not_available` source labels.
- Route dynamic tools to live services by default and legacy cache only when requested.
- Route patrol/governance tools to patrol snapshots once implemented.

### Modify: `dlc_mcp/live.py`

Responsibilities after this plan:

- Continue housing low-level live refresh helpers during migration.
- Add read-oriented live methods that return live data structures without requiring consumers to infer from stale cache.

### Create: `dlc_mcp/source.py`

Responsibilities:

- Define source constants and source resolution helpers.
- Keep source behavior testable without invoking MCP calls.

### Create: `dlc_mcp/live_assets.py`

Responsibilities:

- Provide `LiveAssetService` for live single-asset queries.
- Compose registry context with live API calls.
- Return structured results with module-level errors.

### Create: `dlc_mcp/patrol.py`

Responsibilities:

- Provide `PatrolService` for patrol run creation, snapshot writes, finding writes, metric writes, and error writes.
- Keep patrol execution state separate from registry and legacy dynamic cache.

### Modify: `dlc_mcp/assets.py`

Responsibilities after this plan:

- Add patrol snapshot tables to `AssetStore.init_schema()`.
- Add minimal patrol read/write methods used by `PatrolService` and MCP report tools.
- Keep legacy cache methods available but not default for live-first tools.

### Modify: `tests/test_mcp.py`

Responsibilities:

- Cover MCP source parameter behavior.
- Cover live-first partition behavior.
- Cover legacy-cache opt-in behavior.
- Cover no-patrol-snapshot behavior for governance reports.

### Create: `tests/test_source.py`

Responsibilities:

- Cover source resolution without MCP setup.

### Create: `tests/test_live_assets.py`

Responsibilities:

- Cover `LiveAssetService` module success/failure semantics.

### Create: `tests/test_patrol.py`

Responsibilities:

- Cover patrol schema, run lifecycle, findings, metrics, and errors.

---

### Task 1: Add Explicit Source Semantics

**Files:**
- Create: `dlc_mcp/source.py`
- Modify: `dlc_mcp/mcp.py:7-130`
- Test: `tests/test_source.py`
- Test: `tests/test_mcp.py`

**Interfaces:**
- Consumes: existing MCP tool names and argument dictionaries.
- Produces:
  - `Source` constants: `AUTO`, `REGISTRY`, `LIVE`, `PARTIAL_LIVE`, `PATROL_SNAPSHOT`, `LEGACY_CACHE`, `NOT_AVAILABLE`.
  - `resolve_source(tool_name: str, args: dict) -> str`.
  - `DYNAMIC_TOOLS`, `REGISTRY_TOOLS`, `PATROL_TOOLS` sets.
  - MCP schemas that accept optional `source` string.

- [ ] **Step 1: Write source resolution tests**

Create `tests/test_source.py`:

```python
from dlc_mcp.source import Source, resolve_source


def test_dynamic_tool_auto_resolves_to_live():
    assert resolve_source("get_table_partition_profile", {}) == Source.LIVE
    assert resolve_source("get_task_runs", {"source": "auto"}) == Source.LIVE


def test_registry_tool_auto_resolves_to_registry():
    assert resolve_source("search_assets", {"source": "auto"}) == Source.REGISTRY
    assert resolve_source("list_data_sources", {}) == Source.REGISTRY


def test_patrol_tool_auto_resolves_to_patrol_snapshot():
    assert resolve_source("get_asset_governance_daily_report", {}) == Source.PATROL_SNAPSHOT
    assert resolve_source("get_asset_governance_issue_inventory", {"source": "auto"}) == Source.PATROL_SNAPSHOT


def test_explicit_source_wins():
    assert resolve_source("get_table_partition_profile", {"source": "legacy_cache"}) == Source.LEGACY_CACHE
    assert resolve_source("search_assets", {"source": "live"}) == Source.LIVE


def test_live_true_maps_to_live_for_compatibility():
    assert resolve_source("get_table_partition_profile", {"live": True}) == Source.LIVE


def test_live_false_does_not_force_legacy_cache():
    assert resolve_source("get_table_partition_profile", {"live": False}) == Source.LIVE
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run:

```bash
pytest tests/test_source.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'dlc_mcp.source'`.

- [ ] **Step 3: Implement `dlc_mcp/source.py`**

Create `dlc_mcp/source.py`:

```python
class Source:
    AUTO = "auto"
    REGISTRY = "registry"
    LIVE = "live"
    PARTIAL_LIVE = "partial_live"
    PATROL_SNAPSHOT = "patrol_snapshot"
    LEGACY_CACHE = "legacy_cache"
    NOT_AVAILABLE = "not_available"


DYNAMIC_TOOLS = {
    "get_table_partition_profile",
    "get_table_production_status",
    "get_task_runs",
    "get_quality_status",
    "get_table_lineage",
    "get_table_tasks",
    "get_task_code",
    "get_table_risk_profile",
    "get_table_readiness",
    "get_table_profile",
    "get_table_production_risk_detail",
}

REGISTRY_TOOLS = {
    "search_assets",
    "search_tasks",
    "get_table",
    "list_table_columns",
    "list_data_sources",
    "get_data_source",
    "list_data_source_tasks",
    "get_data_source_inventory",
    "list_projects",
    "get_project",
    "list_project_members",
    "list_metadata",
    "get_asset_coverage",
    "get_sync_health",
}

PATROL_TOOLS = {
    "get_asset_governance_daily_report",
    "get_asset_governance_issue_inventory",
    "list_table_production_risks",
    "list_quality_gaps",
    "list_asset_coverage_gaps",
    "list_expert_review_queue",
}

VALID_SOURCES = {
    Source.AUTO,
    Source.REGISTRY,
    Source.LIVE,
    Source.PATROL_SNAPSHOT,
    Source.LEGACY_CACHE,
}


def resolve_source(tool_name, args):
    requested = (args or {}).get("source")
    if requested in VALID_SOURCES and requested != Source.AUTO:
        return requested
    if (args or {}).get("live") is True:
        return Source.LIVE
    if tool_name in DYNAMIC_TOOLS:
        return Source.LIVE
    if tool_name in PATROL_TOOLS:
        return Source.PATROL_SNAPSHOT
    if tool_name in REGISTRY_TOOLS:
        return Source.REGISTRY
    return Source.REGISTRY
```

- [ ] **Step 4: Add `source` to MCP tool schemas**

Modify `dlc_mcp/mcp.py`. Import source helpers near the top:

```python
from .source import Source, resolve_source
```

Add a helper below imports:

```python
def _with_source_schema(schema):
    properties = dict(schema.get("properties") or {})
    properties.setdefault(
        "source",
        {
            "type": "string",
            "enum": ["auto", "live", "registry", "patrol_snapshot", "legacy_cache"],
        },
    )
    return {**schema, "properties": properties}
```

After `TOOLS = {...}` is defined, add this loop before `def handle_request`:

```python
for _tool_spec in TOOLS.values():
    _tool_spec["schema"] = _with_source_schema(_tool_spec["schema"])
```

- [ ] **Step 5: Use source resolution in `_call_tool` metadata**

Modify `_call_tool` in `dlc_mcp/mcp.py` after `args = params.get("arguments") or {}`:

```python
    source = resolve_source(name, args)
```

Then after `meta = _new_query_meta(...)`, set:

```python
    meta["source"] = source
```

This is a temporary metadata-only change; later tasks will route behavior.

- [ ] **Step 6: Run source tests**

Run:

```bash
pytest tests/test_source.py -v
```

Expected: PASS.

- [ ] **Step 7: Run MCP schema smoke test**

Run:

```bash
pytest tests/test_mcp.py::McpTest::test_tools_list -v
```

Expected: PASS. If the exact test name differs, run:

```bash
pytest tests/test_mcp.py -k tools -v
```

Expected: existing tools-list tests pass and schemas include the new optional source property.

- [ ] **Step 8: Commit**

```bash
git add dlc_mcp/source.py dlc_mcp/mcp.py tests/test_source.py tests/test_mcp.py
git commit -m "feat: add MCP source semantics

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: Make Partition Profile Live-first and Legacy-cache Explicit

**Files:**
- Modify: `dlc_mcp/mcp.py:320-377`
- Modify: `tests/test_mcp.py`

**Interfaces:**
- Consumes: `Source` and `resolve_source()` from Task 1.
- Produces: `get_table_partition_profile` behavior:
  - `source=auto` uses live when a `live` object is available.
  - `source=legacy_cache` reads old SQLite partition facts.
  - live refresh is triggered even when legacy partition facts exist but a requested target partition is missing.

- [ ] **Step 1: Add regression test for stale cache with live-first default**

Append to `tests/test_mcp.py` near existing partition profile tests:

```python
class RefreshingPartitionLive:
    def __init__(self, store):
        self.store = store
        self.synced = []

    def sync_table_partitions(self, table_name):
        self.synced.append(table_name)
        self.store.upsert_table_partition(
            {
                "table_name": table_name,
                "partition_name": "dt=20260715",
                "partition_date": "20260715",
                "row_count": 2,
                "storage_bytes": 21127,
                "file_count": 1,
                "updated_at": "2026-07-16T07:02:22+08:00",
            }
        )


def test_partition_profile_auto_refreshes_stale_cache_for_requested_partition():
    conn = sqlite3.connect(":memory:")
    store = AssetStore(conn)
    store.init_schema()
    store.upsert_table({"name": "ods_cloud_cost_baidu_day_di", "database": "byai_bigdata"})
    store.upsert_column("ods_cloud_cost_baidu_day_di", "dt", "string", "", 1)
    store.upsert_table_partition(
        {
            "table_name": "ods_cloud_cost_baidu_day_di",
            "partition_name": "dt=20260706",
            "partition_date": "20260706",
            "row_count": 2,
            "storage_bytes": 21127,
            "file_count": 1,
            "updated_at": "2026-07-16T07:02:22+08:00",
        }
    )
    live = RefreshingPartitionLive(store)
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "get_table_partition_profile",
            "arguments": {"table_name": "ods_cloud_cost_baidu_day_di", "partition_date": "20260715"},
        },
    }

    response = _call_tool(store, request, live)
    text = response["result"]["content"][0]["text"]

    assert live.synced == ["ods_cloud_cost_baidu_day_di"]
    assert "数据来源：live" in text
    assert "dt=20260715" in text
```

- [ ] **Step 2: Add legacy-cache opt-in test**

Append:

```python
def test_partition_profile_legacy_cache_does_not_refresh():
    conn = sqlite3.connect(":memory:")
    store = AssetStore(conn)
    store.init_schema()
    store.upsert_table({"name": "ods_cloud_cost_baidu_day_di", "database": "byai_bigdata"})
    store.upsert_column("ods_cloud_cost_baidu_day_di", "dt", "string", "", 1)
    store.upsert_table_partition(
        {
            "table_name": "ods_cloud_cost_baidu_day_di",
            "partition_name": "dt=20260706",
            "partition_date": "20260706",
            "row_count": 2,
            "storage_bytes": 21127,
            "file_count": 1,
            "updated_at": "2026-07-16T07:02:22+08:00",
        }
    )
    live = RefreshingPartitionLive(store)
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "get_table_partition_profile",
            "arguments": {
                "table_name": "ods_cloud_cost_baidu_day_di",
                "partition_date": "20260715",
                "source": "legacy_cache",
            },
        },
    }

    response = _call_tool(store, request, live)
    text = response["result"]["content"][0]["text"]

    assert live.synced == []
    assert "数据来源：legacy_cache" in text
    assert "dt=20260706" in text
    assert "dt=20260715" not in text
```

- [ ] **Step 3: Run tests to verify failure**

Run:

```bash
pytest tests/test_mcp.py -k 'partition_profile_auto_refreshes_stale_cache or partition_profile_legacy_cache' -v
```

Expected: first test FAILS because current auto behavior does not refresh stale existing partition facts.

- [ ] **Step 4: Add helper for missing requested partition**

In `dlc_mcp/mcp.py`, add after `_empty_list`:

```python
def _partition_refresh_needed(data, partition_date):
    if _has_error(data):
        return True
    if data.get("is_partitioned") and not data.get("partition_fact_available"):
        return True
    if partition_date and data.get("status") == "missing_partition":
        return True
    return False
```

- [ ] **Step 5: Route partition profile by source**

Replace the current `elif name == "get_table_partition_profile":` block with:

```python
    elif name == "get_table_partition_profile":
        partition_date = args.get("partition_date", "")
        data = store.get_table_partition_profile(args["table_name"], partition_date)
        if source == Source.LEGACY_CACHE:
            meta["source"] = Source.LEGACY_CACHE
        elif live:
            refreshed = _maybe_live_refresh(
                meta,
                {**args, "live": True},
                data,
                lambda item: _partition_refresh_needed(item, partition_date),
                lambda: live.sync_table_partitions(args["table_name"]),
                reason="user_requested" if args.get("live") else "live_first",
            )
            if refreshed:
                meta["source"] = Source.LIVE
                data = store.get_table_partition_profile(args["table_name"], partition_date)
        else:
            meta["source"] = Source.NOT_AVAILABLE
            data = {
                "error": "live_source_unavailable",
                "table_name": args["table_name"],
                "requested_source": source,
            }
```

- [ ] **Step 6: Run focused tests**

Run:

```bash
pytest tests/test_mcp.py -k 'partition_profile_auto_refreshes_stale_cache or partition_profile_legacy_cache or partition_profile_live_true' -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add dlc_mcp/mcp.py tests/test_mcp.py
git commit -m "fix: make partition profile live-first

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: Introduce `LiveAssetService` for Structured Live Results

**Files:**
- Create: `dlc_mcp/live_assets.py`
- Modify: `tests/test_live_assets.py`

**Interfaces:**
- Consumes:
  - `AssetStore` registry methods.
  - Existing `LiveWeData` methods: `sync_table_partitions`, `sync_task_runs`, `sync_table`, `sync_task_code`.
- Produces:
  - `LiveModuleResult` dataclass.
  - `LiveAssetResult` dataclass.
  - `LiveAssetService.get_partition_profile(table_name: str, partition_date: str = "") -> LiveAssetResult`.
  - `LiveAssetService.get_task_runs(task_id: str = "", task_name: str = "", instance_date: str = "", limit: int = 10) -> LiveAssetResult`.

- [ ] **Step 1: Write tests for structured live success and failure**

Create `tests/test_live_assets.py`:

```python
import sqlite3

from dlc_mcp.assets import AssetStore
from dlc_mcp.live_assets import LiveAssetService
from dlc_mcp.source import Source


class SyncingLive:
    def __init__(self, store):
        self.store = store
        self.partition_calls = []
        self.run_calls = []

    def sync_table_partitions(self, table_name):
        self.partition_calls.append(table_name)
        self.store.upsert_table_partition(
            {
                "table_name": table_name,
                "partition_name": "dt=20260715",
                "partition_date": "20260715",
                "row_count": 2,
            }
        )

    def sync_task_runs(self, task_name="", task_id="", instance_date=""):
        self.run_calls.append((task_name, task_id, instance_date))


class FailingLive:
    def sync_table_partitions(self, table_name):
        raise RuntimeError("DescribeTablePartitions failed: Throttling rate exceeded")

    def sync_task_runs(self, task_name="", task_id="", instance_date=""):
        raise RuntimeError("ListTaskInstances failed: InternalError temporary unavailable")


def _store_with_partitioned_table():
    conn = sqlite3.connect(":memory:")
    store = AssetStore(conn)
    store.init_schema()
    store.upsert_table({"name": "ods_cloud_cost_baidu_day_di", "database": "byai_bigdata"})
    store.upsert_column("ods_cloud_cost_baidu_day_di", "dt", "string", "", 1)
    return store


def test_live_asset_service_partition_success_returns_live_result():
    store = _store_with_partitioned_table()
    live = SyncingLive(store)
    service = LiveAssetService(store, live)

    result = service.get_partition_profile("ods_cloud_cost_baidu_day_di", "20260715")

    assert result.source == Source.LIVE
    assert result.data["target_partition"]["partition_name"] == "dt=20260715"
    assert result.errors == []
    assert live.partition_calls == ["ods_cloud_cost_baidu_day_di"]


def test_live_asset_service_partition_failure_is_partial_live_not_missing():
    store = _store_with_partitioned_table()
    service = LiveAssetService(store, FailingLive())

    result = service.get_partition_profile("ods_cloud_cost_baidu_day_di", "20260715")

    assert result.source == Source.PARTIAL_LIVE
    assert result.data["status"] == "unknown"
    assert result.errors[0]["module"] == "partition"
    assert result.errors[0]["status"] == "check_failed"
    assert "Throttling" in result.errors[0]["error_message"]
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pytest tests/test_live_assets.py -v
```

Expected: FAIL with missing module/class.

- [ ] **Step 3: Implement `dlc_mcp/live_assets.py`**

Create:

```python
from dataclasses import dataclass, field

from .source import Source


@dataclass
class LiveAssetResult:
    source: str
    data: dict
    errors: list = field(default_factory=list)

    def as_dict(self):
        result = dict(self.data or {})
        result["source"] = self.source
        if self.errors:
            result["errors"] = self.errors
        return result


class LiveAssetService:
    def __init__(self, store, live):
        self.store = store
        self.live = live

    def get_partition_profile(self, table_name, partition_date=""):
        try:
            self.live.sync_table_partitions(table_name)
            data = self.store.get_table_partition_profile(table_name, partition_date)
            return LiveAssetResult(Source.LIVE, data, [])
        except Exception as exc:
            data = self.store.get_table_partition_profile(table_name, partition_date)
            safe = {
                "table_name": table_name,
                "partition_date": partition_date,
                "is_partitioned": data.get("is_partitioned", False),
                "partition_field": data.get("partition_field", ""),
                "partition_fact_available": False,
                "status": "unknown",
                "target_partition": None,
                "recent_partitions": [],
            }
            return LiveAssetResult(
                Source.PARTIAL_LIVE,
                safe,
                [
                    {
                        "module": "partition",
                        "status": "check_failed",
                        "api_action": "ListTablePartitions",
                        "error_message": str(exc),
                        "retryable": _retryable_error(str(exc)),
                    }
                ],
            )

    def get_task_runs(self, task_id="", task_name="", instance_date="", limit=10):
        try:
            self.live.sync_task_runs(task_name=task_name, task_id=task_id, instance_date=instance_date)
            if task_name:
                data = self.store.get_task_runs_by_name(task_name, limit, instance_date)
            else:
                data = self.store.get_task_runs(task_id, limit, instance_date)
            return LiveAssetResult(Source.LIVE, data, [])
        except Exception as exc:
            return LiveAssetResult(
                Source.PARTIAL_LIVE,
                {
                    "task_id": task_id,
                    "task_name": task_name,
                    "runs": [],
                    "status": "unknown",
                },
                [
                    {
                        "module": "task_runs",
                        "status": "check_failed",
                        "api_action": "ListTaskInstances",
                        "error_message": str(exc),
                        "retryable": _retryable_error(str(exc)),
                    }
                ],
            )


def _retryable_error(message):
    text = (message or "").lower()
    return any(token in text for token in ("timeout", "throttl", "rate", "internal", "temporary", "5"))
```

- [ ] **Step 4: Run tests**

Run:

```bash
pytest tests/test_live_assets.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dlc_mcp/live_assets.py tests/test_live_assets.py
git commit -m "feat: add live asset service

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: Route Partition Profile and Task Runs Through `LiveAssetService`

**Files:**
- Modify: `dlc_mcp/mcp.py:342-449`
- Modify: `tests/test_mcp.py`

**Interfaces:**
- Consumes: `LiveAssetService` from Task 3.
- Produces:
  - `get_table_partition_profile` live path uses `LiveAssetService.get_partition_profile()`.
  - `get_task_runs` live path uses `LiveAssetService.get_task_runs()`.
  - Partial live errors are included in formatted output.

- [ ] **Step 1: Add MCP test for task run live failure**

Append to `tests/test_mcp.py`:

```python
class FailingTaskRunLive:
    def sync_task_runs(self, task_name="", task_id="", instance_date=""):
        raise RuntimeError("ListTaskInstances failed: InternalError temporary unavailable")


def test_task_runs_live_failure_returns_unknown_not_empty_runs():
    conn = sqlite3.connect(":memory:")
    store = AssetStore(conn)
    store.init_schema()
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "get_task_runs",
            "arguments": {"task_id": "task-1", "instance_date": "2026-07-15"},
        },
    }

    response = _call_tool(store, request, FailingTaskRunLive())
    text = response["result"]["content"][0]["text"]

    assert "数据来源：partial_live" in text
    assert "task_runs" in text
    assert "check_failed" in text
    assert "InternalError" in text
```

- [ ] **Step 2: Run focused test and verify failure**

Run:

```bash
pytest tests/test_mcp.py -k task_runs_live_failure_returns_unknown -v
```

Expected: FAIL because current MCP path returns cached empty runs or live refresh failure metadata without structured module error.

- [ ] **Step 3: Import service and add error formatting**

In `dlc_mcp/mcp.py`, add import:

```python
from .live_assets import LiveAssetService
```

In `_format_markdown`, after the existing error-data block, add:

```python
    if isinstance(data, dict) and data.get("errors"):
        error_rows = [
            [err.get("module"), err.get("status"), err.get("api_action"), err.get("error_message"), err.get("retryable")]
            for err in data.get("errors", [])
        ]
        base = {k: v for k, v in data.items() if k != "errors"}
        return _section("部分查询失败", [f"状态：`{_cell(base.get('status', 'unknown'))}`"]) + "\n\n" + _table(
            ["模块", "状态", "API", "错误", "可重试"],
            error_rows,
        )
```

- [ ] **Step 4: Route live partition profile through service**

In the partition block from Task 2, replace the live branch with:

```python
        elif live:
            result = LiveAssetService(store, live).get_partition_profile(args["table_name"], partition_date)
            meta["source"] = result.source
            meta["live_attempted"] = True
            meta["live_reason"] = "user_requested" if args.get("live") else "live_first"
            data = result.as_dict()
```

- [ ] **Step 5: Route task runs through service**

Replace the `elif name == "get_task_runs":` block with:

```python
    elif name == "get_task_runs":
        if not args.get("task_id") and not args.get("task_name"):
            data = _error_data("missing_task_identity")
        elif source == Source.LEGACY_CACHE:
            meta["source"] = Source.LEGACY_CACHE
            if args.get("task_name"):
                data = store.get_task_runs_by_name(args["task_name"], args.get("limit", 10), args.get("instance_date", ""))
            else:
                data = store.get_task_runs(args["task_id"], args.get("limit", 10), args.get("instance_date", ""))
        elif live:
            result = LiveAssetService(store, live).get_task_runs(
                task_id=args.get("task_id", ""),
                task_name=args.get("task_name", ""),
                instance_date=args.get("instance_date", ""),
                limit=args.get("limit", 10),
            )
            meta["source"] = result.source
            meta["live_attempted"] = True
            meta["live_reason"] = "live_first"
            data = result.as_dict()
        else:
            meta["source"] = Source.NOT_AVAILABLE
            data = _error_data("live_source_unavailable", requested_source=source)
```

- [ ] **Step 6: Run focused tests**

Run:

```bash
pytest tests/test_mcp.py -k 'partition_profile_auto_refreshes_stale_cache or partition_profile_legacy_cache or task_runs_live_failure_returns_unknown' -v
```

Expected: PASS.

- [ ] **Step 7: Run related service tests**

Run:

```bash
pytest tests/test_live_assets.py tests/test_source.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add dlc_mcp/mcp.py tests/test_mcp.py
git commit -m "feat: route dynamic MCP reads through live service

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: Add Patrol Snapshot Schema and Store Methods

**Files:**
- Modify: `dlc_mcp/assets.py:180-300`
- Create: `tests/test_patrol.py`

**Interfaces:**
- Consumes: existing `AssetStore` SQLite connection and schema migration style.
- Produces methods on `AssetStore`:
  - `create_patrol_run(run_id: str, instance_date: str, scope: str, config: dict) -> None`
  - `finish_patrol_run(run_id: str, status: str, summary: dict) -> None`
  - `upsert_patrol_asset_snapshot(item: dict) -> None`
  - `insert_patrol_finding(item: dict) -> None`
  - `insert_patrol_metric(item: dict) -> None`
  - `insert_patrol_error(item: dict) -> None`
  - `latest_patrol_run(instance_date: str = "", scope: str = "") -> dict | None`
  - `get_patrol_report_data(run_id: str) -> dict`

- [ ] **Step 1: Write patrol store tests**

Create `tests/test_patrol.py`:

```python
import sqlite3

from dlc_mcp.assets import AssetStore


def test_patrol_run_lifecycle_and_report_data():
    store = AssetStore(sqlite3.connect(":memory:"))
    store.init_schema()

    store.create_patrol_run("run-1", "2026-07-16", "daily_p0", {"limit": 10})
    store.upsert_patrol_asset_snapshot(
        {
            "run_id": "run-1",
            "asset_name": "ods_cloud_cost_baidu_day_di",
            "asset_type": "table",
            "layer": "ods",
            "owner": "prod-bigdata",
            "core_level": "非核心",
            "status": "risk",
            "snapshot": {"latest_partition": "dt=20260715"},
        }
    )
    store.insert_patrol_finding(
        {
            "run_id": "run-1",
            "asset_name": "ods_cloud_cost_baidu_day_di",
            "issue_type": "missing_quality_rules",
            "severity": "P1",
            "evidence": {"quality_rule_count": 0},
            "owner_bucket": "warehouse_owner",
            "suggested_action": "Add or confirm quality monitoring rule coverage.",
        }
    )
    store.insert_patrol_metric(
        {
            "run_id": "run-1",
            "metric_name": "checked_count",
            "metric_value": 1,
            "dimension": {"scope": "daily_p0"},
        }
    )
    store.insert_patrol_error(
        {
            "run_id": "run-1",
            "asset_name": "ods_cloud_cost_baidu_day_di",
            "module": "lineage",
            "api_action": "ListLineage",
            "error_code": "InternalError",
            "error_message": "temporary unavailable",
            "retryable": True,
        }
    )
    store.finish_patrol_run("run-1", "partial", {"checked_count": 1, "error_count": 1})

    latest = store.latest_patrol_run("2026-07-16", "daily_p0")
    report = store.get_patrol_report_data("run-1")

    assert latest["run_id"] == "run-1"
    assert latest["status"] == "partial"
    assert report["run"]["run_id"] == "run-1"
    assert report["snapshots"][0]["asset_name"] == "ods_cloud_cost_baidu_day_di"
    assert report["findings"][0]["issue_type"] == "missing_quality_rules"
    assert report["metrics"][0]["metric_name"] == "checked_count"
    assert report["errors"][0]["module"] == "lineage"
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pytest tests/test_patrol.py -v
```

Expected: FAIL with missing methods/tables.

- [ ] **Step 3: Add patrol tables to schema**

In `AssetStore.init_schema()` in `dlc_mcp/assets.py`, add the following SQL inside the existing `executescript` block after `table_partitions` or before `expert_labels`:

```sql
            create table if not exists patrol_runs (
                run_id text primary key,
                instance_date text not null default '',
                scope text not null default '',
                status text not null default 'running',
                started_at text not null default (datetime('now')),
                finished_at text not null default '',
                asset_count integer not null default 0,
                checked_count integer not null default 0,
                error_count integer not null default 0,
                config_json text not null default '{}',
                summary_json text not null default '{}'
            );
            create table if not exists patrol_asset_snapshots (
                run_id text not null,
                asset_name text not null,
                asset_type text not null default 'table',
                layer text not null default '',
                owner text not null default '',
                core_level text not null default '',
                status text not null default 'unknown',
                snapshot_json text not null default '{}',
                checked_at text not null default (datetime('now')),
                primary key (run_id, asset_type, asset_name)
            );
            create table if not exists patrol_findings (
                id integer primary key autoincrement,
                run_id text not null,
                asset_name text not null,
                issue_type text not null,
                severity text not null default '',
                evidence_json text not null default '{}',
                owner_bucket text not null default '',
                suggested_action text not null default '',
                created_at text not null default (datetime('now'))
            );
            create table if not exists patrol_metrics (
                id integer primary key autoincrement,
                run_id text not null,
                metric_name text not null,
                metric_value real not null default 0,
                dimension_json text not null default '{}',
                created_at text not null default (datetime('now'))
            );
            create table if not exists patrol_errors (
                id integer primary key autoincrement,
                run_id text not null,
                asset_name text not null default '',
                module text not null default '',
                api_action text not null default '',
                error_code text not null default '',
                error_message text not null default '',
                retryable integer not null default 0,
                created_at text not null default (datetime('now'))
            );
```

After existing index creation calls, add:

```python
        self.conn.execute("create index if not exists idx_patrol_runs_date_scope on patrol_runs (instance_date, scope, status)")
        self.conn.execute("create index if not exists idx_patrol_findings_run on patrol_findings (run_id, severity, issue_type)")
        self.conn.execute("create index if not exists idx_patrol_errors_run on patrol_errors (run_id, module)")
```

- [ ] **Step 4: Add patrol store methods**

Add methods to `AssetStore` near other insert/upsert helpers:

```python
    def create_patrol_run(self, run_id, instance_date, scope, config):
        self.conn.execute(
            """
            insert into patrol_runs (run_id, instance_date, scope, status, config_json)
            values (?, ?, ?, 'running', ?)
            on conflict(run_id) do update set
                instance_date = excluded.instance_date,
                scope = excluded.scope,
                status = 'running',
                config_json = excluded.config_json,
                summary_json = '{}',
                finished_at = ''
            """,
            (run_id, instance_date, scope, json.dumps(config or {}, ensure_ascii=False)),
        )
        self.conn.commit()

    def finish_patrol_run(self, run_id, status, summary):
        summary = summary or {}
        self.conn.execute(
            """
            update patrol_runs
            set status = ?,
                finished_at = datetime('now'),
                checked_count = ?,
                error_count = ?,
                summary_json = ?
            where run_id = ?
            """,
            (
                status,
                int(summary.get("checked_count") or 0),
                int(summary.get("error_count") or 0),
                json.dumps(summary, ensure_ascii=False),
                run_id,
            ),
        )
        self.conn.commit()

    def upsert_patrol_asset_snapshot(self, item):
        self.conn.execute(
            """
            insert into patrol_asset_snapshots
                (run_id, asset_name, asset_type, layer, owner, core_level, status, snapshot_json, checked_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            on conflict(run_id, asset_type, asset_name) do update set
                layer = excluded.layer,
                owner = excluded.owner,
                core_level = excluded.core_level,
                status = excluded.status,
                snapshot_json = excluded.snapshot_json,
                checked_at = excluded.checked_at
            """,
            (
                item["run_id"],
                item["asset_name"],
                item.get("asset_type", "table"),
                item.get("layer", ""),
                item.get("owner", ""),
                item.get("core_level", ""),
                item.get("status", "unknown"),
                json.dumps(item.get("snapshot") or {}, ensure_ascii=False),
            ),
        )
        self.conn.commit()

    def insert_patrol_finding(self, item):
        self.conn.execute(
            """
            insert into patrol_findings
                (run_id, asset_name, issue_type, severity, evidence_json, owner_bucket, suggested_action)
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["run_id"],
                item["asset_name"],
                item["issue_type"],
                item.get("severity", ""),
                json.dumps(item.get("evidence") or {}, ensure_ascii=False),
                item.get("owner_bucket", ""),
                item.get("suggested_action", ""),
            ),
        )
        self.conn.commit()

    def insert_patrol_metric(self, item):
        self.conn.execute(
            """
            insert into patrol_metrics (run_id, metric_name, metric_value, dimension_json)
            values (?, ?, ?, ?)
            """,
            (
                item["run_id"],
                item["metric_name"],
                float(item.get("metric_value") or 0),
                json.dumps(item.get("dimension") or {}, ensure_ascii=False),
            ),
        )
        self.conn.commit()

    def insert_patrol_error(self, item):
        self.conn.execute(
            """
            insert into patrol_errors
                (run_id, asset_name, module, api_action, error_code, error_message, retryable)
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["run_id"],
                item.get("asset_name", ""),
                item.get("module", ""),
                item.get("api_action", ""),
                item.get("error_code", ""),
                item.get("error_message", ""),
                1 if item.get("retryable") else 0,
            ),
        )
        self.conn.commit()

    def latest_patrol_run(self, instance_date="", scope=""):
        where = ["status in ('completed', 'partial')"]
        params = []
        if instance_date:
            where.append("instance_date = ?")
            params.append(instance_date)
        if scope:
            where.append("scope = ?")
            params.append(scope)
        row = self._one(
            "select * from patrol_runs where " + " and ".join(where) + " order by finished_at desc, started_at desc limit 1",
            tuple(params),
        )
        return dict(row) if row else None

    def get_patrol_report_data(self, run_id):
        run = self._one("select * from patrol_runs where run_id = ?", (run_id,))
        if not run:
            return {"error": "patrol_run_not_found", "run_id": run_id}
        return {
            "run": dict(run),
            "snapshots": [dict(row) for row in self._all("select * from patrol_asset_snapshots where run_id = ? order by asset_name", (run_id,))],
            "findings": [dict(row) for row in self._all("select * from patrol_findings where run_id = ? order by severity, issue_type, asset_name", (run_id,))],
            "metrics": [dict(row) for row in self._all("select * from patrol_metrics where run_id = ? order by metric_name", (run_id,))],
            "errors": [dict(row) for row in self._all("select * from patrol_errors where run_id = ? order by module, asset_name", (run_id,))],
        }
```

Ensure `assets.py` already imports `json`; if not, add `import json` at the top.

- [ ] **Step 5: Run patrol tests**

Run:

```bash
pytest tests/test_patrol.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add dlc_mcp/assets.py tests/test_patrol.py
git commit -m "feat: add patrol snapshot storage

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: Add `PatrolService` and Minimal Daily P0 Execution

**Files:**
- Create: `dlc_mcp/patrol.py`
- Modify: `tests/test_patrol.py`

**Interfaces:**
- Consumes:
  - `AssetStore` patrol methods from Task 5.
  - `LiveAssetService.get_partition_profile()` from Task 3.
- Produces:
  - `PatrolService.run_daily_p0(instance_date: str, limit: int = 50) -> dict`.
  - Run status `completed`, `partial`, or `failed` based on module failures.

- [ ] **Step 1: Add patrol service test**

Append to `tests/test_patrol.py`:

```python
from dlc_mcp.patrol import PatrolService


class PatrolLive:
    def __init__(self, store):
        self.store = store

    def sync_table_partitions(self, table_name):
        self.store.upsert_table_partition(
            {
                "table_name": table_name,
                "partition_name": "dt=20260715",
                "partition_date": "20260715",
                "row_count": 2,
            }
        )


def test_patrol_service_daily_p0_writes_run_snapshot_and_metric():
    store = AssetStore(sqlite3.connect(":memory:"))
    store.init_schema()
    store.upsert_table({"name": "ods_cloud_cost_baidu_day_di", "layer": "ods", "owner": "prod-bigdata", "database": "byai_bigdata"})
    store.upsert_column("ods_cloud_cost_baidu_day_di", "dt", "string", "", 1)

    result = PatrolService(store, PatrolLive(store)).run_daily_p0("2026-07-16", limit=1)
    report = store.get_patrol_report_data(result["run_id"])

    assert result["status"] == "completed"
    assert report["run"]["scope"] == "daily_p0"
    assert report["snapshots"][0]["asset_name"] == "ods_cloud_cost_baidu_day_di"
    assert report["metrics"][0]["metric_name"] == "checked_count"
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
pytest tests/test_patrol.py -k patrol_service_daily_p0 -v
```

Expected: FAIL with missing `dlc_mcp.patrol`.

- [ ] **Step 3: Implement `dlc_mcp/patrol.py`**

Create:

```python
from datetime import datetime

from .live_assets import LiveAssetService
from .source import Source


class PatrolService:
    def __init__(self, store, live):
        self.store = store
        self.live = live

    def run_daily_p0(self, instance_date, limit=50):
        run_id = f"{instance_date}_daily_p0"
        candidates = self._daily_p0_candidates(limit)
        self.store.create_patrol_run(run_id, instance_date, "daily_p0", {"limit": limit})
        checked = 0
        errors = 0
        for table in candidates:
            checked += 1
            result = LiveAssetService(self.store, self.live).get_partition_profile(table["name"], "")
            if result.source == Source.PARTIAL_LIVE:
                errors += len(result.errors)
                for error in result.errors:
                    self.store.insert_patrol_error(
                        {
                            "run_id": run_id,
                            "asset_name": table["name"],
                            "module": error.get("module", ""),
                            "api_action": error.get("api_action", ""),
                            "error_code": error.get("error_code", ""),
                            "error_message": error.get("error_message", ""),
                            "retryable": error.get("retryable", False),
                        }
                    )
            status = "check_failed" if result.source == Source.PARTIAL_LIVE else "ok"
            self.store.upsert_patrol_asset_snapshot(
                {
                    "run_id": run_id,
                    "asset_name": table["name"],
                    "asset_type": "table",
                    "layer": table.get("layer", ""),
                    "owner": table.get("owner", ""),
                    "core_level": "",
                    "status": status,
                    "snapshot": result.as_dict(),
                }
            )
        self.store.insert_patrol_metric(
            {
                "run_id": run_id,
                "metric_name": "checked_count",
                "metric_value": checked,
                "dimension": {"scope": "daily_p0"},
            }
        )
        self.store.insert_patrol_metric(
            {
                "run_id": run_id,
                "metric_name": "error_count",
                "metric_value": errors,
                "dimension": {"scope": "daily_p0"},
            }
        )
        status = "completed" if errors == 0 else "partial"
        if checked and errors / checked > 0.30:
            status = "failed"
        summary = {"checked_count": checked, "error_count": errors, "finished_at": datetime.utcnow().isoformat()}
        self.store.finish_patrol_run(run_id, status, summary)
        return {"run_id": run_id, "status": status, **summary}

    def _daily_p0_candidates(self, limit):
        rows = self.store._all(
            """
            select name, layer, owner, database
            from tables
            where layer in ('ods', 'dim', 'dwd', 'dws', 'mid', 'ads')
            order by case when layer in ('ads', 'dws', 'dwd') then 0 else 1 end, name
            limit ?
            """,
            (int(limit or 50),),
        )
        return [dict(row) for row in rows]
```

- [ ] **Step 4: Run patrol tests**

Run:

```bash
pytest tests/test_patrol.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dlc_mcp/patrol.py tests/test_patrol.py
git commit -m "feat: add daily patrol service

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: Route Governance Reports to Patrol Snapshot by Default

**Files:**
- Modify: `dlc_mcp/mcp.py:570-584`
- Modify: `dlc_mcp/mcp.py` formatting section
- Modify: `tests/test_mcp.py`

**Interfaces:**
- Consumes: `AssetStore.latest_patrol_run()` and `AssetStore.get_patrol_report_data()` from Task 5.
- Produces: `get_asset_governance_daily_report source=auto` reads patrol snapshot or returns `patrol_snapshot_not_found`.

- [ ] **Step 1: Add no-snapshot MCP test**

Append to `tests/test_mcp.py`:

```python
def test_daily_report_auto_requires_patrol_snapshot():
    conn = sqlite3.connect(":memory:")
    store = AssetStore(conn)
    store.init_schema()
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "get_asset_governance_daily_report",
            "arguments": {"instance_date": "2026-07-16"},
        },
    }

    response = _call_tool(store, request)
    text = response["result"]["content"][0]["text"]

    assert "数据来源：patrol_snapshot" in text
    assert "patrol_snapshot_not_found" in text
```

- [ ] **Step 2: Add snapshot-backed report test**

Append:

```python
def test_daily_report_auto_reads_latest_patrol_snapshot():
    conn = sqlite3.connect(":memory:")
    store = AssetStore(conn)
    store.init_schema()
    store.create_patrol_run("run-1", "2026-07-16", "daily_p0", {})
    store.insert_patrol_metric({"run_id": "run-1", "metric_name": "checked_count", "metric_value": 1, "dimension": {}})
    store.finish_patrol_run("run-1", "completed", {"checked_count": 1, "error_count": 0})
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "get_asset_governance_daily_report",
            "arguments": {"instance_date": "2026-07-16"},
        },
    }

    response = _call_tool(store, request)
    text = response["result"]["content"][0]["text"]

    assert "数据来源：patrol_snapshot" in text
    assert "run-1" in text
    assert "checked_count" in text
```

- [ ] **Step 3: Run tests to verify failure**

Run:

```bash
pytest tests/test_mcp.py -k 'daily_report_auto_requires_patrol_snapshot or daily_report_auto_reads_latest_patrol_snapshot' -v
```

Expected: FAIL because current daily report reads legacy cache.

- [ ] **Step 4: Add patrol report formatter**

In `_format_markdown` before existing `if tool_name == "list_projects":`, add:

```python
    if tool_name == "get_asset_governance_daily_report" and data.get("source") == "patrol_snapshot":
        if data.get("error"):
            return _section("每日巡检报告", [f"错误：`{_cell(data.get('error'))}`", "没有可用巡检快照，请先运行每日巡检。"])
        run = data.get("run") or {}
        metrics = data.get("metrics") or []
        findings = data.get("findings") or []
        errors = data.get("errors") or []
        return "\n\n".join(
            [
                _section(
                    "每日巡检报告",
                    [
                        f"Run ID：`{_cell(run.get('run_id'))}`",
                        f"日期：`{_cell(run.get('instance_date'))}`",
                        f"范围：`{_cell(run.get('scope'))}`",
                        f"状态：`{_cell(run.get('status'))}`",
                        f"完成检查：{_cell(run.get('checked_count'))}",
                        f"错误数：{_cell(run.get('error_count'))}",
                    ],
                ),
                _section("巡检指标", []) + "\n\n" + _table(["指标", "值", "维度"], [[m.get("metric_name"), m.get("metric_value"), m.get("dimension_json")] for m in metrics]),
                _section("发现的问题", []) + "\n\n" + _table(["资产", "问题", "严重级别", "责任桶"], [[f.get("asset_name"), f.get("issue_type"), f.get("severity"), f.get("owner_bucket")] for f in findings]),
                _section("本次巡检未完成检查", []) + "\n\n" + _table(["资产", "模块", "API", "错误"], [[e.get("asset_name"), e.get("module"), e.get("api_action"), e.get("error_message")] for e in errors]),
            ]
        )
```

- [ ] **Step 5: Route daily report by source**

Replace the daily report block with:

```python
    elif name == "get_asset_governance_daily_report":
        if source == Source.LEGACY_CACHE:
            meta["source"] = Source.LEGACY_CACHE
            data = store.get_asset_governance_daily_report(args.get("instance_date", ""), args.get("layer", ""), args.get("core_level", ""))
        else:
            meta["source"] = Source.PATROL_SNAPSHOT
            run = store.latest_patrol_run(args.get("instance_date", ""), args.get("scope", ""))
            if not run:
                data = {"source": Source.PATROL_SNAPSHOT, "error": "patrol_snapshot_not_found"}
            else:
                data = store.get_patrol_report_data(run["run_id"])
                data["source"] = Source.PATROL_SNAPSHOT
```

Add `scope` to `get_asset_governance_daily_report` schema near its existing schema definition if not present:

```python
"scope": {"type": "string"},
```

- [ ] **Step 6: Run focused tests**

Run:

```bash
pytest tests/test_mcp.py -k 'daily_report_auto_requires_patrol_snapshot or daily_report_auto_reads_latest_patrol_snapshot' -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add dlc_mcp/mcp.py tests/test_mcp.py
git commit -m "feat: read governance reports from patrol snapshots

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 8: Add Patrol CLI Entry Point

**Files:**
- Create: `dlc_mcp/asset_patrol.py`
- Modify: `tests/test_patrol.py`

**Interfaces:**
- Consumes: `PatrolService.run_daily_p0()` from Task 6.
- Produces: CLI module runnable as `python3 -m dlc_mcp.asset_patrol --scope daily_p0 --instance-date 2026-07-16 --limit 50`.

- [ ] **Step 1: Add CLI argument parsing test**

Append to `tests/test_patrol.py`:

```python
from dlc_mcp.asset_patrol import parse_args


def test_asset_patrol_parse_args():
    args = parse_args(["--scope", "daily_p0", "--instance-date", "2026-07-16", "--limit", "5"])

    assert args.scope == "daily_p0"
    assert args.instance_date == "2026-07-16"
    assert args.limit == 5
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
pytest tests/test_patrol.py -k asset_patrol_parse_args -v
```

Expected: FAIL with missing module.

- [ ] **Step 3: Implement CLI**

Create `dlc_mcp/asset_patrol.py`:

```python
import argparse
import json
import os
import sqlite3
from datetime import date, timedelta

from .assets import AssetStore
from .live import LiveWeData
from .patrol import PatrolService


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Run DLC MCP asset patrol")
    parser.add_argument("--scope", default="daily_p0", choices=["daily_p0"], help="Patrol scope to run")
    parser.add_argument("--instance-date", default=_default_instance_date(), help="Instance date in YYYY-MM-DD format")
    parser.add_argument("--limit", type=int, default=50, help="Maximum assets to check")
    parser.add_argument("--db", default=os.environ.get("DLC_MCP_DB", "/data/dlc-mcp/assets.db"), help="SQLite asset DB path")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    conn = sqlite3.connect(args.db)
    store = AssetStore(conn)
    store.init_schema()
    live = LiveWeData(store)
    service = PatrolService(store, live)
    if args.scope == "daily_p0":
        result = service.run_daily_p0(args.instance_date, limit=args.limit)
    else:
        raise SystemExit(f"unsupported scope: {args.scope}")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _default_instance_date():
    return (date.today() - timedelta(days=1)).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run CLI parse test**

Run:

```bash
pytest tests/test_patrol.py -k asset_patrol_parse_args -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dlc_mcp/asset_patrol.py tests/test_patrol.py
git commit -m "feat: add asset patrol CLI

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 9: Migrate Governance Inventory and Gap Lists to Patrol Snapshot Stubs

**Files:**
- Modify: `dlc_mcp/mcp.py:507-584`
- Modify: `tests/test_mcp.py`

**Interfaces:**
- Consumes: patrol snapshot storage from Task 5.
- Produces:
  - `get_asset_governance_issue_inventory source=auto` reads latest patrol findings.
  - `list_table_production_risks`, `list_quality_gaps`, and `list_asset_coverage_gaps source=auto` read latest patrol findings/metrics where possible or return `patrol_snapshot_not_found`.
  - `source=legacy_cache` retains old behavior.

- [ ] **Step 1: Add issue inventory patrol snapshot test**

Append to `tests/test_mcp.py`:

```python
def test_issue_inventory_auto_reads_patrol_findings():
    conn = sqlite3.connect(":memory:")
    store = AssetStore(conn)
    store.init_schema()
    store.create_patrol_run("run-1", "2026-07-16", "daily_p0", {})
    store.insert_patrol_finding(
        {
            "run_id": "run-1",
            "asset_name": "ods_cloud_cost_baidu_day_di",
            "issue_type": "missing_quality_rules",
            "severity": "P1",
            "evidence": {"quality_rule_count": 0},
            "owner_bucket": "warehouse_owner",
            "suggested_action": "Add or confirm quality monitoring rule coverage.",
        }
    )
    store.finish_patrol_run("run-1", "completed", {"checked_count": 1, "error_count": 0})
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "get_asset_governance_issue_inventory",
            "arguments": {"instance_date": "2026-07-16"},
        },
    }

    response = _call_tool(store, request)
    text = response["result"]["content"][0]["text"]

    assert "数据来源：patrol_snapshot" in text
    assert "missing_quality_rules" in text
    assert "ods_cloud_cost_baidu_day_di" in text
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
pytest tests/test_mcp.py -k issue_inventory_auto_reads_patrol_findings -v
```

Expected: FAIL because inventory still reads legacy cache.

- [ ] **Step 3: Add patrol inventory formatter**

In `_format_markdown`, before existing specific governance formatting, add:

```python
    if tool_name == "get_asset_governance_issue_inventory" and data.get("source") == "patrol_snapshot":
        if data.get("error"):
            return _section("治理问题清单", [f"错误：`{_cell(data.get('error'))}`", "没有可用巡检快照，请先运行每日巡检。"])
        findings = data.get("findings") or []
        return _section("治理问题清单", [f"Run ID：`{_cell(data.get('run_id'))}`", f"问题数：{len(findings)}"]) + "\n\n" + _table(
            ["资产", "问题", "严重级别", "责任桶", "建议动作"],
            [[f.get("asset_name"), f.get("issue_type"), f.get("severity"), f.get("owner_bucket"), f.get("suggested_action")] for f in findings],
        )
```

- [ ] **Step 4: Route issue inventory by source**

Replace the `get_asset_governance_issue_inventory` block with:

```python
    elif name == "get_asset_governance_issue_inventory":
        if source == Source.LEGACY_CACHE:
            meta["source"] = Source.LEGACY_CACHE
            data = store.get_asset_governance_issue_inventory(
                args.get("layer", ""),
                args.get("core_level", ""),
                args.get("issue_type", ""),
                int(args.get("limit", 100)),
            )
        else:
            meta["source"] = Source.PATROL_SNAPSHOT
            run = store.latest_patrol_run(args.get("instance_date", ""), args.get("scope", ""))
            if not run:
                data = {"source": Source.PATROL_SNAPSHOT, "error": "patrol_snapshot_not_found"}
            else:
                report = store.get_patrol_report_data(run["run_id"])
                findings = report.get("findings", [])
                issue_type = args.get("issue_type", "")
                if issue_type:
                    findings = [item for item in findings if item.get("issue_type") == issue_type]
                data = {"source": Source.PATROL_SNAPSHOT, "run_id": run["run_id"], "findings": findings[: int(args.get("limit", 100))]}
```

- [ ] **Step 5: Run focused test**

Run:

```bash
pytest tests/test_mcp.py -k issue_inventory_auto_reads_patrol_findings -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add dlc_mcp/mcp.py tests/test_mcp.py
git commit -m "feat: read governance inventory from patrol findings

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 10: Documentation and Full Regression Verification

**Files:**
- Modify: `README.md` or existing project documentation if there is a DLC MCP usage section
- Modify: `docs/superpowers/specs/2026-07-16-live-first-dlc-mcp-design.md` only if implementation decisions differ from the approved spec
- Test: full relevant test suite

**Interfaces:**
- Consumes: all previous tasks.
- Produces: documented operational guidance for source modes, live-first behavior, and patrol snapshots.

- [ ] **Step 1: Locate documentation target**

Run:

```bash
rg -n "dlc-mcp|DLC MCP|asset governance|governance" README.md docs dlc_mcp || true
```

Expected: output identifies the best existing doc to update. If no usage doc exists, use `README.md`.

- [ ] **Step 2: Add user-facing source mode documentation**

Add this section to the chosen doc:

```markdown
## DLC MCP source modes

DLC MCP uses three primary data sources:

- `registry`: SQLite index for tables, tasks, data sources, and project metadata.
- `live`: current Tencent Cloud / DLC / WeData API results for dynamic facts such as partitions, task runs, quality, lineage, and task code.
- `patrol_snapshot`: a specific daily patrol run used for governance reports and issue inventories.

Default `source=auto` behavior:

- Single-table and single-task diagnostics use `live`.
- Search and list tools use `registry`.
- Governance reports and issue inventories use the latest `patrol_snapshot`.

Use `source=legacy_cache` only for debugging old SQLite dynamic facts. Legacy cache results do not represent current truth.

Query failures are reported as `check_failed` or `partial_live`; they are not treated as confirmed missing partitions, missing task runs, missing quality rules, or missing lineage.
```

- [ ] **Step 3: Add patrol operation documentation**

Add:

```markdown
## Running daily asset patrol

Run a daily P0 patrol with:

```bash
python3 -m dlc_mcp.asset_patrol --scope daily_p0 --instance-date YYYY-MM-DD --limit 50
```

The patrol writes:

- `patrol_runs`
- `patrol_asset_snapshots`
- `patrol_findings`
- `patrol_metrics`
- `patrol_errors`

Governance report tools read a single patrol `run_id` so report evidence is time-consistent. If no patrol snapshot exists, report tools ask the user to run patrol instead of falling back to legacy dynamic cache.
```

- [ ] **Step 4: Run all focused tests**

Run:

```bash
pytest tests/test_source.py tests/test_live_assets.py tests/test_patrol.py tests/test_mcp.py -v
```

Expected: PASS.

- [ ] **Step 5: Run full test suite**

Run:

```bash
pytest -q
```

Expected: PASS. If unrelated pre-existing failures occur, capture the failing tests and output in the handoff instead of hiding them.

- [ ] **Step 6: Update code-review graph after changes**

Run via MCP or CLI-equivalent graph update if available:

```text
mcp__code-review-graph__build_or_update_graph_tool(repo_root="/Users/leve/Documents/DLC-Agent", full_rebuild=false, postprocess="minimal")
```

Expected: graph update succeeds.

- [ ] **Step 7: Commit documentation and final verification**

```bash
git add README.md docs dlc_mcp tests
git commit -m "docs: document live-first DLC MCP source modes

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Self-Review Notes

Spec coverage:

- Live-first dynamic tools: Tasks 1-4 cover source semantics, partition profile, task runs, and live service foundation.
- Registry retained for tables/tasks/data sources: Task 1 source classification preserves registry behavior; later tasks do not remove registry sync.
- Patrol snapshots: Tasks 5-8 add schema, service, CLI, and report routing.
- Governance inventory/report migration: Tasks 7 and 9 move report and inventory defaults to patrol snapshots.
- Failure semantics: Tasks 3 and 4 add `partial_live` and `check_failed` structured errors; Task 6 records patrol errors.
- Legacy cache explicit-only: Tasks 1, 2, 4, 7, and 9 route `source=legacy_cache` separately.
- Documentation and regression: Task 10 covers docs and full tests.

No placeholder sections remain. Function names used by later tasks are introduced by earlier tasks. The plan intentionally starts with the stale partition failure because it is the highest-risk known bug and provides an early working improvement before broader patrol migration.
