# Asset Patrol Orchestrator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the existing patrol component so daily core, monthly full, and manual asset patrols produce fresh cache/live evidence reports without duplicating orchestration code.

**Architecture:** Keep `dlc_mcp.patrol.PatrolService` as the public entry point and refactor its internals into scope resolution, evidence collection, result normalization, and persistence helpers. Stable asset facts come from `AssetStore`; dynamic task/quality/run evidence is collected through live-capable services and persisted only in patrol snapshots/findings/errors. Extend the CLI and MCP report rendering around the existing patrol tables instead of creating a parallel framework.

**Tech Stack:** Python 3 stdlib, SQLite via `sqlite3`, existing `AssetStore`, existing `LiveWeData`, existing MCP markdown formatters, `unittest`/pytest-style tests run through `python3 -m unittest discover -s tests -v`, Node package checks via `node --check` and `npm pack --dry-run`.

## Global Constraints

- Reuse existing `PatrolService`; do not create a separate parallel patrol framework.
- Stable facts use cache/registry: metadata, columns, lineage, data source, core decision.
- Dynamic evidence uses live-only: related tasks, task details, upstream/downstream task dependencies, quality status, production status, production risk, task runs.
- Live-only evidence may be stored in patrol snapshots/findings/errors, but must not update long-term asset fact cache tables.
- Preserve `daily_p0` compatibility.
- Add `daily_core`, `monthly_full`, and `manual` patrol scopes.
- Keep missing data separate from live/API failures: `missing` means query succeeded with no data; `live_failed` means query failed; `not_checked` means scope/policy skipped it.
- Prefer small helper methods in `dlc_mcp/patrol.py`; split files only if the implementation becomes too large.
- Every code change must have a focused test.
- Commit messages must end with `Co-Authored-By: Claude <noreply@anthropic.com>`.

---

## File Structure

- Modify: `dlc_mcp/asset_patrol.py`
  - Extend CLI scope choices and optional filters.
  - Route all scopes through `PatrolService.run(...)`.
- Modify: `dlc_mcp/patrol.py`
  - Keep `PatrolService` public.
  - Add `run(...)`, `run_daily_core(...)`, `run_monthly_full(...)`, `run_manual(...)`.
  - Add scope candidate helpers.
  - Replace partition-only `_check_table()` with cache/live evidence collection and normalization while retaining partition checks as one optional evidence source if existing tests require it.
- Modify: `dlc_mcp/assets.py`
  - Add focused query helpers only if existing methods are insufficient for candidate selection or patrol report aggregation.
  - Prefer existing `AssetStore` methods before adding new ones.
- Modify: `dlc_mcp/mcp.py`
  - Extend patrol snapshot markdown rendering to show new summary/source-policy/finding sections.
- Modify: `tests/test_patrol.py`
  - Add CLI scope/filter parsing tests.
  - Add scope candidate tests.
  - Add patrol check tests for cache/live evidence, missing findings, live errors, monthly full, manual.
- Modify: `tests/test_mcp.py`
  - Add report rendering assertions for new patrol snapshot structure.
- Modify: `README.md`
  - Document daily core, monthly full, and manual patrol command examples if CLI behavior changes user-facing usage.

---

### Task 1: Extend patrol CLI scopes and route through one service method

**Files:**
- Modify: `dlc_mcp/asset_patrol.py:11-45`
- Test: `tests/test_patrol.py:8-32`

**Interfaces:**
- Consumes: existing `PatrolService.run_daily_p0(instance_date, ...)`.
- Produces: `PatrolService.run(scope: str, instance_date: str, **options) -> dict` call site from CLI.

- [ ] **Step 1: Write failing CLI parsing test**

Add this test below `test_asset_patrol_parse_args` in `tests/test_patrol.py`:

```python
def test_asset_patrol_parse_args_new_scopes_and_filters():
    args = parse_args(
        [
            "--scope", "monthly_full",
            "--instance-date", "2026-07-16",
            "--limit", "100",
            "--batch-size", "25",
            "--offset", "50",
            "--table", "ads_360_fin_income_cost_1d_di",
            "--layer", "ads",
            "--owner", "tencent",
            "--core-level", "P1",
        ]
    )

    assert args.scope == "monthly_full"
    assert args.instance_date == "2026-07-16"
    assert args.limit == 100
    assert args.batch_size == 25
    assert args.offset == 50
    assert args.table == "ads_360_fin_income_cost_1d_di"
    assert args.layer == "ads"
    assert args.owner == "tencent"
    assert args.core_level == "P1"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python3 -m unittest tests.test_patrol -v
```

Expected: FAIL because `monthly_full` is not an allowed `--scope` and the new filter arguments do not exist.

- [ ] **Step 3: Extend `parse_args`**

In `dlc_mcp/asset_patrol.py`, replace the `--scope` argument and add filter arguments:

```python
    parser.add_argument(
        "--scope",
        default="daily_p0",
        choices=["daily_p0", "daily_core", "monthly_full", "manual"],
        help="Patrol scope to run",
    )
    parser.add_argument("--batch-size", type=int, default=0, help="Maximum assets per batch for full patrols")
    parser.add_argument("--offset", type=int, default=0, help="Offset into the selected patrol scope")
    parser.add_argument("--table", default="", help="Single table name for manual patrol")
    parser.add_argument("--layer", default="", help="Layer filter for manual or full patrol")
    parser.add_argument("--owner", default="", help="Owner filter for manual or full patrol")
    parser.add_argument("--core-level", default="", help="Core level filter for core/manual patrol")
```

