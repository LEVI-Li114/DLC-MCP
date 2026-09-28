# WeData Refresh and Feishu Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two-stage, explicitly confirmed workflows that refresh a WeData table through its supported upstream task DAG and then safely query and overwrite a named Feishu Docs, Bitable, or Sheets target.

**Architecture:** Keep `dlc_mcp/mcp.py` as the MCP boundary and add focused orchestration/domain modules beneath it. WeData, DLC, and Feishu vendor calls remain in connector classes; planners and executors consume normalized models and never format raw vendor payloads. Short-lived refresh and export plans live in an in-process operation store, so every remote side effect requires a prepare/confirm pair and plans expire with the process or their TTL.

**Tech Stack:** Python 3 standard library, existing `TencentCloudClient`, `LiveWeData`, `DLCQueryService`, SQLite `AssetStore` for read-only metadata, `urllib.request` for new HTTP connectors, `unittest`/`unittest.mock`, MCP JSON-RPC tool schemas, and existing shell/deployment documentation.

## Global Constraints

- Tencent Cloud AK/SK and Feishu `APP_SECRET` remain server-only environment values and never appear in MCP responses, tests, Git, or client configuration.
- WeData execution uses only an official Tencent Cloud API; SSH, shell, browser automation, console simulation, and direct client credentials are not execution paths.
- `Asia/Shanghai` is the fixed default business timezone; an omitted partition means the business-timezone calendar date minus one day.
- Only offline data-integration synchronization tasks and SQL/offline ETL tasks are executable in the first release; real-time, Shell/script, workflow, machine-learning, and unknown task types are plan-only.
- A target table with multiple producer tasks returns candidates and cannot be executed until the caller supplies `task_id`.
- Task input/output table mappings require real task-definition evidence; task names cannot infer table names.
- The dependency graph must detect cycles and incomplete dependencies before confirmation.
- Tasks in the same dependency level execute serially in stable task-id order.
- A failed task blocks only its dependent descendants; independent branches continue.
- The target task succeeding is sufficient to return the final refresh result; unrelated branches may remain running and must be reported.
- Default execution timeout is 1,800 seconds and callers may provide a bounded override; no automatic task retry is performed.
- Prepare operations are read-only; refresh execution and Feishu overwrite are separate explicit confirmations.
- Feishu writes default to overwrite and must first clear the complete tool-managed range; content outside that range is unchanged.
- Docs requires an existing native table block; Bitable requires an existing same-name data table; Sheets requires an existing same-name worksheet; none is auto-created.
- Feishu output contains only query column names as the header row and query data rows; no metadata is inserted into the target.
- DLC custom SQL is limited to one read-only `SELECT`/`WITH` statement using the existing validator.
- The first release does not promise cross-API transactions, automatic rollback, task retries, persistent operation plans, or cross-session confirmation.
- Every new Tencent Cloud action must be added to `TENCENT_CLOUD_API_CATALOG` in `dlc_mcp/assets.py` with an official source URL, description, and usage.
- Existing unrelated worktree changes (`crm_fxiaoke_tx_inventory.md` deletion and the untracked Spark SQL plan) must not be modified or included in feature commits.

---

## File Map

### New production files

- `dlc_mcp/operation_store.py` — thread-safe in-memory refresh/export plan records, TTL checks, one-time confirmation state, and context fingerprints.
- `dlc_mcp/refresh.py` — normalized refresh models, table-to-task resolution, dependency DAG construction, partition calculation, task-type support checks, and refresh orchestration.
- `dlc_mcp/wedata_execution.py` — official WeData trigger/status adapter and normalized task-instance polling; returns an explicit unsupported result when capability verification or configuration is absent.
- `dlc_mcp/query_orchestration.py` — safe target-table SQL construction, custom SQL validation, DLC pagination, result normalization, and bounded export previews.
- `dlc_mcp/feishu.py` — Feishu app-token connector, URL parsing, permission probes, target discovery, managed-range snapshots, and normalized API errors.
- `dlc_mcp/feishu_writers.py` — Docs/Bitable/Sheets clear-and-rewrite implementations, pagination/batching, schema replacement, verification, and partial-write accounting.

### Modified production files

- `dlc_mcp/mcp.py` — register four tools, validate arguments, create/confirm plans, and format structured workflow results without vendor-specific API logic.
- `dlc_mcp/server.py` — create shared operation services at process startup and pass them to request handling; preserve existing query-only behavior when write credentials are absent.
- `dlc_mcp/live.py` — expose normalized task-definition and upstream-relation reads needed by the refresh planner, with existing cache/import behavior preserved.
- `dlc_mcp/dlc_query.py` — add a reusable paginated-result helper while preserving `submit`/`result` compatibility and existing read-only validation.
- `dlc_mcp/tencentcloud.py` — add configurable request error normalization only if required by the verified trigger/status actions; preserve TC3 signing behavior.
- `dlc_mcp/assets.py` — catalog verified WeData trigger/status actions and any new DLC action; do not store secrets or transient operation plans.
- `deploy/env.example` — document refresh timeout, business timezone, operation TTL, verified WeData action names, Feishu app credentials, Feishu batch limits, and explicit capability flags.
- `README.md` — add the four tools, confirmation semantics, supported task/target types, and server-only credential requirements.
- `docs/architecture.md` — document orchestration, operation-store, WeData execution, and Feishu connector boundaries.
- `docs/server-mcp-wedata-flow.md` — add server configuration, capability verification, permissions, smoke tests, and failure behavior.

