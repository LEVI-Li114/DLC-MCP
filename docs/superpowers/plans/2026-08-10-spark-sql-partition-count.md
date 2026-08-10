# Spark SQL Partition Count Implementation Plan

> **Implementation resolution (2026-08-10):** Public WeData SQL-exploration APIs did not provide a complete documented result-fetch contract. With user approval to prioritize a usable tool, the execution boundary was changed to the public DLC `2021-01-25` APIs: `CreateTasks`, `DescribeMCPTask`, `DescribeMCPTaskResult`, and `CancelTask`. WeData/Asset Store metadata remains the validation source. The verified replacement contract is documented in `docs/superpowers/contracts/2026-08-10-dlc-query-contract.md`; references below to a WeData executor are superseded by that contract.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a safe asynchronous Spark SQL partition row-count query flow for one validated partition in the default WeData project.

**Architecture:** MCP only registers tools, validates the request envelope, delegates, and formats the response. `QueryService` orchestrates metadata validation, idempotency, quotas, execution, and result handling. `query_validation.py` owns strict identifiers, partition completeness, and fixed SQL generation. `QueryStore` owns an isolated SQLite `query_jobs` table. `QueryExecutor` is the only boundary to WeData query execution and must never call production-task APIs. The first implementation task is a contract gate: no guessed WeData action or payload may be shipped.

**Tech Stack:** Python 3, existing `TencentCloudClient`, SQLite, existing MCP JSON-RPC entry points, pytest, and fake WeData clients.

## Global Constraints

- Only exact-partition `COUNT(*)` queries are supported.
- Every request must provide every partition key; no full-table, range, `IN`, wildcard, cross-partition, multi-table, subquery, DDL, DML, or arbitrary SQL query.
- MCP input schemas must not contain an `sql` property.
- Table and partition identifiers must come from validated default-project metadata.
- Generated SQL must be one table, one exact partition predicate, and one numeric `row_count` column.
- Submission is asynchronous and returns without waiting for Spark completion.
- Queries use a dedicated resource group/queue, low priority, bounded driver/executor resources, and a maximum runtime.
- Query execution must not reuse, update, or cancel production tasks.
- WeData is the execution source of truth. Transport uncertainty is not a Spark failure and must not trigger blind duplicate submission.
- Successful results must be exactly one row and one numeric `row_count`; malformed results return `RESULT_INVALID`.
- Times are UTC; status/result records have TTLs; a failed local store rejects new submissions.
- Secrets, signatures, and sensitive headers never appear in logs or error messages.
- No third-party dependency is added.

---

### Task 1: Establish the WeData query execution contract

**Files:**
- Create: `docs/superpowers/contracts/2026-08-10-wedata-query-contract.md`
- Create: `tests/test_query_executor_contract.py`
- Modify: `deploy/env.example` only after exact setting names are confirmed
- Modify: `dlc_mcp/tencentcloud.py` only for generic, contract-backed helpers; never add guessed actions

**Interfaces:**
- Consumes: `TencentCloudClient.call(action, payload)`, `WEDATA_PROJECT_ID`, current WeData API version, and fake-client conventions.
- Produces: an explicit contract containing the confirmed create, status, result, and cancel operations; exact request fields; response paths; task-id semantics; resource/queue binding; timeout behavior; and transport error classification.

- [ ] **Step 1: Write the failing contract test.**

```python
def test_query_contract_declares_all_required_operations():
    contract = load_query_contract()
    assert set(contract.operations) == {"submit", "status", "result", "cancel"}
    for operation in contract.operations.values():
        assert operation.action
        assert operation.request_fields
        assert operation.response_paths
```

- [ ] **Step 2: Run the focused test.**

Run: `pytest tests/test_query_executor_contract.py -q`
Expected: FAIL because the contract loader/document does not yet exist.

- [ ] **Step 3: Investigate before implementation.**

Inspect the repository API catalog, existing WeData wrappers, deployment configuration, and the tenant-approved Tencent Cloud API documentation. Record only operations that are supported by evidence. If the API cannot create an isolated one-off query, record the supported dedicated-template mechanism instead. Do not substitute `CreateTask`, production task submission, or an unverified action.

- [ ] **Step 4: Add the contract document and a test fixture loader.**

The contract must define these exact conceptual operations:

```text
submit(project_id, sql, execution_policy) -> external_task_id
status(project_id, external_task_id) -> external_status
result(project_id, external_task_id) -> raw_result
cancel(project_id, external_task_id) -> cancellation_ack
```