- [ ] **Step 4: Add a unified service call fallback**

In `dlc_mcp/asset_patrol.py`, replace the `if args.scope == "daily_p0"` block with:

```python
    result = service.run(
        args.scope,
        args.instance_date,
        limit=args.limit,
        batch_size=args.batch_size,
        offset=args.offset,
        table=args.table,
        layer=args.layer,
        owner=args.owner,
        core_level=args.core_level,
        concurrency=args.concurrency,
        table_timeout_seconds=args.table_timeout_seconds,
        retry=args.retry,
        retry_backoff_seconds=args.retry_backoff_seconds,
        api_delay_seconds=args.api_delay_seconds,
        failure_threshold=args.failure_threshold,
    )
```

- [ ] **Step 5: Add temporary compatibility method in `PatrolService`**

In `dlc_mcp/patrol.py`, add this method near the top of `PatrolService`:

```python
    def run(self, scope, instance_date, **options):
        if scope in {"daily_p0", "daily_core"}:
            return self.run_daily_p0(
                instance_date,
                limit=options.get("limit", 50),
                concurrency=options.get("concurrency", 3),
                table_timeout_seconds=options.get("table_timeout_seconds", 120),
                retry=options.get("retry", 2),
                retry_backoff_seconds=options.get("retry_backoff_seconds", 2),
                api_delay_seconds=options.get("api_delay_seconds", 0.2),
                failure_threshold=options.get("failure_threshold", 0.3),
            )
        raise SystemExit(f"unsupported scope: {scope}")
```

This keeps CLI tests passing before the later scope implementation tasks.

- [ ] **Step 6: Run focused tests**

Run:

```bash
python3 -m unittest tests.test_patrol -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add dlc_mcp/asset_patrol.py dlc_mcp/patrol.py tests/test_patrol.py
git commit -m "feat: extend patrol CLI scopes" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: Add scope resolution for daily core, monthly full, and manual patrols

**Files:**
- Modify: `dlc_mcp/patrol.py`
- Test: `tests/test_patrol.py`

**Interfaces:**
- Consumes: `AssetStore._all(sql: str, params: tuple) -> list[sqlite3.Row]` existing helper.
- Produces: `PatrolService._scope_candidates(scope: str, limit: int, offset: int = 0, table: str = "", layer: str = "", owner: str = "", core_level: str = "") -> list[dict]`.

- [ ] **Step 1: Write failing scope candidate tests**

Add these tests to `tests/test_patrol.py`:

```python
def test_patrol_scope_candidates_monthly_full_uses_all_tables_with_filters():
    store = AssetStore(sqlite3.connect(":memory:"))
    store.init_schema()
    store.upsert_table({"name": "ods_a", "layer": "ods", "owner": "data", "database": "dw"})
    store.upsert_table({"name": "ads_b", "layer": "ads", "owner": "tencent", "database": "dw"})
    store.upsert_table({"name": "ads_c", "layer": "ads", "owner": "other", "database": "dw"})

    service = PatrolService(store, PatrolLive(store))
    candidates = service._scope_candidates("monthly_full", limit=10, layer="ads", owner="tencent")

    assert [item["name"] for item in candidates] == ["ads_b"]


def test_patrol_scope_candidates_manual_accepts_single_table():
    store = AssetStore(sqlite3.connect(":memory:"))
    store.init_schema()
    store.upsert_table({"name": "ads_360_fin_income_cost_1d_di", "layer": "ads", "owner": "tencent", "database": "dw"})
    store.upsert_table({"name": "ads_other", "layer": "ads", "owner": "tencent", "database": "dw"})

    service = PatrolService(store, PatrolLive(store))
    candidates = service._scope_candidates("manual", limit=10, table="ads_360_fin_income_cost_1d_di")

    assert [item["name"] for item in candidates] == ["ads_360_fin_income_cost_1d_di"]
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
python3 -m unittest tests.test_patrol -v
```

Expected: FAIL because `_scope_candidates` does not exist.

- [ ] **Step 3: Implement `_scope_candidates`**

Add this method to `PatrolService`:

```python
    def _scope_candidates(self, scope, limit=50, offset=0, table="", layer="", owner="", core_level=""):
        if scope == "daily_p0":
            return self._daily_p0_candidates(limit)
        if scope == "daily_core":
            return self._daily_core_candidates(limit, offset=offset, layer=layer, owner=owner, core_level=core_level)
        if scope == "monthly_full":
            return self._monthly_full_candidates(limit, offset=offset, layer=layer, owner=owner)
        if scope == "manual":
            return self._manual_candidates(limit, offset=offset, table=table, layer=layer, owner=owner, core_level=core_level)
        raise ValueError(f"unsupported scope: {scope}")
```

- [ ] **Step 4: Implement monthly and manual candidate helpers**

Add these methods to `PatrolService`:

```python
    def _monthly_full_candidates(self, limit, offset=0, layer="", owner=""):
        where = []
        params = []
        if layer:
            where.append("layer = ?")
            params.append(layer)
        if owner:
            where.append("owner = ?")
            params.append(owner)
        sql = "select name, layer, owner, database_name from tables"
        if where:
            sql += " where " + " and ".join(where)
        sql += " order by layer, name limit ? offset ?"
        params.extend([int(limit or 100), int(offset or 0)])
        return [dict(row) for row in self.store._all(sql, tuple(params))]

    def _manual_candidates(self, limit, offset=0, table="", layer="", owner="", core_level=""):
        where = []
        params = []
        if table:
            where.append("name = ?")
            params.append(table)
        if layer:
            where.append("layer = ?")
            params.append(layer)
        if owner:
            where.append("owner = ?")
            params.append(owner)
        sql = "select name, layer, owner, database_name from tables"
        if where:
            sql += " where " + " and ".join(where)
        sql += " order by layer, name limit ? offset ?"
        params.extend([int(limit or 50), int(offset or 0)])
        return [dict(row) for row in self.store._all(sql, tuple(params))]