### New tests

- `tests/test_operation_store.py` — TTL, one-time confirmation, context mismatch, and process-local semantics.
- `tests/test_refresh.py` — producer resolution, candidate selection, DAG/topological levels, cycles, unsupported tasks, partitions, and failure isolation.
- `tests/test_wedata_execution.py` — verified-action payloads, status normalization, polling timeout, target-success early return, and unsupported capability behavior.
- `tests/test_query_orchestration.py` — default partition SQL, filters, custom SQL, pagination, statistics, and safety limits.
- `tests/test_feishu.py` — credential loading, URL/type validation, permission probes, managed-range snapshots, and missing-target errors.
- `tests/test_feishu_writers.py` — clear/rewrite behavior for all three target types, schema changes, batching, partial failures, and out-of-range preservation.
- `tests/test_workflow_tools.py` — MCP schemas, prepare/confirm transitions, confirmation barriers, error codes, and end-to-end mocked refresh/export flows.
- `tests/fixtures/wedata_capability_probe.json` — sanitized representative trigger/status responses and task-type mappings; no credential or tenant-sensitive data.

---

## Task 0: Verify provider capabilities and establish configuration contracts

**Files:**
- Create: `docs/superpowers/reports/2026-08-19-wedata-feishu-capability-report.md`
- Create: `tests/fixtures/wedata_capability_probe.json`
- Modify: `dlc_mcp/assets.py: TENCENT_CLOUD_API_CATALOG`
- Modify: `deploy/env.example`
- Test: `tests/test_tencentcloud.py` and `tests/test_deploy_scripts.py`

**Interfaces:**
- Produces `CapabilityReport` fields: `provider`, `action`, `verified`, `supported_task_types`, `request_shape`, `terminal_states`, `permission_requirements`, `limitations`, and `verified_at`.
- Produces environment contract names: `WEDATA_TRIGGER_ACTION`, `WEDATA_STATUS_ACTION`, `WEDATA_TRIGGER_CAPABILITY`, `WEDATA_REFRESH_TIMEOUT_SECONDS`, `WEDATA_REFRESH_POLL_SECONDS`, `DLC_MCP_BUSINESS_TIMEZONE`, `DLC_MCP_OPERATION_TTL_SECONDS`, `FEISHU_APP_ID`, `FEISHU_APP_SECRET`, `FEISHU_API_BASE`, `FEISHU_CAPABILITY_CHECK`, `FEISHU_BATCH_SIZE`, and `FEISHU_DOCS_MAX_ROWS`.

- [ ] **Step 1: Record the current API boundary and write a sanitized capability fixture**

  Use the existing `TencentCloudClient.call(action, payload)` contract. Capture only action names, field names, normalized status values, and permission/error codes in the fixture. Do not copy IDs, tokens, SQL, document URLs, or response data into the repository.

- [ ] **Step 2: Run the capability probe in the authorized server environment**

  Use the documented server environment and official APIs to verify task triggering, task-instance status polling, offline data-integration support, SQL/ETL support, partition parameter transport, terminal states, and account permissions. Verify Feishu app-token acquisition and read/write probes for Docs, Bitable, and Sheets. If a provider action is unavailable, record `verified: false` and the exact normalized error category instead of inventing a fallback.

- [ ] **Step 3: Add only verified Tencent Cloud actions to the catalog**

  Extend `TENCENT_CLOUD_API_CATALOG` with the exact verified action names and official documentation URLs. Catalog the trigger and status actions separately, including their use by the new executor. Do not catalog speculative actions.

- [ ] **Step 4: Add configuration defaults and capability gating**

  Add safe defaults to `deploy/env.example`: `Asia/Shanghai`, 1,800-second timeout, a bounded polling interval, short operation TTL, disabled capability fallback, and conservative batch/row limits. Set `WEDATA_TRIGGER_CAPABILITY=verified_only`; when no verified action is configured, planning remains available but confirmation returns `wedata_trigger_not_supported`.

- [ ] **Step 5: Add tests for configuration loading and secret hygiene**

  Assert that defaults parse correctly, environment overrides win, missing Feishu credentials produce a capability-disabled state, and serialized reports/errors never contain secret values. Run:

  ```bash
  python3 -m unittest tests.test_tencentcloud tests.test_deploy_scripts -v
  ```

