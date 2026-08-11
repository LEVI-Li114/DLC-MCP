import sqlite3
from datetime import datetime, timedelta, timezone

from dlc_mcp.query_models import QueryJob, QueryStatusPatch
from dlc_mcp.query_store import QueryStore


def make_job(query_id="q-1", key="key", status="PENDING"):
    now = datetime(2026, 8, 10, tzinfo=timezone.utc)
    return QueryJob(query_id, "dw.orders", {"ds": "2026-08-10"}, "hash", key, status, now, now, now + timedelta(hours=2))


def test_query_jobs_schema_persists_audit_identity():
    store = QueryStore(sqlite3.connect(":memory:"))
    store.init_schema()
    job = make_job()
    store.create_job(job)
    stored = store.get_job(job.query_id)
    assert stored.query_id == job.query_id
    assert stored.idempotency_key == job.idempotency_key


def test_expired_result_is_removed_without_deleting_live_job():
    store = QueryStore(sqlite3.connect(":memory:"))
    store.init_schema()
    job = make_job(status="SUCCEEDED")
    store.create_job(job)
    past = job.created_at - timedelta(seconds=1)
    store.update_status(job.query_id, QueryStatusPatch("SUCCEEDED", job.created_at, row_count=7, result_expires_at=past))
    assert store.delete_expired_results(job.created_at) == 1
    assert store.get_job(job.query_id).status == "SUCCEEDED"
    assert store.get_job(job.query_id).row_count is None