```

`core_level` is accepted now for interface stability; a later task wires core-level filtering through value profile/expert labels.

- [ ] **Step 5: Implement daily core candidate helper**

Add this conservative first version:

```python
    def _daily_core_candidates(self, limit, offset=0, layer="", owner="", core_level=""):
        where = ["layer in ('ods', 'dim', 'dwd', 'dws', 'mid', 'ads')"]
        params = []
        if layer:
            where.append("layer = ?")
            params.append(layer)
        if owner:
            where.append("owner = ?")
            params.append(owner)
        sql = """
            select name, layer, owner, database_name
            from tables
            where {where_clause}
            order by case when layer in ('ads', 'dws', 'dwd') then 0 else 1 end, name
            limit ? offset ?
        """.format(where_clause=" and ".join(where))
        params.extend([int(limit or 50), int(offset or 0)])
        return [dict(row) for row in self.store._all(sql, tuple(params))]
```

- [ ] **Step 6: Update `run` to use scope candidates**

Replace the temporary Task 1 `run` body with:

```python
    def run(self, scope, instance_date, **options):
        if scope == "daily_p0":
            return self.run_daily_p0(
                instance_date,
                limit=options.get("limit", 50),
                concurrency=options.get("concurrency", 3),
                table_timeout_seconds=options.get("table_timeout_seconds", 120),
                retry=options.get("retry", 2),
                retry_backoff_seconds=options.get("retry_backoff_seconds", 2),
                api_delay_seconds=options.get("api_delay_seconds", 0.2),
                failure_threshold=options.get("failure_threshold", 0.3),
            )
        if scope in {"daily_core", "monthly_full", "manual"}:
            return self._run_scope(scope, instance_date, **options)
        raise SystemExit(f"unsupported scope: {scope}")
```

Add `_run_scope` by copying the current `run_daily_p0` orchestration and replacing candidate selection/run_id/scope strings:

```python
    def _run_scope(self, scope, instance_date, **options):
        limit = options.get("limit", 50)
        run_id = f"{instance_date}_{scope}"
        candidates = self._scope_candidates(
            scope,
            limit=limit,
            offset=options.get("offset", 0),
            table=options.get("table", ""),
            layer=options.get("layer", ""),
            owner=options.get("owner", ""),
            core_level=options.get("core_level", ""),
        )
        return self._run_candidates(
            run_id,
            instance_date,
            scope,
            candidates,
            limit=limit,
            concurrency=options.get("concurrency", 3),
            table_timeout_seconds=options.get("table_timeout_seconds", 120),
            retry=options.get("retry", 2),
            retry_backoff_seconds=options.get("retry_backoff_seconds", 2),
            api_delay_seconds=options.get("api_delay_seconds", 0.2),
            failure_threshold=options.get("failure_threshold", 0.3),
        )
```

- [ ] **Step 7: Extract current run loop into `_run_candidates`**

Move the body of `run_daily_p0` into a new helper:

```python
    def _run_candidates(
        self,
        run_id,
        instance_date,
        scope,
        candidates,
        limit=50,
        concurrency=3,
        table_timeout_seconds=120,
        retry=2,
        retry_backoff_seconds=2,
        api_delay_seconds=0.2,
        failure_threshold=0.3,
    ):
        # use the existing run_daily_p0 implementation body here, replacing:
        # - run_id assignment with the parameter
        # - candidates assignment with the parameter
        # - hard-coded "daily_p0" metric dimensions with scope
        # - create_patrol_run scope with scope
```

Then make `run_daily_p0` call `_run_candidates`:

```python
    def run_daily_p0(self, instance_date, limit=50, concurrency=3, table_timeout_seconds=120, retry=2, retry_backoff_seconds=2, api_delay_seconds=0.2, failure_threshold=0.3):
        run_id = f"{instance_date}_daily_p0"
        candidates = self._daily_p0_candidates(limit)
        return self._run_candidates(
            run_id,
            instance_date,
            "daily_p0",
            candidates,
            limit=limit,
            concurrency=concurrency,
            table_timeout_seconds=table_timeout_seconds,
            retry=retry,
            retry_backoff_seconds=retry_backoff_seconds,
            api_delay_seconds=api_delay_seconds,
            failure_threshold=failure_threshold,
        )
```

- [ ] **Step 8: Run focused tests**

Run:

```bash
python3 -m unittest tests.test_patrol -v
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add dlc_mcp/patrol.py tests/test_patrol.py
git commit -m "feat: add patrol scope resolution" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: Collect cache/live evidence per table without writing live facts to registry

**Files:**
- Modify: `dlc_mcp/patrol.py`
- Test: `tests/test_patrol.py`

