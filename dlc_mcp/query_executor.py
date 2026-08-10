import base64
import json
import os
import socket
import urllib.error

from dataclasses import dataclass

from .query_models import CountResult, ExternalStatus, ExternalTaskRef, ValidatedQuery


class QueryExecutorError(RuntimeError):
    code = "EXECUTION_ERROR"


class QueryTransportUncertain(QueryExecutorError):
    code = "SUBMISSION_UNCERTAIN"


class QueryResultInvalid(QueryExecutorError):
    code = "RESULT_INVALID"


@dataclass(frozen=True)
class QueryExecutionPolicy:
    enabled: bool
    database_name: str
    datasource_connection_name: str
    data_engine_name: str
    resource_group_name: str
    max_runtime_seconds: int
    max_concurrent_queries: int
    status_ttl_seconds: int
    result_ttl_seconds: int

    @classmethod
    def from_env(cls):
        policy = cls(
            enabled=os.environ.get("DLC_QUERY_ENABLED", "0") == "1",
            database_name=os.environ.get("DLC_QUERY_DATABASE", ""),
            datasource_connection_name=os.environ.get("DLC_QUERY_DATASOURCE", "DataLakeCatalog"),
            data_engine_name=os.environ.get("DLC_QUERY_ENGINE", ""),
            resource_group_name=os.environ.get("DLC_QUERY_RESOURCE_GROUP", ""),
            max_runtime_seconds=_bounded_int("DLC_QUERY_MAX_RUNTIME_SECONDS", 300, 30, 3600),
            max_concurrent_queries=_bounded_int("DLC_QUERY_MAX_CONCURRENT", 2, 1, 20),
            status_ttl_seconds=_bounded_int("DLC_QUERY_STATUS_TTL_SECONDS", 7200, 300, 86400),
            result_ttl_seconds=_bounded_int("DLC_QUERY_RESULT_TTL_SECONDS", 3600, 60, 86400),
        )
        if policy.enabled:
            missing = []
            if not policy.database_name:
                missing.append("DLC_QUERY_DATABASE")
            if not policy.resource_group_name:
                missing.append("DLC_QUERY_RESOURCE_GROUP")
            if missing:
                raise RuntimeError("missing required safe query settings: " + ", ".join(missing))
        return policy


class QueryExecutor:
    """The only boundary that submits isolated Spark SQL queries to DLC."""

    def __init__(self, client, policy: QueryExecutionPolicy):
        self.client = client
        self.policy = policy

    def submit_count_query(self, validated_query: ValidatedQuery) -> ExternalTaskRef:
        if not self.policy.enabled:
            raise QueryExecutorError("query submission is disabled")
        payload = {
            "Tasks": {
                "TaskType": "SparkSQLTask",
                "FailureTolerance": "Terminate",
                "SQL": base64.b64encode(validated_query.sql.encode("utf-8")).decode("ascii"),
                "Config": [],
            },
            "DatabaseName": self.policy.database_name,
            "DatasourceConnectionName": self.policy.datasource_connection_name,
            "ResourceGroupName": self.policy.resource_group_name,
        }
        if self.policy.data_engine_name:
            payload["DataEngineName"] = self.policy.data_engine_name
        try:
            response = self.client.call("CreateTasks", payload)
        except (TimeoutError, socket.timeout, urllib.error.URLError) as exc:
            raise QueryTransportUncertain("query submission outcome is uncertain") from exc
        except Exception as exc:
            raise QueryExecutorError("query submission failed") from exc
        task_ids = ((response.get("Response") or {}).get("TaskIdSet") or []) if isinstance(response, dict) else []
        if len(task_ids) != 1 or not task_ids[0]:
            raise QueryResultInvalid("DLC submission returned an invalid task id")
        return ExternalTaskRef(str(task_ids[0]))

    def get_status(self, task_id: str) -> ExternalStatus:
        response = self.client.call("DescribeMCPTask", {"TaskId": task_id})
        info = (response.get("Response") or {}).get("TaskInfo") or {}
        state = info.get("State")
        status = {0: "SUBMITTED", 1: "RUNNING", 2: "SUCCEEDED", 3: "RUNNING", 4: "SUBMITTED", -1: "FAILED", -3: "CANCELLED"}.get(state)
        if status is None:
            raise QueryExecutorError("DLC returned an unknown query state")
        return ExternalStatus(status, state, _safe_message(info.get("OutputMessage")))

    def get_result(self, task_id: str) -> CountResult:
        response = self.client.call("DescribeMCPTaskResult", {"TaskId": task_id})
        info = (response.get("Response") or {}).get("TaskInfo") or (response.get("Response") or {}).get("Result") or {}
        if info.get("State") not in (None, 2):
            raise QueryResultInvalid("query result is not in a successful state")
        schema = info.get("ResultSchema") or []
        if len(schema) != 1 or str(schema[0].get("Name") or "").lower() != "row_count":
            raise QueryResultInvalid("query result schema is invalid")
        raw = info.get("ResultSet")
        try:
            rows = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError) as exc:
            raise QueryResultInvalid("query result is not valid JSON") from exc
        if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], list) or len(rows[0]) != 1:
            raise QueryResultInvalid("query result must contain exactly one row and one column")
        value = rows[0][0]
        if isinstance(value, bool) or not isinstance(value, (int, str)) or not str(value).isdigit():
            raise QueryResultInvalid("row_count is not a non-negative integer")
        return CountResult(int(value))

    def cancel(self, task_id: str) -> None:
        self.client.call("CancelTask", {"TaskId": task_id})


def _bounded_int(name, default, minimum, maximum):
    value = int(os.environ.get(name, str(default)))
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}")
    return value


def _safe_message(value):
    text = str(value or "")
    return text[:300] if text else ""