- [ ] **Step 6: Commit the capability contract**

  ```bash
  git add docs/superpowers/reports/2026-08-19-wedata-feishu-capability-report.md tests/fixtures/wedata_capability_probe.json dlc_mcp/assets.py deploy/env.example tests/test_tencentcloud.py tests/test_deploy_scripts.py
  git commit -m "docs: verify refresh and Feishu capability contracts"
  ```

---

## Task 1: Build the in-memory operation store

**Files:**
- Create: `dlc_mcp/operation_store.py`
- Test: `tests/test_operation_store.py`

**Interfaces:**
- `OperationNotFound(code: str)`
- `OperationStore(ttl_seconds: int = 1800, clock: Callable[[], datetime] = utcnow)`
- `OperationStore.create(kind: str, payload: dict, context: dict) -> str`
- `OperationStore.get(operation_id: str, kind: str | None = None) -> dict`
- `OperationStore.confirm(operation_id: str, kind: str, context: dict) -> dict`
- `OperationStore.update(operation_id: str, **fields) -> dict`
- `OperationStore.expire(operation_id: str) -> None`
- `fingerprint_context(context: dict) -> str`

- [ ] **Step 1: Write failing tests for lifecycle invariants**

  Cover: create/get round trip; expired plans return `plan_expired`; unknown IDs return `plan_not_found`; a second confirm returns `plan_already_executed`; a changed table/partition/target fingerprint returns `plan_context_mismatch`; refresh and export kinds cannot be interchanged; the store does not persist after a new store instance is created.

- [ ] **Step 2: Run the focused tests and verify failure**

  ```bash
  python3 -m unittest tests.test_operation_store -v
  ```

  Expected: import or attribute failures because the store module is not present.

- [ ] **Step 3: Implement immutable creation data and controlled updates**

  Store deep-copied payloads, `created_at`, `expires_at`, `status`, `confirmed_at`, `executed_at`, and a SHA-256 context fingerprint. Protect the dictionary with `threading.RLock`. `confirm` must atomically transition `awaiting_confirmation` or `awaiting_write_confirmation` to `executing`/`writing` before returning the payload.

- [ ] **Step 4: Implement TTL and error-code behavior**

  Purge expired entries opportunistically on create/get/confirm. Return stable machine-readable codes from `OperationNotFound.code`; never include raw payload secrets in exception text.

- [ ] **Step 5: Run focused tests and commit**

  ```bash
  python3 -m unittest tests.test_operation_store -v
  git add dlc_mcp/operation_store.py tests/test_operation_store.py
  git commit -m "feat: add short-lived operation plan store"
  ```

---

## Task 2: Implement table producer resolution and refresh planning

**Files:**
- Create: `dlc_mcp/refresh.py`
- Modify: `dlc_mcp/live.py` only where normalized task/relation access is missing
- Test: `tests/test_refresh.py`

**Interfaces:**
- `RefreshPlanError(code: str, message: str, details: dict | None = None)`
- `TaskNode(task_id: str, name: str, project_id: str, task_type: str, inputs: tuple[str, ...], outputs: tuple[str, ...], evidence: tuple[str, ...], supported: bool, unsupported_reason: str = "")`
- `RefreshPlan(table_name: str, task_id: str, partition: str, timezone: str, levels: tuple[tuple[str, ...], ...], nodes: dict[str, TaskNode], warnings: tuple[str, ...], status: str)`
- `TableTaskResolver.resolve(table_name: str, task_id: str = "") -> list[TaskNode]`
- `TaskDependencyPlanner.build(target: TaskNode) -> RefreshPlan`
- `PartitionResolver.resolve(explicit_partition: str = "", now: datetime | None = None) -> str`
- `RefreshPlanner.prepare(table_name: str, task_id: str = "", partition: str = "", filters: dict | None = None, sql: str = "", timeout_seconds: int | None = None) -> RefreshPlan`

- [ ] **Step 1: Create fixture-backed tests for real mapping evidence**

  Construct an in-memory `AssetStore` with tasks whose `outputs` explicitly contain `mid_crm_account_df_check`, and a separate task whose name contains the table token but whose outputs do not. Assert only the explicit output mapping resolves. Add two real producers and assert the result is `multiple_producer_tasks` with candidate IDs until `task_id` is supplied.

- [ ] **Step 2: Add tests for partition resolution**

  With `ZoneInfo("Asia/Shanghai")`, assert a fixed instant before and after UTC midnight both resolve to the business date minus one day. Assert an explicit `dt=20260818` or equivalent partition is preserved exactly and malformed empty values raise `partition_not_identified` when table metadata cannot identify a partition column.

- [ ] **Step 3: Add tests for DAG construction and stable topological levels**

  Use a graph `source_a -> transform_a -> target` plus independent `source_b -> target`. Assert all nodes are present, levels are ordered upstream-first, and each level is sorted by task ID. Add a cycle and a missing relation; assert `dependency_cycle` and `dependency_incomplete` respectively.