**Interfaces:**
- Consumes: `AssetStore.get_table_detail(table_name: str = "", table_guid: str = "") -> dict`, `AssetStore.get_table_profile(table_name: str) -> dict`, `AssetStore.get_table_lineage(table_name: str) -> dict`, `AssetStore.get_quality_status(table_name: str) -> dict`, `AssetStore.get_table_tasks(table_name: str) -> dict`, `AssetStore.get_table_production_status(table_name: str, instance_date: str) -> dict` if available in current code.
- Produces: `PatrolService._collect_table_evidence(table: dict, instance_date: str) -> dict` with `source_policy`, `cached`, `live`, `errors`.

- [ ] **Step 1: Add fake live service for patrol evidence tests**

Add this class to `tests/test_patrol.py`:

```python
class PatrolEvidenceLive:
    def __init__(self, tasks=None, quality=None, production=None, fail_quality=False):
        self.tasks = tasks if tasks is not None else {"tasks": []}
        self.quality = quality if quality is not None else {"has_monitoring": False, "rule_count": 0, "latest_status": "missing"}
        self.production = production if production is not None else {"summary_status": "not_run", "producer_task_count": 0, "runs": []}
        self.fail_quality = fail_quality

    def get_table_tasks_live(self, table_name):
        return self.tasks

    def get_quality_status_live(self, table_name):
        if self.fail_quality:
            raise RuntimeError("ListQualityRules failed: InternalError temporary unavailable")
        return self.quality

    def get_table_production_status_live(self, table_name, instance_date):
        return self.production
```

- [ ] **Step 2: Write failing evidence collection test**

Add this test:

```python
def test_patrol_collects_cached_and_live_only_evidence_without_registry_writes():
    store = AssetStore(sqlite3.connect(":memory:"))
    store.init_schema()
    store.upsert_table({
        "name": "ads_360_fin_income_cost_1d_di",
        "layer": "ads",
        "domain": "finance",
        "owner": "tencent",
        "database": "byai_bigdata",
        "data_source_id": "DLC",
        "description": "消耗型产品确认收入和成本汇总表",
    })
    store.upsert_column("ads_360_fin_income_cost_1d_di", "dt", "string", "分区", 1)
    store.upsert_lineage("dws_360_fin_job_line_1d_di", "ads_360_fin_income_cost_1d_di", "task_lineage")
    store.upsert_lineage("ads_360_fin_income_cost_1d_di", "ads_360_fin_income_cost_1d_df", "task_lineage")

    live = PatrolEvidenceLive()
    service = PatrolService(store, live)
    evidence = service._collect_table_evidence(
        {"name": "ads_360_fin_income_cost_1d_di", "layer": "ads", "owner": "tencent", "database_name": "byai_bigdata"},
        "2026-07-16",
    )

    assert evidence["source_policy"] == {
        "metadata": "cache",
        "columns": "cache",
        "lineage": "cache",
        "tasks": "live_only",
        "quality": "live_only",
        "runs": "live_only",
    }
    assert evidence["cached"]["metadata"]["status"] == "complete"
    assert evidence["cached"]["columns"]["count"] == 1
    assert evidence["cached"]["lineage"]["upstream_count"] == 1
    assert evidence["cached"]["lineage"]["downstream_count"] == 1
    assert evidence["live"]["tasks"]["status"] == "missing"
    assert evidence["live"]["quality"]["status"] == "missing"
    assert evidence["live"]["runs"]["status"] == "missing"
    assert evidence["errors"] == []
    assert store.get_table_tasks("ads_360_fin_income_cost_1d_di")["tasks"] == []
```

- [ ] **Step 3: Run test to verify it fails**

Run:

```bash
python3 -m unittest tests.test_patrol -v
```

Expected: FAIL because `_collect_table_evidence` does not exist.

- [ ] **Step 4: Implement live call wrappers**

Add these helper methods to `PatrolService` so tests can use fake live methods and production can later use existing services:

```python
    def _live_table_tasks(self, table_name):
        if hasattr(self.live, "get_table_tasks_live"):
            return self.live.get_table_tasks_live(table_name)
        return self.store.get_table_tasks(table_name)

    def _live_quality_status(self, table_name):
        if hasattr(self.live, "get_quality_status_live"):
            return self.live.get_quality_status_live(table_name)
        return self.store.get_quality_status(table_name)

    def _live_production_status(self, table_name, instance_date):
        if hasattr(self.live, "get_table_production_status_live"):
            return self.live.get_table_production_status_live(table_name, instance_date)
        return self.store.get_table_production_status(table_name, instance_date)
```

These wrappers preserve reuse while making live-only behavior injectable in tests.

- [ ] **Step 5: Implement `_collect_table_evidence`**

Add this method:

