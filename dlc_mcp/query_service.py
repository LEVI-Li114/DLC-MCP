import os
import uuid
from datetime import datetime, timedelta, timezone

from .query_executor import QueryExecutorError, QueryResultInvalid, QueryTransportUncertain
from .query_models import QueryJob, QueryStatusPatch
from .query_store import QueryStoreError
from .query_validation import QueryValidationError, make_validated_query, normalize_table_name, validate_partition


class QueryServiceError(RuntimeError):
    def __init__(self, code, message):
        self.code = code
        self.safe_message = message
        super().__init__(f"{code}: {message}")


def utc_now():
    return datetime.now(timezone.utc)


class QueryService:
    def __init__(self, store, metadata, executor, policy, clock=utc_now):
        self.store = store
        self.metadata = metadata
        self.executor = executor
        self.policy = policy
        self.clock = clock

    def submit_partition_count_query(self, table_name: str, partition: dict[str, str]) -> dict:
        now = self.clock()
        if not self.policy.enabled:
            raise QueryServiceError("QUERY_DISABLED", "partition count queries are disabled")
        requested = normalize_table_name(table_name)
        lookup_name = requested.split(".")[-1]
        profile = self.metadata.get_table_profile(lookup_name)
        if profile.get("error"):
            raise QueryServiceError("INVALID_TABLE", "table was not found in validated metadata")
        table = profile.get("table") or {}
        if not table.get("is_active", 1):
            raise QueryServiceError("INVALID_TABLE", "table is inactive")
        default_project = os.environ.get("WEDATA_PROJECT_ID", "")
        if default_project and table.get("project_id") and table.get("project_id") != default_project:
            raise QueryServiceError("INVALID_TABLE", "table is outside the default WeData project")
        database = table.get("database") or self.policy.database_name
        if database != self.policy.database_name:
            raise QueryServiceError("INVALID_TABLE", "table is outside the configured query database")
        partition_profile = self.metadata.get_table_partition_profile(lookup_name)
        normalized_partition = validate_partition(partition_profile, partition)
        table_identifier = f"{database}.{table.get('name') or lookup_name}"
        validated = make_validated_query(table_identifier, normalized_partition, database)
        existing = self.store.find_active_by_idempotency_key(validated.idempotency_key, now)
        if existing:
            return self._response(existing, duplicate=True)
        if self.store.count_active(now) >= self.policy.max_concurrent_queries:
            raise QueryServiceError("QUERY_QUOTA_EXCEEDED", "too many partition queries are active")
        job = QueryJob(
            query_id=f"q-{uuid.uuid4().hex}", table_name=table_identifier, partition=normalized_partition,
            sql_hash=validated.sql_hash, idempotency_key=validated.idempotency_key, status="PENDING",
            created_at=now, updated_at=now, expires_at=now + timedelta(seconds=self.policy.status_ttl_seconds),
        )
        try:
            self.store.create_job(job)
        except QueryStoreError as exc:
            raise QueryServiceError("QUERY_STORE_UNAVAILABLE", "query state could not be persisted") from exc
        try:
            ref = self.executor.submit_count_query(validated)
        except QueryTransportUncertain:
            job = self.store.update_status(job.query_id, QueryStatusPatch("SUBMISSION_UNCERTAIN", now, error_code="SUBMISSION_UNCERTAIN", error_message="submission outcome is uncertain"))
            return self._response(job)
        except QueryExecutorError as exc:
            job = self.store.update_status(job.query_id, QueryStatusPatch("FAILED", now, completed_at=now, error_code=exc.code, error_message=str(exc)[:300]))
            return self._response(job)
        self.store.update_submission(job.query_id, ref.task_id, now)
        return self._response(self.store.get_job(job.query_id))

    def get_partition_count_query(self, query_id: str) -> dict:
        now = self.clock()
        job = self.store.get_job(query_id)
        if not job:
            raise QueryServiceError("QUERY_NOT_FOUND", "query id was not found")
        if now >= job.expires_at:
            if job.status in {"SUCCEEDED", "FAILED", "CANCELLED", "TIMEOUT", "EXPIRED"}:
                return {**self._response(job), "row_count": None, "error_code": "QUERY_EXPIRED", "error_message": "query status expired"}
            if job.status not in {"SUCCEEDED", "FAILED", "CANCELLED", "TIMEOUT", "EXPIRED"} and job.external_task_id:
                try:
                    self.executor.cancel(job.external_task_id)
                except Exception:
                    pass
            job = self.store.update_status(query_id, QueryStatusPatch("EXPIRED", now, completed_at=now, error_code="QUERY_EXPIRED", error_message="query status expired"))
            return self._response(job)
        if job.status in {"PENDING", "SUBMISSION_UNCERTAIN"} or not job.external_task_id:
            return self._response(job)
        if job.status in {"SUCCEEDED", "FAILED", "CANCELLED", "TIMEOUT", "EXPIRED"}:
            if job.status == "SUCCEEDED" and job.result_expires_at and now >= job.result_expires_at:
                return {**self._response(job), "row_count": None, "error_code": "RESULT_EXPIRED"}
            return self._response(job)
        if job.submitted_at and now - job.submitted_at >= timedelta(seconds=self.policy.max_runtime_seconds):
            try:
                self.executor.cancel(job.external_task_id)
            except Exception:
                pass
            job = self.store.update_status(query_id, QueryStatusPatch("TIMEOUT", now, completed_at=now, error_code="QUERY_TIMEOUT", error_message="query exceeded maximum runtime"))
            return self._response(job)
        try:
            external = self.executor.get_status(job.external_task_id)
        except Exception:
            return {**self._response(job), "error_code": "STATUS_UNAVAILABLE"}
        if external.status == "SUCCEEDED":
            try:
                result = self.executor.get_result(job.external_task_id)
            except QueryResultInvalid:
                job = self.store.update_status(query_id, QueryStatusPatch("FAILED", now, completed_at=now, error_code="RESULT_INVALID", error_message="query result was malformed"))
            except Exception:
                return {**self._response(job), "error_code": "RESULT_UNAVAILABLE", "error_message": "query result is temporarily unavailable"}
            else:
                job = self.store.update_status(query_id, QueryStatusPatch("SUCCEEDED", now, completed_at=now, result_expires_at=now + timedelta(seconds=self.policy.result_ttl_seconds), row_count=result.row_count))
        elif external.status in {"FAILED", "CANCELLED"}:
            code = "SPARK_FAILED" if external.status == "FAILED" else "QUERY_CANCELLED"
            job = self.store.update_status(query_id, QueryStatusPatch(external.status, now, completed_at=now, error_code=code, error_message=external.message or external.status.lower()))
        else:
            job = self.store.update_status(query_id, QueryStatusPatch(external.status, now))
        return self._response(job)

    def cancel_partition_count_query(self, query_id: str) -> dict:
        now = self.clock()
        job = self.store.get_job(query_id)
        if not job:
            raise QueryServiceError("QUERY_NOT_FOUND", "query id was not found")
        if job.status in {"SUCCEEDED", "FAILED", "CANCELLED", "TIMEOUT", "EXPIRED"}:
            return self._response(job)
        if not job.external_task_id:
            raise QueryServiceError("CANCEL_UNAVAILABLE", "query submission is not confirmed")
        self.executor.cancel(job.external_task_id)
        job = self.store.update_status(query_id, QueryStatusPatch("CANCELLED", now, completed_at=now, error_code="QUERY_CANCELLED", error_message="query was cancelled"))
        return self._response(job)

    @staticmethod
    def _response(job, duplicate=False):
        return {
            "query_id": job.query_id,
            "table_name": job.table_name,
            "partition": job.partition,
            "status": job.status,
            "row_count": job.row_count,
            "error_code": job.error_code,
            "error_message": job.error_message,
            "created_at": job.created_at.isoformat(),
            "updated_at": job.updated_at.isoformat(),
            "duplicate": duplicate,
        }