`execution_policy` must include the dedicated resource group/queue, low priority, driver/executor limits, and timeout. The document must map each conceptual operation to its verified action and payload fields.

- [ ] **Step 5: Run the contract test.**

Run: `pytest tests/test_query_executor_contract.py -q`
Expected: PASS.

- [ ] **Step 6: Commit.**

```bash
git add docs/superpowers/contracts/2026-08-10-wedata-query-contract.md tests/test_query_executor_contract.py deploy/env.example dlc_mcp/tencentcloud.py
git commit -m "docs: define wedata query execution contract"
```

---

### Task 2: Add query models and strict validation

**Files:**
- Create: `dlc_mcp/query_models.py`
- Create: `dlc_mcp/query_validation.py`
- Create: `tests/test_query_validation.py`

**Interfaces:**
- Produces `QueryRequest(table_name: str, partition: dict[str, str])`.
- Produces `ValidatedQuery(table_name: str, partition: dict[str, str], sql: str, sql_hash: str, idempotency_key: str)`.
- `normalize_table_name(value: str) -> str`.
- `validate_partition(table: dict, partition: dict[str, str]) -> dict[str, str]`.
- `build_partition_count_sql(table_identifier: str, partition: dict[str, str]) -> str`.
- `validate_generated_sql(sql: str) -> None`.

- [ ] **Step 1: Write failing tests.**

```python
def test_requires_all_partition_keys():
    with pytest.raises(QueryValidationError, match="PARTITION_REQUIRED"):
        validate_partition({"partition_keys": ["ds", "region"]}, {"ds": "2026-08-10"})


def test_rejects_sql_fragments_in_table_and_partition_values():
    for value in ["orders;drop", "orders--comment", "x' OR 1=1", "${bad}"]:
        with pytest.raises(QueryValidationError):
            normalize_table_name(value)


def test_builds_only_fixed_count_sql():
    sql = build_partition_count_sql("dws_order_detail", {"ds": "2026-08-10"})
    assert sql == "SELECT COUNT(*) AS row_count FROM `dws_order_detail` WHERE `ds` = '2026-08-10'"
```

- [ ] **Step 2: Run tests and verify failure.**

Run: `pytest tests/test_query_validation.py -q`
Expected: FAIL because the query modules do not yet exist.

- [ ] **Step 3: Implement minimal models and validation.**

Use dataclasses, normalize only a single dotted identifier composed of letters, digits, and underscores, reject empty/oversized values, require a non-empty mapping, require exact metadata keys, and escape only the validated literal form. Preserve sorted partition-key order for deterministic SQL, hashes, and idempotency keys. Raise a typed error carrying one stable error code and a safe message.

- [ ] **Step 4: Add second-pass SQL checks.**

`validate_generated_sql` must parse by strict structural checks and reject semicolons, comments, additional statements, joins, subqueries, DDL/DML, missing `COUNT(*) AS row_count`, unvalidated identifiers, and predicates not matching the exact validated partition set.

- [ ] **Step 5: Run tests.**

Run: `pytest tests/test_query_validation.py -q`
Expected: PASS.

- [ ] **Step 6: Commit.**

```bash
git add dlc_mcp/query_models.py dlc_mcp/query_validation.py tests/test_query_validation.py
git commit -m "feat: validate partition count queries"
```

---

### Task 3: Add isolated SQLite query state

**Files:**
- Create: `dlc_mcp/query_store.py`
- Create: `tests/test_query_store.py`
- Modify: `dlc_mcp/server.py`
- Modify: `dlc_mcp/gateway.py`
- Modify: `dlc_mcp/assets.py` only if the store needs the existing connection migration hook

**Interfaces:**
- `QueryStore(conn)`.
- `init_schema() -> None`.
- `create_job(job: QueryJob) -> None`.
- `get_job(query_id: str) -> QueryJob | None`.
- `find_active_by_idempotency_key(key: str, now: datetime) -> QueryJob | None`.
- `update_submission(query_id: str, external_task_id: str, submitted_at: datetime) -> None`.
- `update_status(query_id: str, patch: QueryStatusPatch) -> QueryJob`.
- `expire_jobs(now: datetime) -> int`.
- `delete_expired_results(now: datetime) -> int`.

- [ ] **Step 1: Write failing tests.**