```python
    def _collect_table_evidence(self, table, instance_date):
        table_name = table["name"]
        detail = self.store.get_table_detail(table_name=table_name)
        profile = self.store.get_table_profile(table_name)
        lineage = self.store.get_table_lineage(table_name)
        errors = []

        columns = detail.get("columns", []) if not detail.get("error") else []
        table_detail = detail.get("table", {}) if not detail.get("error") else {}
        upstream = lineage.get("upstream", []) if not lineage.get("error") else []
        downstream = lineage.get("downstream", []) if not lineage.get("error") else []

        live_tasks = self._safe_live_call("tasks", "get_table_tasks", lambda: self._live_table_tasks(table_name), errors)
        live_quality = self._safe_live_call("quality", "get_quality_status", lambda: self._live_quality_status(table_name), errors)
        live_runs = self._safe_live_call("runs", "get_table_production_status", lambda: self._live_production_status(table_name, instance_date), errors)

        return {
            "source_policy": {
                "metadata": "cache",
                "columns": "cache",
                "lineage": "cache",
                "tasks": "live_only",
                "quality": "live_only",
                "runs": "live_only",
            },
            "cached": {
                "metadata": {
                    "status": "missing" if detail.get("error") else "complete",
                    "table": table_detail,
                    "core_level": profile.get("value", {}).get("core_level") or profile.get("core_level", ""),
                },
                "columns": {"status": "missing" if not columns else "complete", "count": len(columns)},
                "lineage": {
                    "status": "missing" if not upstream and not downstream else "complete",
                    "upstream_count": len(upstream),
                    "downstream_count": len(downstream),
                },
            },
            "live": {
                "tasks": self._normalize_live_tasks(live_tasks),
                "quality": self._normalize_live_quality(live_quality),
                "runs": self._normalize_live_runs(live_runs),
            },
            "errors": errors,
        }
```

- [ ] **Step 6: Implement `_safe_live_call` and normalizers**

Add these methods:

```python
    def _safe_live_call(self, module, tool, fn, errors):
        try:
            return fn()
        except Exception as exc:
            errors.append(
                {
                    "module": module,
                    "api_action": tool,
                    "error_code": exc.__class__.__name__,
                    "error_message": str(exc),
                    "retryable": "InternalError" in str(exc) or "timeout" in str(exc).lower(),
                }
            )
            return {"error": "live_failed", "message": str(exc)}

    def _normalize_live_tasks(self, data):
        if data.get("error") == "live_failed":
            return {"status": "live_failed", "producer_count": 0, "consumer_count": 0, "raw": data}
        tasks = data.get("tasks") or data.get("results") or []
        producer_count = len([item for item in tasks if item.get("direction") in {"output", "producer", "produces"}])
        consumer_count = len([item for item in tasks if item.get("direction") in {"input", "consumer", "consumes"}])
        return {
            "status": "complete" if tasks else "missing",
            "producer_count": producer_count,
            "consumer_count": consumer_count,
            "count": len(tasks),
            "raw": data,
        }

    def _normalize_live_quality(self, data):
        if data.get("error") == "live_failed":
            return {"status": "live_failed", "rule_count": 0, "raw": data}
        rule_count = int(data.get("rule_count") or len(data.get("rules") or []))
        return {"status": "complete" if rule_count else "missing", "rule_count": rule_count, "raw": data}

    def _normalize_live_runs(self, data):
        if data.get("error") == "live_failed":
            return {"status": "live_failed", "run_count": 0, "raw": data}
        runs = data.get("runs") or data.get("instances") or []
        summary_status = data.get("summary_status") or data.get("status") or ""
        if summary_status in {"failed", "timeout"}:
            status = summary_status
        elif runs:
            status = "complete"
        else:
            status = "missing"
        return {"status": status, "run_count": len(runs), "summary_status": summary_status, "raw": data}
```

- [ ] **Step 7: Run focused tests**

Run:

```bash
python3 -m unittest tests.test_patrol -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add dlc_mcp/patrol.py tests/test_patrol.py
git commit -m "feat: collect patrol cache and live evidence" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: Normalize evidence into findings and enriched snapshots

**Files:**
- Modify: `dlc_mcp/patrol.py`
- Test: `tests/test_patrol.py`

**Interfaces:**
- Consumes: `_collect_table_evidence(table: dict, instance_date: str) -> dict` from Task 3.
- Produces: `_normalize_table_result(table: dict, evidence: dict) -> dict` returning keys `asset_name`, `table`, `status`, `snapshot`, `findings`, `errors`, `timed_out`.

- [ ] **Step 1: Write failing findings test**

Add this test:

```python
def test_patrol_normalizes_missing_live_evidence_into_findings():
    store = AssetStore(sqlite3.connect(":memory:"))
    store.init_schema()
    table = {"name": "ads_360_fin_income_cost_1d_di", "layer": "ads", "owner": "tencent", "database_name": "dw"}
    evidence = {
        "source_policy": {"metadata": "cache", "columns": "cache", "lineage": "cache", "tasks": "live_only", "quality": "live_only", "runs": "live_only"},
        "cached": {
            "metadata": {"status": "complete", "core_level": "P2"},
            "columns": {"status": "complete", "count": 36},
            "lineage": {"status": "complete", "upstream_count": 26, "downstream_count": 13},
        },
        "live": {
            "tasks": {"status": "missing", "producer_count": 0, "consumer_count": 0},
            "quality": {"status": "missing", "rule_count": 0},
            "runs": {"status": "missing", "run_count": 0, "summary_status": "not_run"},
        },
        "errors": [],
    }

    result = PatrolService(store, PatrolLive(store))._normalize_table_result(table, evidence)

    assert result["status"] == "p1"
    assert result["snapshot"]["source_policy"]["tasks"] == "live_only"
    assert [finding["issue_type"] for finding in result["findings"]] == [
        "missing_producer_task",
        "missing_quality_rules",
        "missing_task_runs",
    ]
    assert all(finding["severity"] == "P1" for finding in result["findings"])
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python3 -m unittest tests.test_patrol -v
```

Expected: FAIL because `_normalize_table_result` does not exist.

- [ ] **Step 3: Implement finding helper**

Add this method:

```python
    def _finding(self, issue_type, severity, source, evidence, owner_bucket="warehouse_owner", suggested_action=""):
        return {
            "issue_type": issue_type,
            "severity": severity,
            "source": source,
            "evidence": evidence,
            "owner_bucket": owner_bucket,
            "suggested_action": suggested_action,
        }