- [ ] **Step 4: Add tests for task-type gating and overwrite warnings**

  Map offline data-integration and SQL/ETL task types to `supported=True`; map real-time, Shell/script, workflow, machine-learning, and unknown values to `supported=False` with `task_type_unsupported`. Add a partition existence fixture and assert the plan warning says the existing partition may be overwritten.

- [ ] **Step 5: Implement normalized task access without task-name inference**

  Read tasks from `AssetStore` and refresh missing/incomplete task definitions through `LiveWeData`. When a task ID is supplied, fetch its real definition before accepting it. Preserve evidence labels such as `task_output_mapping`, `task_input_mapping`, and `wedata_relation_api`; reject a node with no table evidence.

- [ ] **Step 6: Implement recursive dependency traversal and cycle detection**

  Traverse `list_upstream_tasks` from the target, deduplicate by task ID, merge relation payloads, and maintain a three-state DFS marker (`unseen`, `visiting`, `visited`). Missing task definitions or relation responses become `dependency_incomplete`; a back edge becomes `dependency_cycle`.

- [ ] **Step 7: Implement partition and plan serialization**

  Build the `RefreshPlan` with the final partition, SQL/filter summary, timeout, levels, node support statuses, existing-partition warning, and `awaiting_confirmation` status. Do not call a trigger API in this task.

- [ ] **Step 8: Run focused tests and commit**

  ```bash
  python3 -m unittest tests.test_refresh -v
  git add dlc_mcp/refresh.py dlc_mcp/live.py tests/test_refresh.py
  git commit -m "feat: plan WeData table refresh dependencies"
  ```

---

## Task 3: Implement official WeData execution and polling

**Files:**
- Create: `dlc_mcp/wedata_execution.py`
- Modify: `dlc_mcp/live.py` if a shared task-instance normalizer is needed
- Test: `tests/test_wedata_execution.py`

**Interfaces:**
- `WeDataExecutionError(code: str, details: dict | None = None)`
- `TaskExecutionResult(task_id: str, status: str, instance_id: str = "", message: str = "", started_at: str = "", ended_at: str = "")`
- `WeDataExecutionConnector(client, trigger_action: str, status_action: str)`
- `WeDataExecutionConnector.trigger(task: TaskNode, partition: str) -> TaskExecutionResult`
- `WeDataExecutionConnector.status(task: TaskNode, instance_id: str) -> TaskExecutionResult`
- `WeDataExecutionConnector.capability() -> dict`
- `RefreshExecutor(connector, sleep: Callable[[float], None], clock: Callable[[], float])`
- `RefreshExecutor.execute(plan: RefreshPlan, timeout_seconds: int) -> dict`

- [ ] **Step 1: Write payload and terminal-state tests from the sanitized capability fixture**

  Assert the connector sends the exact verified project/task/partition fields, never sends secrets in the payload, normalizes provider success/failure/cancelled/running states, and returns `wedata_trigger_not_supported` when capability verification is false.

- [ ] **Step 2: Add executor tests for serial levels and branch isolation**

  Use a fake connector that records calls. Assert level 0 tasks run in task-id order, level 1 starts only after required parents succeed, a failed parent marks only its descendants `blocked`, and an independent branch still runs. Assert no retry call occurs.

- [ ] **Step 3: Add tests for target-success early return and timeout**

  Make the target succeed while an unrelated branch remains running; assert the executor returns success and reports `running_independent_branches`. Make the target remain running beyond the configured deadline; assert `task_timeout` and no success claim.

- [ ] **Step 4: Implement the verified official trigger adapter**

  Use `TencentCloudClient.call` with the action recorded in Task 0. Keep provider field construction isolated in `_build_trigger_payload`; pass project ID, task ID, execution date/partition, and any verified run-mode fields only. Convert API error codes to `wedata_permission_denied`, `wedata_trigger_not_supported`, or `task_failed` without exposing raw credentials.

- [ ] **Step 5: Implement polling and normalized statuses**

  Poll the verified status action using the returned instance/run identifier. Use monotonic time for deadlines, configurable sleep, and explicit terminal-state mapping. Preserve request IDs only when they are non-sensitive and useful for server logs; do not return raw payloads.

- [ ] **Step 6: Implement level-by-level execution and descendant blocking**

  Maintain node state and reverse adjacency. Before running a node, mark it `blocked` if any parent is failed, timed out, or blocked. Execute same-level nodes serially, stop returning once the target is successful, and include a complete node status snapshot in the result.

- [ ] **Step 7: Run focused tests and commit**

  ```bash
  python3 -m unittest tests.test_wedata_execution -v
  git add dlc_mcp/wedata_execution.py dlc_mcp/live.py tests/test_wedata_execution.py
  git commit -m "feat: execute verified WeData refresh plans"
  ```

---

## Task 4: Add DLC query orchestration for refreshed table data

**Files:**
- Create: `dlc_mcp/query_orchestration.py`
- Modify: `dlc_mcp/dlc_query.py`
- Test: `tests/test_query_orchestration.py`