```python
def test_query_jobs_schema_and_idempotent_lookup(conn):
    store = QueryStore(conn)
    store.init_schema()
    job = make_job(idempotency_key="project:dws_order_detail:ds=2026-08-10")
    store.create_job(job)
    assert store.get_job(job.query_id).query_id == job.query_id
    assert store.find_active_by_idempotency_key(job.idempotency_key, now=job.created_at).query_id == job.query_id


def test_expired_result_is_removed_without_deleting_a_live_job(conn):
    store = QueryStore(conn)
    store.init_schema()
    store.create_job(make_succeeded_job(expires_at=past()))
    assert store.delete_expired_results(now=now()) == 1
    assert store.get_job("q-expired").status == "SUCCEEDED"
```

- [ ] **Step 2: Run focused tests and verify failure.**

Run: `pytest tests/test_query_store.py -q`
Expected: FAIL because `QueryStore` and query models do not yet exist.

- [ ] **Step 3: Implement schema and transactional methods.**

Create `query_jobs` with the fields from the approved design, unique `query_id` and `idempotency_key`, indexes on status and expiry, UTC ISO timestamps, and explicit `check_same_thread=False` compatibility matching `AssetStore`. Store only SQL hash by default. Use transactions for create and state updates. Reject new creates on SQLite errors rather than returning a fake query ID.

- [ ] **Step 4: Wire initialization.**

Initialize `QueryStore` from the same database connection in both `server.py` and `gateway.py`; pass it explicitly to the query service construction path. Do not change existing asset read behavior.

- [ ] **Step 5: Run tests.**

Run: `pytest tests/test_query_store.py tests/test_mcp.py -q`
Expected: PASS.

- [ ] **Step 6: Commit.**

```bash
git add dlc_mcp/query_store.py tests/test_query_store.py dlc_mcp/server.py dlc_mcp/gateway.py dlc_mcp/assets.py
git commit -m "feat: store partition query jobs"
```

---

### Task 4: Implement the contract-backed QueryExecutor

**Files:**
- Create: `dlc_mcp/query_executor.py`
- Create: `tests/test_query_executor.py`
- Modify: `dlc_mcp/tencentcloud.py` only where Task 1 verified a generic wrapper is necessary
- Modify: `deploy/env.example` with verified query settings

**Interfaces:**
- `QueryExecutionPolicy.from_env() -> QueryExecutionPolicy`.
- `QueryExecutor(client, project_id, policy, contract) -> None`.
- `submit_count_query(validated_query: ValidatedQuery) -> ExternalTaskRef`.
- `get_status(task_id: str) -> ExternalStatus`.
- `get_result(task_id: str) -> CountResult`.
- `cancel(task_id: str) -> None`.

- [ ] **Step 1: Write failing fake-client tests.**

```python
def test_submit_uses_only_verified_query_operation(fake_client, contract):
    executor = QueryExecutor(fake_client, "project", safe_policy(), contract)
    ref = executor.submit_count_query(validated_query())
    assert ref.task_id == "query-task-1"
    assert fake_client.calls[-1][0] == contract.operation("submit").action
    assert fake_client.calls[-1][1]["ProjectId"] == "project"


def test_transport_uncertainty_is_not_reported_as_spark_failure(fake_client, contract):
    fake_client.raise_timeout = True
    with pytest.raises(QueryTransportUncertain):
        QueryExecutor(fake_client, "project", safe_policy(), contract).submit_count_query(validated_query())
```

- [ ] **Step 2: Run tests and verify failure.**

Run: `pytest tests/test_query_executor.py -q`
Expected: FAIL because the executor does not yet exist.

- [ ] **Step 3: Implement the executor against the contract.**

Build payloads only from validated SQL, the configured project, and the fixed execution policy. Never accept raw SQL from the MCP layer. Map external statuses to `SUBMITTED`, `RUNNING`, `SUCCEEDED`, `FAILED`, `CANCELLED`, or `TIMEOUT`; preserve unknown/transport uncertainty as a distinct exception. Parse result only in the executor’s contract-backed response path and reject malformed shapes.

- [ ] **Step 4: Test isolation and cancellation.**

Assert that no production task action is called, the resource policy is present in submit payloads, and `cancel` receives only the query task ID.

- [ ] **Step 5: Run tests.**

Run: `pytest tests/test_query_executor.py -q`
Expected: PASS.

- [ ] **Step 6: Commit.**

```bash
git add dlc_mcp/query_executor.py tests/test_query_executor.py dlc_mcp/tencentcloud.py deploy/env.example
git commit -m "feat: execute isolated wedata count queries"
```

---