```

- [ ] **Step 4: Implement `_normalize_table_result`**

Add this method:

```python
    def _normalize_table_result(self, table, evidence):
        findings = []
        cached = evidence.get("cached", {})
        live = evidence.get("live", {})

        if cached.get("metadata", {}).get("status") == "missing":
            findings.append(self._finding("missing_table_metadata", "P0", "cache", cached.get("metadata", {}), suggested_action="Refresh table metadata cache."))
        if cached.get("columns", {}).get("status") == "missing":
            findings.append(self._finding("missing_columns", "P0", "cache", cached.get("columns", {}), suggested_action="Refresh table columns cache."))
        if cached.get("lineage", {}).get("status") == "missing":
            findings.append(self._finding("missing_lineage", "P1", "cache", cached.get("lineage", {}), suggested_action="Refresh table lineage cache."))

        task_status = live.get("tasks", {}).get("status")
        if task_status == "missing":
            findings.append(self._finding("missing_producer_task", "P1", "live", live.get("tasks", {}), suggested_action="Check ListTasks inputs/outputs or SQL parsing for this table."))
        quality_status = live.get("quality", {}).get("status")
        if quality_status == "missing":
            findings.append(self._finding("missing_quality_rules", "P1", "live", live.get("quality", {}), suggested_action="Confirm or add minimum quality rules for this core table."))
        run_status = live.get("runs", {}).get("status")
        if run_status == "missing":
            findings.append(self._finding("missing_task_runs", "P1", "live", live.get("runs", {}), suggested_action="Check producer task mapping before validating run instances."))
        if run_status in {"failed", "timeout"}:
            findings.append(self._finding("task_run_failed", "P0", "live", live.get("runs", {}), suggested_action="Inspect failed producer task run."))

        if evidence.get("errors"):
            status = "live_failed"
        elif any(item["severity"] == "P0" for item in findings):
            status = "p0"
        elif findings:
            status = "p1"
        else:
            status = "healthy"

        return {
            "asset_name": table["name"],
            "table": table,
            "status": status,
            "snapshot": {
                "source_policy": evidence.get("source_policy", {}),
                "cached": cached,
                "live": live,
                "coverage_status": status,
            },
            "findings": findings,
            "errors": evidence.get("errors", []),
            "timed_out": False,
        }
```

- [ ] **Step 5: Update `_check_table` to use evidence collection while preserving retry behavior**

Replace the success path in `_check_table` with:

```python
            evidence = self._collect_table_evidence(table, table.get("instance_date", ""))
            result = self._normalize_table_result(table, evidence)
            if not result.get("errors"):
                return result
            retryable = any(error.get("retryable") for error in result.get("errors", []))
```

If `instance_date` is not present in `table`, pass it in from `_run_candidates` by copying each candidate before submit:

```python
                        {**table, "instance_date": instance_date},
```

- [ ] **Step 6: Update `_persist_table_result` to write findings**

Inside `_persist_table_result`, after error writes and before/after snapshot write, add:

```python
        for finding in item.get("findings", []):
            self.store.insert_patrol_finding(
                {
                    "run_id": run_id,
                    "asset_name": table["name"],
                    "issue_type": finding.get("issue_type", ""),
                    "severity": finding.get("severity", ""),
                    "evidence": finding.get("evidence") or {},
                    "owner_bucket": finding.get("owner_bucket", ""),
                    "suggested_action": finding.get("suggested_action", ""),
                }
            )
```

- [ ] **Step 7: Run focused tests**

Run:

```bash
python3 -m unittest tests.test_patrol -v
```

Expected: PASS. If old partition-specific tests fail, adjust their expectations to check the new `coverage_status` and keep timeout/error assertions intact.

- [ ] **Step 8: Commit**

```bash
git add dlc_mcp/patrol.py tests/test_patrol.py
git commit -m "feat: classify patrol evidence findings" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: Add enriched run summary metrics for patrol reports

**Files:**
- Modify: `dlc_mcp/patrol.py`
- Test: `tests/test_patrol.py`

**Interfaces:**
- Consumes: normalized item statuses from Task 4: `healthy`, `p0`, `p1`, `live_failed`, `check_failed`.
- Produces: `summary_json` fields `live_success_count`, `live_partial_count`, `live_failed_count`, `p0_count`, `p1_count`, `p2_count`.

- [ ] **Step 1: Write failing summary test**

Add this test:

```python
def test_patrol_summary_counts_live_and_severity_buckets():
    store = AssetStore(sqlite3.connect(":memory:"))
    store.init_schema()
    store.upsert_table({"name": "ads_missing", "layer": "ads", "owner": "tencent", "database": "dw"})
    store.upsert_column("ads_missing", "dt", "string", "", 1)

    result = PatrolService(store, PatrolEvidenceLive()).run(
        "daily_core",
        "2026-07-16",
        limit=1,
        concurrency=1,
        retry=0,
        api_delay_seconds=0,
    )

    assert result["live_success_count"] == 0
    assert result["live_partial_count"] == 1
    assert result["live_failed_count"] == 0
    assert result["p0_count"] == 0
    assert result["p1_count"] == 1
    assert result["p2_count"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python3 -m unittest tests.test_patrol -v
```

Expected: FAIL because the summary does not contain the new counts.

- [ ] **Step 3: Count statuses in `_run_candidates`**