**Interfaces:**
- `QueryPlanError(code: str, details: dict | None = None)`
- `QueryResult(columns: tuple[str, ...], rows: tuple[dict, ...], row_count: int, column_count: int, pages: int, next_token: str = "", preview_truncated: bool = False)`
- `TableQueryService(query_service: DLCQueryService, table_metadata_reader)`
- `TableQueryService.build_sql(table_name: str, partition: str, filters: dict | None = None, sql: str = "") -> str`
- `TableQueryService.fetch(table_name: str, partition: str, filters: dict | None = None, sql: str = "", max_rows: int | None = None) -> QueryResult`

- [ ] **Step 1: Write tests for default SQL and filter binding**

  Assert `build_sql("mid_crm_account_df_check", "dt=20260818", {"status": "active"})` produces a single read-only query with a safely quoted identifier and bound literal representation. Assert no unrecognized partition column allows an unbounded default query.

- [ ] **Step 2: Write tests for custom SQL validation**

  Assert custom `SELECT` and `WITH` SQL is accepted through `validate_read_only_sql`; DDL, DML, multiple statements, and unsafe partition overrides are rejected. The returned SQL hash may be included in an internal plan but raw SQL must be omitted from user-facing error text when it contains sensitive literals.

- [ ] **Step 3: Write tests for pagination and normalized statistics**

  Fake two DLC result pages, aggregate rows and columns, preserve the first schema order, count rows/columns, and stop at `max_rows` with `preview_truncated=True`. Assert a failed DLC page returns a query error rather than partial data marked successful.

- [ ] **Step 4: Implement safe SQL construction**

  Reuse the existing read-only validator. Resolve the actual partition column from table metadata; construct `SELECT * FROM <table> WHERE <partition-column> = <literal>` and append validated filters. If a custom SQL is supplied, validate it and avoid silently rewriting it.

- [ ] **Step 5: Implement paginated result aggregation**

  Add a helper in `DLCQueryService` or the orchestration module that repeatedly calls `result` with `next_token`, normalizes schema names, and enforces row/page/byte limits. Return a bounded preview for `prepare_table_export` and the full in-memory row set only within configured limits.

- [ ] **Step 6: Run focused tests and commit**

  ```bash
  python3 -m unittest tests.test_dlc_query tests.test_query_orchestration -v
  git add dlc_mcp/query_orchestration.py dlc_mcp/dlc_query.py tests/test_query_orchestration.py
  git commit -m "feat: orchestrate safe partitioned DLC table queries"
  ```

---

## Task 5: Implement Feishu authentication, URL parsing, and target discovery

**Files:**
- Create: `dlc_mcp/feishu.py`
- Test: `tests/test_feishu.py`

**Interfaces:**
- `FeishuError(code: str, details: dict | None = None)`
- `FeishuTarget(target_type: str, resource_token: str, managed_range: dict, display_name: str, fingerprint: str)`
- `FeishuConnector(app_id: str, app_secret: str, api_base: str = "https://open.feishu.cn")`
- `FeishuConnector.acquire_tenant_token() -> str`
- `FeishuConnector.check_permissions(target_type: str) -> dict`
- `FeishuConnector.resolve_target(target_type: str, url: str, table_name: str, document_block_id: str = "", table_id: str = "", sheet_name: str = "") -> FeishuTarget`
- `FeishuConnector.snapshot(target: FeishuTarget) -> dict`

- [ ] **Step 1: Write credential and URL validation tests**

  Assert missing `FEISHU_APP_ID` or `FEISHU_APP_SECRET` returns `feishu_permission_denied` without making a network call. Assert Docs/Bitable/Sheets URL forms map only to their explicit target type; mismatches return `feishu_target_type_mismatch`; malformed links return `feishu_target_not_found`.

- [ ] **Step 2: Write permission-gate tests**

  Fake token and permission responses. Assert all required permissions for the selected target type are checked before a writer is constructed, and any missing permission prevents clearing or writing. Assert app secrets are absent from exception strings and serialized snapshots.

- [ ] **Step 3: Write target management tests**

  Docs must reject an absent `document_block_id`; Bitable must reject a missing same-name table; Sheets must reject a missing same-name worksheet and default the managed range to `A1`. Assert the target fingerprint changes when the target structure or managed range changes.

- [ ] **Step 4: Implement token acquisition and normalized HTTP calls**

  Use `urllib.request` with JSON requests, bounded timeouts, and normalized provider error handling. Cache the tenant token only in the process memory and refresh before expiry. Keep response parsing in connector methods; never return raw vendor payloads from MCP.

- [ ] **Step 5: Implement target resolution for each type**

  Parse resource tokens from the URL, call the relevant metadata APIs, enforce explicit target type, match Bitable tables and Sheets worksheets by source table name, and require a Docs native table block ID on first use. Return a managed-range snapshot limited to the selected target.

- [ ] **Step 6: Run focused tests and commit**

  ```bash
  python3 -m unittest tests.test_feishu -v
  git add dlc_mcp/feishu.py tests/test_feishu.py
  git commit -m "feat: resolve and authorize Feishu export targets"
  ```