### Task 5: Implement QueryService orchestration

**Files:**
- Create: `dlc_mcp/query_service.py`
- Create: `tests/test_query_service.py`

**Interfaces:**
- `QueryService(store: QueryStore, metadata: QueryMetadataProvider, executor: QueryExecutor, clock=utc_now) -> None`.
- `submit_partition_count_query(table_name: str, partition: dict[str, str]) -> dict`.
- `get_partition_count_query(query_id: str) -> dict`.
- `cancel_partition_count_query(query_id: str) -> dict` only if cancellation is explicitly exposed by the approved contract; otherwise do not add an MCP tool.

- [ ] **Step 1: Write failing service tests.**

```python
def test_missing_table_or_partition_does_not_submit(fake_metadata, fake_executor, query_store):
    service = make_service(fake_metadata, fake_executor, query_store)
    with pytest.raises(QueryServiceError, match="INVALID_TABLE"):
        service.submit_partition_count_query("missing_table", {"ds": "2026-08-10"})
    assert fake_executor.submissions == []


def test_duplicate_submission_returns_existing_query(fake_service):
    first = fake_service.submit_partition_count_query("dws_order_detail", {"ds": "2026-08-10"})
    second = fake_service.submit_partition_count_query("dws_order_detail", {"ds": "2026-08-10"})
    assert second["query_id"] == first["query_id"]
    assert fake_service.executor.submissions == 1
```

- [ ] **Step 2: Run focused tests and verify failure.**

Run: `pytest tests/test_query_service.py -q`
Expected: FAIL because `QueryService` does not yet exist.

- [ ] **Step 3: Implement submission flow.**

Resolve the table only in the default project, obtain reliable partition metadata, validate all partition keys and values, generate and second-pass-check SQL, compute the idempotency key, enforce active-query and duplicate-interval limits, create the local job before external submission when the persistence contract requires it, and record the external task ID immediately after confirmed submission. If submission outcome is uncertain, retain a non-terminal local state and return a safe retry/status response rather than creating another task.

- [ ] **Step 4: Implement status/result flow.**

For non-terminal jobs, query WeData and apply only legal state transitions. For success, fetch and validate the single numeric count, persist it, and return the result. Map external failures, cancellation, timeout, expiration, access denial, transport uncertainty, and malformed result into stable safe responses. Never manufacture a count.

- [ ] **Step 5: Test quotas, TTL, status transitions, and error redaction.**

Use fake clocks and fake executor responses. Assert production task IDs/actions are never used and secrets do not occur in returned messages.

- [ ] **Step 6: Run tests.**

Run: `pytest tests/test_query_service.py -q`
Expected: PASS.

- [ ] **Step 7: Commit.**

```bash
git add dlc_mcp/query_service.py tests/test_query_service.py
git commit -m "feat: orchestrate partition count queries"
```

---

### Task 6: Register MCP tools and preserve existing behavior

**Files:**
- Modify: `dlc_mcp/mcp.py`
- Modify: `dlc_mcp/server.py`
- Modify: `dlc_mcp/gateway.py`
- Modify: `tests/test_mcp.py`
- Create: `tests/test_query_mcp_contract.py`

**Interfaces:**
- Register `submit_partition_count_query` with required `table_name` and `partition` object properties.
- Register `get_partition_count_query` with required `query_id`.
- The schemas must have no `sql` property and no production task ID input.
- `_call_tool(store, request, live=None, query_service=None)` delegates to `QueryService` without embedding business logic.

- [ ] **Step 1: Write failing MCP contract tests.**

```python
def test_query_tools_are_listed_without_arbitrary_sql():
    result = handle_request(store, {"id": 1, "method": "tools/list"})
    tools = {item["name"]: item for item in result["result"]["tools"]}
    assert "sql" not in tools["submit_partition_count_query"]["inputSchema"]["properties"]
    assert "query_id" in tools["get_partition_count_query"]["inputSchema"]["required"]


def test_submit_tool_delegates_to_query_service(query_service):
    response = _call_tool(store, request_for_submit(), query_service=query_service)
    assert response["result"]["content"][0]["type"] == "text"
    assert query_service.submissions == [("dws_order_detail", {"ds": "2026-08-10"})]
```

- [ ] **Step 2: Run tests and verify failure.**

Run: `pytest tests/test_query_mcp_contract.py -q`
Expected: FAIL because the tools and service injection are not yet wired.

- [ ] **Step 3: Implement registration and delegation.**