In `_run_candidates`, initialize counters before the loop:

```python
        live_success_count = 0
        live_partial_count = 0
        live_failed_count = 0
        p0_count = 0
        p1_count = 0
        p2_count = 0
```

Inside the loop, after `item` is available:

```python
                status_value = item.get("status", "unknown")
                if status_value == "healthy":
                    live_success_count += 1
                elif status_value in {"p0", "p1", "p2"}:
                    live_partial_count += 1
                elif status_value in {"live_failed", "check_failed"}:
                    live_failed_count += 1
                if status_value == "p0":
                    p0_count += 1
                elif status_value == "p1":
                    p1_count += 1
                elif status_value == "p2":
                    p2_count += 1
```

Add these fields to `summary`:

```python
            "live_success_count": live_success_count,
            "live_partial_count": live_partial_count,
            "live_failed_count": live_failed_count,
            "p0_count": p0_count,
            "p1_count": p1_count,
            "p2_count": p2_count,
```

- [ ] **Step 4: Write metrics for new counts**

After existing metric inserts, add a loop:

```python
        for metric_name, metric_value in (
            ("live_success_count", live_success_count),
            ("live_partial_count", live_partial_count),
            ("live_failed_count", live_failed_count),
            ("p0_count", p0_count),
            ("p1_count", p1_count),
            ("p2_count", p2_count),
        ):
            self.store.insert_patrol_metric(
                {"run_id": run_id, "metric_name": metric_name, "metric_value": metric_value, "dimension": {"scope": scope}}
            )
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
python3 -m unittest tests.test_patrol -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add dlc_mcp/patrol.py tests/test_patrol.py
git commit -m "feat: summarize patrol live coverage" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: Render enriched patrol snapshot reports through MCP

**Files:**
- Modify: `dlc_mcp/mcp.py`
- Test: `tests/test_mcp.py`

**Interfaces:**
- Consumes: existing `AssetStore.get_patrol_report_data(run_id: str) -> dict`.
- Produces: Markdown containing sections for summary, source policy, coverage overview, findings, and live errors when `source=patrol_snapshot`.

- [ ] **Step 1: Write failing MCP rendering test**

Add this test near existing patrol snapshot tests in `tests/test_mcp.py`:

```python
def test_daily_report_markdown_renders_enriched_patrol_snapshot():
    store = AssetStore(sqlite3.connect(":memory:"))
    store.init_schema()
    store.create_patrol_run("run-rich", "2026-07-16", "daily_core", {})
    store.upsert_patrol_asset_snapshot(
        {
            "run_id": "run-rich",
            "asset_name": "ads_360_fin_income_cost_1d_di",
            "asset_type": "table",
            "layer": "ads",
            "owner": "tencent",
            "core_level": "P2",
            "status": "p1",
            "snapshot": {
                "source_policy": {"metadata": "cache", "tasks": "live_only", "quality": "live_only", "runs": "live_only"},
                "cached": {"columns": {"count": 36}, "lineage": {"upstream_count": 26, "downstream_count": 13}},
                "live": {"tasks": {"status": "missing"}, "quality": {"status": "missing"}, "runs": {"status": "missing"}},
                "coverage_status": "p1",
            },
        }
    )
    store.insert_patrol_finding(
        {
            "run_id": "run-rich",
            "asset_name": "ads_360_fin_income_cost_1d_di",
            "issue_type": "missing_producer_task",
            "severity": "P1",
            "evidence": {"source": "live", "status": "missing"},
            "owner_bucket": "warehouse_owner",
            "suggested_action": "Check ListTasks inputs/outputs or SQL parsing for this table.",
        }
    )
    store.finish_patrol_run(
        "run-rich",
        "partial",
        {"checked_count": 1, "error_count": 0, "live_partial_count": 1, "p1_count": 1},
    )

    text = render_tool_result(
        "get_asset_governance_daily_report",
        store.get_patrol_report_data("run-rich"),
    )

    assert "数据来源与查询策略" in text
    assert "ads_360_fin_income_cost_1d_di" in text
    assert "missing_producer_task" in text
    assert "live_only" in text
