import json
import sqlite3
from datetime import datetime, timezone

from .query_models import QueryJob, QueryStatusPatch


ACTIVE_STATUSES = {"PENDING", "SUBMITTED", "RUNNING", "SUBMISSION_UNCERTAIN"}
TERMINAL_STATUSES = {"SUCCEEDED", "FAILED", "CANCELLED", "TIMEOUT", "EXPIRED"}


class QueryStoreError(RuntimeError):
    pass


class QueryStore:
    def __init__(self, conn):
        self.conn = conn
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("pragma busy_timeout = 30000")

    def init_schema(self) -> None:
        self.conn.executescript(
            """
            create table if not exists query_jobs (
                query_id text primary key,
                table_name text not null,
                partition_json text not null,
                sql_hash text not null,
                idempotency_key text not null,
                status text not null,
                external_task_id text not null default '',
                created_at text not null,
                updated_at text not null,
                submitted_at text,
                completed_at text,
                expires_at text not null,
                result_expires_at text,
                row_count integer,
                error_code text not null default '',
                error_message text not null default ''
            );
            create index if not exists idx_query_jobs_status on query_jobs(status);
            create index if not exists idx_query_jobs_expires on query_jobs(expires_at, result_expires_at);
            create index if not exists idx_query_jobs_idempotency on query_jobs(idempotency_key, created_at);
            """
        )
        self.conn.commit()

    def create_job(self, job: QueryJob) -> None:
        try:
            with self.conn:
                self.conn.execute(
                    """insert into query_jobs
                    (query_id, table_name, partition_json, sql_hash, idempotency_key, status,
                     external_task_id, created_at, updated_at, submitted_at, completed_at,
                     expires_at, result_expires_at, row_count, error_code, error_message)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (job.query_id, job.table_name, json.dumps(job.partition, sort_keys=True), job.sql_hash,
                     job.idempotency_key, job.status, job.external_task_id, _iso(job.created_at),
                     _iso(job.updated_at), _iso(job.submitted_at), _iso(job.completed_at),
                     _iso(job.expires_at), _iso(job.result_expires_at), job.row_count,
                     job.error_code, job.error_message),
                )
        except sqlite3.Error as exc:
            raise QueryStoreError("query state could not be persisted") from exc

    def get_job(self, query_id: str):
        row = self.conn.execute("select * from query_jobs where query_id = ?", (query_id,)).fetchone()
        return _job(row) if row else None

    def count_active(self, now: datetime) -> int:
        placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
        return self.conn.execute(
            f"select count(*) from query_jobs where status in ({placeholders}) and expires_at > ?",
            (*sorted(ACTIVE_STATUSES), _iso(now)),
        ).fetchone()[0]

    def update_submission(self, query_id: str, external_task_id: str, submitted_at: datetime) -> None:
        with self.conn:
            self.conn.execute(
                "update query_jobs set external_task_id = ?, status = 'SUBMITTED', submitted_at = ?, updated_at = ? where query_id = ?",
                (external_task_id, _iso(submitted_at), _iso(submitted_at), query_id),
            )

    def update_status(self, query_id: str, patch: QueryStatusPatch) -> QueryJob:
        current = self.get_job(query_id)
        if not current:
            raise QueryStoreError("query job was not found")
        if current.status in TERMINAL_STATUSES and patch.status != current.status:
            return current
        with self.conn:
            self.conn.execute(
                """update query_jobs set status = ?, updated_at = ?, completed_at = coalesce(?, completed_at),
                result_expires_at = coalesce(?, result_expires_at), row_count = coalesce(?, row_count),
                error_code = ?, error_message = ? where query_id = ?""",
                (patch.status, _iso(patch.updated_at), _iso(patch.completed_at), _iso(patch.result_expires_at),
                 patch.row_count, patch.error_code, patch.error_message, query_id),
            )
        return self.get_job(query_id)

    def expire_jobs(self, now: datetime) -> int:
        with self.conn:
            cursor = self.conn.execute(
                f"update query_jobs set status = 'EXPIRED', updated_at = ? where expires_at <= ? and status not in ({','.join('?' for _ in TERMINAL_STATUSES)})",
                (_iso(now), _iso(now), *sorted(TERMINAL_STATUSES)),
            )
        return cursor.rowcount

    def delete_expired_results(self, now: datetime) -> int:
        with self.conn:
            cursor = self.conn.execute(
                "update query_jobs set row_count = null where row_count is not null and result_expires_at <= ?",
                (_iso(now),),
            )
        return cursor.rowcount


def _iso(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _dt(value):
    return datetime.fromisoformat(value) if value else None


def _job(row):
    return QueryJob(
        query_id=row["query_id"], table_name=row["table_name"], partition=json.loads(row["partition_json"]),
        sql_hash=row["sql_hash"], idempotency_key=row["idempotency_key"], status=row["status"],
        external_task_id=row["external_task_id"], created_at=_dt(row["created_at"]), updated_at=_dt(row["updated_at"]),
        submitted_at=_dt(row["submitted_at"]), completed_at=_dt(row["completed_at"]), expires_at=_dt(row["expires_at"]),
        result_expires_at=_dt(row["result_expires_at"]), row_count=row["row_count"],
        error_code=row["error_code"], error_message=row["error_message"],
    )