---

## Task 6: Implement Docs, Bitable, and Sheets overwrite writers

**Files:**
- Create: `dlc_mcp/feishu_writers.py`
- Test: `tests/test_feishu_writers.py`

**Interfaces:**
- `WriteBatchResult(status: str, cleared_rows: int, written_rows: int, successful_batches: tuple[int, ...], failed_batches: tuple[dict, ...], managed_range: dict)`
- `FeishuWriter(target_api, batch_size: int = 100) -> None`
- `FeishuWriter.preview(target: FeishuTarget, result: QueryResult) -> dict`
- `FeishuWriter.write(target: FeishuTarget, result: QueryResult, expected_fingerprint: str) -> WriteBatchResult`
- Internal methods: `_clear_docs_table`, `_write_docs_table`, `_clear_bitable_records`, `_write_bitable_records`, `_clear_sheet_range`, `_write_sheet_values`, `_verify_target`.

- [ ] **Step 1: Write Docs overwrite tests**

  Assert the writer re-reads the block fingerprint, clears only the specified native table block, writes one header row followed by data rows, rejects row counts above `FEISHU_DOCS_MAX_ROWS`, and leaves surrounding document content untouched.

- [ ] **Step 2: Write Bitable overwrite and schema tests**

  Assert old records are deleted in batches before new records are inserted, field definitions follow the latest query columns, missing same-name tables fail without creation, and row-count reduction removes stale records. Use fake API state to verify no out-of-table records are deleted.

- [ ] **Step 3: Write Sheets overwrite and schema tests**

  Assert the selected same-name worksheet is cleared from `A1` through the previous managed extent, new headers/data begin at `A1`, column order follows the query, and rows outside the managed range are preserved. Verify row-count reduction clears trailing rows.

- [ ] **Step 4: Write batching and partial-failure tests**

  Make batch 2 fail after batch 1 succeeds. Assert result status is `partial_write`, successful and failed batch indexes are returned, the cleared range is reported, and no false full-success status is emitted. Add a verification mismatch test returning `feishu_schema_changed`.

- [ ] **Step 5: Implement range-limited clear and replacement**

  Recheck target fingerprint before clearing. Clear the complete prior managed range, write the current header/data in bounded batches, update the managed-range snapshot only after successful batches, and verify header/row counts where the API supports reads. Never call create-table, create-sheet, or create-doc-block endpoints.

- [ ] **Step 6: Implement target-specific adapters behind one writer interface**

  Keep Docs block requests, Bitable record/field requests, and Sheets value/range requests isolated in private adapter methods. Normalize rate-limit and permission failures to stable error codes. Do not attempt rollback in this release.

- [ ] **Step 7: Run focused tests and commit**

  ```bash
  python3 -m unittest tests.test_feishu_writers -v
  git add dlc_mcp/feishu_writers.py tests/test_feishu_writers.py
  git commit -m "feat: overwrite managed Feishu targets safely"
  ```

---

## Task 7: Add refresh and export orchestration services

**Files:**
- Modify: `dlc_mcp/refresh.py`
- Create: `dlc_mcp/export.py`
- Test: `tests/test_workflow_tools.py`

**Interfaces:**
- `RefreshWorkflow(store, planner, executor, operation_store)`
- `RefreshWorkflow.prepare(args: dict) -> dict`
- `RefreshWorkflow.confirm(plan_id: str) -> dict`
- `ExportWorkflow(refresh_workflow, query_service, feishu_connector, writer, operation_store)`
- `ExportWorkflow.prepare(args: dict) -> dict`
- `ExportWorkflow.confirm(write_plan_id: str) -> dict`

- [ ] **Step 1: Write refresh prepare/confirm contract tests**

  Assert prepare returns `awaiting_task_selection` for multiple producers, `awaiting_confirmation` for a valid plan, and a non-executable plan for unsupported types or graph errors. Assert prepare never calls `trigger`, and confirm without a valid plan returns the specified plan error.

- [ ] **Step 2: Write refresh execution contract tests**

  Assert confirm atomically consumes the plan, executes the DAG once, returns progress per task, reports target success immediately, and a second confirmation returns `plan_already_executed`. Assert unsupported plans cannot enter execution.

- [ ] **Step 3: Write export workflow contract tests**

  Assert export prepare invokes refresh planning/execution according to the configured default, refuses to create a write plan when the target task did not succeed, fetches query columns/rows, resolves and permission-checks Feishu, and returns a preview requiring `confirm_table_export`.

- [ ] **Step 4: Implement refresh workflow state transitions**

  Create an operation-store record containing table/task/partition/DAG/context. On confirm, revalidate the context fingerprint, transition to `executing`, call `RefreshExecutor`, persist normalized result, and mark terminal status `success`, `partial_success`, `failed`, or `blocked`.