Add only schemas, descriptions, read-only annotations, service construction/injection, and response formatting. Keep existing source resolution and asset tool behavior unchanged. Query execution metadata must identify the WeData executor separately from asset metadata source.

- [ ] **Step 4: Run MCP regression tests.**

Run: `pytest tests/test_query_mcp_contract.py tests/test_mcp.py -q`
Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add dlc_mcp/mcp.py dlc_mcp/server.py dlc_mcp/gateway.py tests/test_mcp.py tests/test_query_mcp_contract.py
git commit -m "feat: expose partition count query tools"
```

---

### Task 7: Add configuration, lifecycle checks, and end-to-end fake coverage

**Files:**
- Modify: `deploy/env.example`
- Create: `tests/test_query_end_to_end.py`
- Create: `docs/superpowers/runbooks/spark-sql-partition-count-rollout.md`

**Interfaces:**
- Configuration is loaded through existing `_load_env_file` behavior.
- The runbook documents dry-run, test-project, and production-gray rollout gates.

- [ ] **Step 1: Write failing lifecycle tests.**

```python
def test_expired_query_returns_query_expired_without_calling_wedata(service, fake_executor, clock):
    job = service.submit_partition_count_query("dws_order_detail", {"ds": "2026-08-10"})
    clock.advance(hours=2)
    result = service.get_partition_count_query(job["query_id"])
    assert result["error_code"] == "QUERY_EXPIRED"
    assert fake_executor.status_calls == []
```

- [ ] **Step 2: Implement verified settings and lifecycle behavior.**

Add only contract-backed names for project, resource group, queue, priority, resource limits, max runtime, concurrency, duplicate interval, result TTL, and status TTL. Keep conservative defaults that refuse submission when required production-safety settings are absent.

- [ ] **Step 3: Write the rollout runbook.**

Document dry-run first, test-project-only submission, whitelist and low concurrency for production gray, evidence to collect, rollback by disabling query submission, and the rule that rollback never cancels production tasks.

- [ ] **Step 4: Run the complete suite.**

Run: `pytest -q`
Expected: PASS with the existing suite and all query tests.

- [ ] **Step 5: Commit.**

```bash
git add deploy/env.example tests/test_query_end_to_end.py docs/superpowers/runbooks/spark-sql-partition-count-rollout.md
git commit -m "docs: add partition count query rollout safeguards"
```

---

## Verification Checklist

- [ ] Contract document names verified WeData operations; no guessed action remains.
- [ ] `query_jobs` migration is idempotent and separate from asset facts.
- [ ] MCP schemas contain no arbitrary SQL field.
- [ ] Missing/unknown table and incomplete/invalid partitions fail before submission.
- [ ] Generated SQL is deterministic, single-table, exact-partition, and second-pass validated.
- [ ] Duplicate requests reuse the existing active query ID.
- [ ] Unknown submission outcome never causes blind duplicate creation.
- [ ] Query resources are isolated and bounded.
- [ ] Status transitions are legal and terminal states are stable.
- [ ] Result parser rejects malformed/non-numeric output.
- [ ] Transport errors, Spark failures, access errors, timeouts, and expiry remain distinguishable.
- [ ] Cancellation, if exposed, targets only recorded query task IDs.
- [ ] Existing asset MCP tests remain green.
- [ ] `pytest -q` passes.
- [ ] No secret, signature, or sensitive header is returned or logged.

## Spec Coverage Review

- Scope and non-goals: Tasks 2, 4, and 6.
- Fixed SQL and injection defense: Task 2.
- Metadata and complete partition validation: Tasks 2 and 5.
- Async WeData execution: Tasks 1 and 4.
- Query state, idempotency, TTL, and UTC: Task 3.
- Resource isolation, quota, timeout, and cancellation: Tasks 4, 5, and 7.
- Stable errors and transport distinction: Tasks 4 and 5.
- MCP contracts: Task 6.
- Unit, service, contract, regression, and integration-style fake tests: Tasks 1-7.
- Dry-run, test project, and production gray rollout: Task 7.
- Unresolved API prerequisites are intentionally a blocking first task, not a placeholder; implementation cannot proceed to external submission until Task 1 produces evidence-backed action/payload mappings.

## Placeholder and Type Consistency Review

- No `TODO`, `TBD`, or unspecified implementation step is used.
- All cross-task types and method names are defined before use.
- The only conditional behavior is explicitly tied to whether the approved contract exposes cancellation.
- The plan never instructs an engineer to guess an API action or reuse a production task.
