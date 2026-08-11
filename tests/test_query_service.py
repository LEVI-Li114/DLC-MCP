import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from dlc_mcp.assets import AssetStore
from dlc_mcp.query_executor import QueryExecutionPolicy
from dlc_mcp.query_models import CountResult, ExternalStatus, ExternalTaskRef
from dlc_mcp.query_service import QueryService, QueryServiceError
from dlc_mcp.query_store import QueryStore


class FakeExecutor:
    def __init__(self):
        self.submissions = []
        self.status = "RUNNING"
        self.cancelled = []

    def submit_count_query(self, query):
        self.submissions.append(query)
        return ExternalTaskRef("task-1")

    def get_status(self, task_id):
        return ExternalStatus(self.status, 2 if self.status == "SUCCEEDED" else 1)

    def get_result(self, task_id):
        return CountResult(123)

    def cancel(self, task_id):
        self.cancelled.append(task_id)


class Clock:
    def __init__(self):
        self.now = datetime(2026, 8, 10, tzinfo=timezone.utc)

    def __call__(self):
        return self.now


def make_service():
    asset_store = AssetStore(sqlite3.connect(":memory:"))
    asset_store.init_schema()
    asset_store.upsert_table({"name": "orders", "database": "dw", "raw": {"PartitionKeys": [{"Name": "ds"}]}})
    asset_store.upsert_column("orders", "ds", "string", "", 1)
    query_store = QueryStore(asset_store.conn)
    query_store.init_schema()
    executor = FakeExecutor()
    clock = Clock()
    policy = QueryExecutionPolicy(True, "dw", "DataLakeCatalog", "engine", "rg", 300, 2, 7200, 3600)
    return QueryService(query_store, asset_store, executor, policy, clock), executor, clock


def test_missing_table_does_not_submit():
    service, executor, _ = make_service()
    with pytest.raises(QueryServiceError, match="INVALID_TABLE"):
        service.submit_partition_count_query("missing", {"ds": "2026-08-10"})
    assert executor.submissions == []


def test_repeated_submission_creates_a_new_query():
    service, executor, _ = make_service()
    first = service.submit_partition_count_query("orders", {"ds": "2026-08-10"})
    second = service.submit_partition_count_query("orders", {"ds": "2026-08-10"})
    assert second["query_id"] != first["query_id"]
    assert second["duplicate"] is False
    assert len(executor.submissions) == 2


def test_repeated_submission_still_obeys_concurrency_limit():
    service, executor, _ = make_service()
    service.policy = QueryExecutionPolicy(True, "dw", "DataLakeCatalog", "engine", "rg", 300, 1, 7200, 3600)
    service.submit_partition_count_query("orders", {"ds": "2026-08-10"})
    with pytest.raises(QueryServiceError, match="QUERY_QUOTA_EXCEEDED"):
        service.submit_partition_count_query("orders", {"ds": "2026-08-10"})
    assert len(executor.submissions) == 1


def test_success_fetches_validated_count():
    service, executor, _ = make_service()
    job = service.submit_partition_count_query("orders", {"ds": "2026-08-10"})
    executor.status = "SUCCEEDED"
    result = service.get_partition_count_query(job["query_id"])
    assert result["status"] == "SUCCEEDED"
    assert result["row_count"] == 123


def test_runtime_limit_cancels_only_recorded_query_task():
    service, executor, clock = make_service()
    job = service.submit_partition_count_query("orders", {"ds": "2026-08-10"})
    clock.now += timedelta(seconds=301)
    result = service.get_partition_count_query(job["query_id"])
    assert result["status"] == "TIMEOUT"
    assert executor.cancelled == ["task-1"]