```

If `tests/test_mcp.py` does not expose `render_tool_result`, use the existing helper in that file for rendering tool calls and adapt only the call setup, not the assertions.

- [ ] **Step 2: Run focused MCP test**

Run:

```bash
python3 -m unittest tests.test_mcp -v
```

Expected: FAIL because enriched sections are not rendered.

- [ ] **Step 3: Add patrol snapshot markdown helper**

In `dlc_mcp/mcp.py`, locate the patrol snapshot rendering branch for `get_asset_governance_daily_report`. Add or extend a helper like this:

```python
def _format_patrol_snapshot_report(data):
    run = data.get("run") or {}
    snapshots = data.get("snapshots") or []
    findings = data.get("findings") or []
    errors = data.get("errors") or []
    summary = _json_loads(run.get("summary_json", "{}"))
    lines = ["**查询元信息**", "", "- 数据来源：patrol_snapshot", "- 实时刷新：否", ""]
    lines.extend(["## 巡检摘要", ""])
    lines.append(f"- Run ID：`{run.get('run_id', '')}`")
    lines.append(f"- Scope：`{run.get('scope', '')}`")
    lines.append(f"- 状态：**{run.get('status', '')}**")
    lines.append(f"- 已检查：{summary.get('checked_count', run.get('checked_count', 0))}")
    lines.append(f"- live 完整成功：{summary.get('live_success_count', 0)}")
    lines.append(f"- live 部分缺失：{summary.get('live_partial_count', 0)}")
    lines.append(f"- live 失败：{summary.get('live_failed_count', 0)}")
    lines.append(f"- P0：{summary.get('p0_count', 0)}")
    lines.append(f"- P1：{summary.get('p1_count', 0)}")
    lines.extend(["", "## 数据来源与查询策略", "", "| 信息 | 查询方式 |", "| --- | --- |"])
    first_snapshot = _json_loads(snapshots[0].get("snapshot_json", "{}")) if snapshots else {}
    for key, value in (first_snapshot.get("source_policy") or {}).items():
        lines.append(f"| {key} | {value} |")
    lines.extend(["", "## 覆盖总览", "", "| 表名 | 层级 | Owner | 状态 |", "| --- | --- | --- | --- |"])
    for row in snapshots[:50]:
        lines.append(f"| `{row.get('asset_name', '')}` | {row.get('layer', '')} | {row.get('owner', '')} | {row.get('status', '')} |")
    lines.extend(["", "## 问题清单", "", "| 表名 | 严重级别 | 问题 | 建议 |", "| --- | --- | --- | --- |"])
    for row in findings[:100]:
        lines.append(f"| `{row.get('asset_name', '')}` | {row.get('severity', '')} | {row.get('issue_type', '')} | {row.get('suggested_action', '')} |")
    if errors:
        lines.extend(["", "## live 查询失败清单", "", "| 表名 | 模块 | 错误 |", "| --- | --- | --- |"])
        for row in errors[:100]:
            lines.append(f"| `{row.get('asset_name', '')}` | {row.get('module', '')} | {row.get('error_message', '')} |")
    return "\n".join(lines)
```

Use the project's existing JSON helper if one already exists. If not, add:

```python
def _json_loads(value):
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value or "{}")
    except Exception:
        return {}
```

- [ ] **Step 4: Route patrol snapshot reports through helper**

In the rendering branch where `data.get("source") == Source.PATROL_SNAPSHOT` or where patrol report data is detected by keys `run/snapshots/findings`, return `_format_patrol_snapshot_report(data)`.

- [ ] **Step 5: Run MCP tests**

Run:

```bash
python3 -m unittest tests.test_mcp -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add dlc_mcp/mcp.py tests/test_mcp.py
git commit -m "feat: render enriched patrol snapshots" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: Document patrol modes and run full verification

**Files:**
- Modify: `README.md`
- Test: full verification commands

**Interfaces:**
- Consumes: completed CLI scopes from Task 1 and `PatrolService.run(...)` from Task 2.
- Produces: user-facing command examples for daily core, monthly full, and manual patrol.

- [ ] **Step 1: Add README section**

In `README.md`, add a section near existing sync/governance operation docs:

```markdown
## Asset patrol modes

The asset patrol command reuses the existing server registry for stable facts and live-refreshes dynamic evidence during the patrol run.

Stable cache/registry evidence:

- table metadata
- columns
- table lineage
- data source
- core table decision

Live-only evidence, written only to patrol snapshots/findings/errors:

- related tasks and producer task coverage
- task details and task dependencies
- quality status
- production status and task runs

Daily core patrol:

```bash
python3 -m dlc_mcp.asset_patrol --scope daily_core --instance-date 2026-07-16 --limit 100
```

Monthly full patrol, batched:

```bash
python3 -m dlc_mcp.asset_patrol --scope monthly_full --instance-date 2026-07-16 --limit 500 --batch-size 500 --offset 0
```

Manual table patrol:

```bash
python3 -m dlc_mcp.asset_patrol --scope manual --table ads_360_fin_income_cost_1d_di --instance-date 2026-07-16
```

`daily_p0` remains supported as a compatibility scope.
```

- [ ] **Step 2: Run full Python test suite**

Run:

```bash
python3 -m unittest discover -s tests -v
```

Expected: PASS.

- [ ] **Step 3: Run Node syntax check**

Run:

```bash
node --check bin/dlc-mcp.js
```

Expected: no output and exit code 0.

- [ ] **Step 4: Run package dry-run**

Run:

```bash
npm pack --dry-run
```

Expected: package contents print successfully and command exits 0.

- [ ] **Step 5: Check working tree and diff hygiene**

Run:

```bash
git diff --check
git status --short
```

Expected: `git diff --check` exits 0. `git status --short` shows only intended tracked changes plus any pre-existing untracked files the user asked to keep.

- [ ] **Step 6: Commit**

```bash
git add README.md
git commit -m "docs: document asset patrol modes" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Final Verification

After all tasks are complete, run:

```bash
python3 -m unittest discover -s tests -v
node --check bin/dlc-mcp.js
npm pack --dry-run
git status --short --branch
```

Expected:

- Python tests pass.
- Node syntax check passes.
- npm package dry-run passes.
- Branch contains only intended commits and no unresolved tracked changes.

## Self-Review Notes

- Spec coverage: Tasks cover CLI scopes, scope resolution, cache/live evidence, missing/live-failed separation, snapshot/finding/error persistence, report rendering, documentation, and verification.
- Placeholder scan: no placeholder tasks are left for implementers; each task has concrete test and implementation snippets.
- Type consistency: `PatrolService.run(scope, instance_date, **options)`, `_scope_candidates(...)`, `_collect_table_evidence(...)`, and `_normalize_table_result(...)` are introduced before use by later tasks.