- [ ] **Step 5: Implement export workflow and refresh dependency**

  `prepare_table_export` must either use a caller-provided successful refresh context or create/confirm the refresh plan according to the product rule that export preparation refreshes first. Query only after target-task success. Store SQL hash, query statistics, target fingerprint, managed range, and preview rows in the write plan.

- [ ] **Step 6: Implement confirm-time rechecks**

  On export confirmation, atomically consume the write plan, reacquire permissions, resolve the URL again, compare target type/resource/range fingerprint, and refuse with `plan_context_mismatch` or the relevant Feishu error before any clear call.

- [ ] **Step 7: Run focused tests and commit**

  ```bash
  python3 -m unittest tests.test_workflow_tools -v
  git add dlc_mcp/refresh.py dlc_mcp/export.py tests/test_workflow_tools.py
  git commit -m "feat: orchestrate confirmed refresh and export workflows"
  ```

---

## Task 8: Register the four MCP tools and wire process services

**Files:**
- Modify: `dlc_mcp/mcp.py`
- Modify: `dlc_mcp/server.py`
- Modify: `tests/test_mcp.py`
- Modify: `tests/test_server.py`

**Interfaces:**
- Tool names and arguments:
  - `prepare_table_refresh(table_name, task_id?, partition?, filters?, sql?, timeout_seconds?)`
  - `confirm_table_refresh(plan_id)`
  - `prepare_table_export(table_name, feishu_url, target_type, partition?, filters?, sql?, document_block_id?, table_id?, sheet_name?, timeout_seconds?)`
  - `confirm_table_export(write_plan_id)`
- `_call_tool(store, request, live=None, query_service=None, workflows=None) -> response`
- `handle_request(store, request, live=None, query_service=None, workflows=None) -> response`

- [ ] **Step 1: Add schema tests before changing registrations**

  Call `tools/list` and assert all four tools have required fields, optional fields, and `readOnlyHint: false`/`destructiveHint: true` annotations. Assert no credentials appear in schemas or descriptions.

- [ ] **Step 2: Add request/response tests for argument validation**

  Assert missing table, URL, target type, plan ID, or required Docs block ID returns JSON-RPC parameter errors or stable workflow error data. Assert `target_type` accepts only `docs`, `bitable`, and `sheets`.

- [ ] **Step 3: Register schemas and dispatch branches**

  Add tool entries near the existing DLC tools. Dispatch to workflow services, catch only expected domain/vendor errors, and format structured JSON/Markdown summaries containing statuses, progress, warnings, preview, and next action. Do not place API pagination or vendor payload parsing in `mcp.py`.

- [ ] **Step 4: Wire shared services in `server.py`**

  Build one `OperationStore`, `RefreshWorkflow`, and `ExportWorkflow` per server process. Construct WeData execution only when capability configuration and Tencent credentials are present; construct Feishu services only when both app credentials are present. Preserve existing startup behavior for query-only deployments.

- [ ] **Step 5: Add end-to-end mocked MCP tests**

  Send JSON-RPC `tools/call` requests for prepare/confirm refresh and prepare/confirm export. Assert the first confirmation boundary prevents accidental writes, the second boundary is required for Feishu overwrite, and errors are JSON serializable and secret-free.

- [ ] **Step 6: Run MCP and server tests and commit**

  ```bash
  python3 -m unittest tests.test_mcp tests.test_server tests.test_workflow_tools -v
  git add dlc_mcp/mcp.py dlc_mcp/server.py tests/test_mcp.py tests/test_server.py
  git commit -m "feat: expose confirmed refresh and Feishu export MCP tools"
  ```

---

## Task 9: Add deployment, API, and user documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Modify: `docs/server-mcp-wedata-flow.md`
- Modify: `deploy/env.example`
- Create: `docs/feishu-export-permissions.md`
- Test: `tests/test_docs.py`

**Interfaces:**
- Documentation must name the four MCP tools exactly and describe their argument names, status transitions, confirmation requirements, supported task types, supported Feishu target types, and server-only credentials.

- [ ] **Step 1: Document user-visible workflows in README**

  Add examples showing `prepare_table_refresh` followed by `confirm_table_refresh`, and `prepare_table_export` followed by `confirm_table_export`. Explain candidate producer selection, default partition, existing-partition overwrite warning, target-success gate, and partial-write reporting.

- [ ] **Step 2: Document architecture boundaries**

  Update the architecture diagram and module table to place planners/executors above connectors and operation storage. State that SQLite remains read-only asset cache for this feature and transient plans are not persisted.

- [ ] **Step 3: Document server setup and capability verification**

  Add environment names, the authorized capability-probe procedure, verified-action gate, timeout/polling settings, and smoke-test examples. Make clear that a failed capability probe permits plan generation but blocks remote execution.

- [ ] **Step 4: Document Feishu permissions and managed ranges**

  Create `docs/feishu-export-permissions.md` covering app-token credentials, required permission categories per Docs/Bitable/Sheets, existing-target requirements, Docs block IDs, source-table-name matching, A1 default, range isolation, and no-auto-create behavior. Do not include real tenant IDs, URLs, or secrets.

- [ ] **Step 5: Add documentation assertions**

  Extend `tests/test_docs.py` to check tool names, configuration names, server-only credential wording, no-auto-create wording, and confirmation wording. Run:

  ```bash
  python3 -m unittest tests.test_docs -v
  ```

- [ ] **Step 6: Commit documentation**

  ```bash
  git add README.md docs/architecture.md docs/server-mcp-wedata-flow.md docs/feishu-export-permissions.md deploy/env.example tests/test_docs.py
  git commit -m "docs: document confirmed refresh and Feishu export"
  ```

---

## Task 10: Complete integration, security, and regression verification

**Files:**
- Modify: all feature tests only when a failing integration assertion identifies a concrete defect
- Modify: `docs/superpowers/reports/2026-08-19-wedata-feishu-capability-report.md` with final verification results

**Interfaces:**
- The final MCP surface must pass existing query behavior unchanged and expose stable workflow error codes listed in the approved design.

- [ ] **Step 1: Run all Python tests**

  ```bash
  python3 -m unittest discover -s tests -v
  ```

  Expected: all existing and new tests pass. If an existing test fails, fix only the feature-induced regression and document the cause in the capability report.

- [ ] **Step 2: Run syntax and package checks**

  ```bash
  node --check bin/dlc-mcp.js
  npm pack --dry-run
  git diff --check
  ```

- [ ] **Step 3: Run secret and placeholder scans**

  ```bash
  grep -RInE 'TBD|TODO|AKIA[0-9A-Z]{16}|BEGIN (RSA|OPENSSH|EC) PRIVATE KEY|APP_SECRET=.*[^r]eplace' dlc_mcp tests docs deploy README.md || true
  ```

  Expected: no feature placeholder, credential, private-key material, or real secret output. The literal scan command itself may appear in shell history but must not be committed.

- [ ] **Step 4: Review confirmation and range-isolation invariants**

  Manually inspect the diff to verify every remote side effect is reachable only from a confirm handler, every Feishu clear is preceded by permission and fingerprint checks, every WeData execution uses the verified official adapter, and no connector leaks raw response payloads.

- [ ] **Step 5: Run authorized smoke tests with bounded sample targets**

  In the configured server environment, prepare a known non-critical table, confirm only after reviewing the plan, prepare an export to a dedicated pre-existing Feishu target, inspect the preview, then confirm. Record only action/status/error categories and row counts in the report; do not save returned data or credentials.

- [ ] **Step 6: Confirm clean feature scope and final commit**

  ```bash
  git status --short
  git diff --stat HEAD~10..HEAD
  git log --oneline -n 12
  ```

  Ensure unrelated deletion/untracked files remain untouched and are not staged. Create a final integration commit only if the repository convention requires one; otherwise retain the task commits for review.

---

## Spec Coverage Self-Review

- WeData official trigger/status capability and account permission verification: Task 0 and Task 3.
- Real table-to-task evidence and multiple-producer selection: Task 2.
- Recursive upstream dependencies, DAG, cycles, missing relations, stable levels: Task 2.
- Asia/Shanghai default partition, explicit partition, existing-partition warning: Task 2.
- Supported and unsupported task types: Tasks 0 and 2.
- Serial same-level execution, branch-level blocking, no retry, timeout, target-success early return: Task 3.
- In-memory plans, TTL, one-time confirmation, process loss: Task 1.
- Default/custom read-only SQL, filters, partition safety, pagination, statistics: Task 4.
- Feishu app credentials, permission gate, URL/type matching, managed-range fingerprint: Task 5.
- Docs native block, Bitable same-name table, Sheets same-name worksheet/A1: Tasks 5 and 6.
- Overwrite clear, schema replacement, stale-row cleanup, out-of-range preservation: Task 6.
- Large-result limits, batches, partial writes, no rollback promise: Task 6.
- Four MCP tools, annotations, state/error formatting, shared service wiring: Task 8.
- README, architecture, deployment, permissions, smoke-test documentation: Task 9.
- Full regression, syntax, package, secret, placeholder, and scope checks: Task 10.

## Placeholder and Type Consistency Review

- No implementation step depends on an undefined function: all cross-task interfaces are listed in the Interfaces blocks.
- `RefreshPlan`, `TaskNode`, `QueryResult`, `FeishuTarget`, `OperationStore`, and workflow method names remain consistent throughout the plan.
- Capability failure is represented by `wedata_trigger_not_supported`, not by a speculative provider action.
- The approved four-tool names and parameter names are used consistently in code, tests, and documentation.
- The plan contains no `TBD`, `TODO`, or deferred implementation item.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-19-wedata-refresh-feishu-export.md`. Two execution options:

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, and iterate quickly.

**2. Inline Execution** — execute the tasks in this session using the executing-plans workflow with checkpoints.

Choose the execution approach when ready.
