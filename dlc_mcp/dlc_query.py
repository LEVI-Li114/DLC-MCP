import base64
import hashlib
import json
import os
import re
from datetime import datetime, timedelta

from .tencentcloud import TencentCloudClient


STATE_NAMES = {
    -3: "cancelled",
    -1: "failed",
    0: "initializing",
    1: "running",
    2: "succeeded",
    3: "writing_result",
    4: "queued",
}

FORBIDDEN_KEYWORDS = {
    "ALTER", "CACHE", "CALL", "CREATE", "DELETE", "DROP", "GRANT",
    "INSERT", "LOAD", "MERGE", "MSCK", "REFRESH", "REPLACE", "REVOKE",
    "SET", "TRUNCATE", "UNCACHE", "UPDATE", "USE",
}


class QueryValidationError(ValueError):
    pass


def validate_read_only_sql(sql, max_chars=100_000):
    if not isinstance(sql, str) or not sql.strip():
        raise QueryValidationError("sql_required")
    if len(sql) > max_chars:
        raise QueryValidationError("sql_too_long")

    masked = _mask_literals_and_comments(sql)
    semicolons = [match.start() for match in re.finditer(";", masked)]
    if len(semicolons) > 1:
        raise QueryValidationError("multiple_statements_not_allowed")
    if semicolons and masked[semicolons[0] + 1 :].strip():
        raise QueryValidationError("multiple_statements_not_allowed")

    keywords = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", masked.upper())
    is_show_tables = len(keywords) >= 2 and keywords[:2] == ["SHOW", "TABLES"]
    if not keywords or (keywords[0] not in {"SELECT", "WITH"} and not is_show_tables):
        raise QueryValidationError("only_select_with_or_show_tables_allowed")
    if is_show_tables:
        show_keywords = keywords[2:]
        if any(keyword not in {"LIKE"} for keyword in show_keywords) or len(show_keywords) > 1:
            raise QueryValidationError("only_show_tables_or_show_tables_like_allowed")
        if show_keywords and not re.search(r"\bLIKE\s+(?:'|\")", sql, re.IGNORECASE):
            raise QueryValidationError("only_show_tables_or_show_tables_like_allowed")
    forbidden = sorted(set(keywords) & FORBIDDEN_KEYWORDS)
    if forbidden:
        raise QueryValidationError("forbidden_sql_keyword:" + ",".join(forbidden))
    return sql.strip().rstrip(";").rstrip()


def _mask_literals_and_comments(sql):
    chars = list(sql)
    index = 0
    length = len(chars)
    while index < length:
        if sql.startswith("--", index):
            end = sql.find("\n", index + 2)
            end = length if end < 0 else end
            _blank(chars, index, end)
            index = end
            continue
        if sql.startswith("/*", index):
            end = sql.find("*/", index + 2)
            if end < 0:
                raise QueryValidationError("unterminated_comment")
            _blank(chars, index, end + 2)
            index = end + 2
            continue
        if sql[index] in {"'", '"', "`"}:
            quote = sql[index]
            start = index
            index += 1
            while index < length:
                if sql[index] == "\\" and index + 1 < length:
                    index += 2
                    continue
                if sql[index] == quote:
                    if index + 1 < length and sql[index + 1] == quote:
                        index += 2
                        continue
                    index += 1
                    _blank(chars, start, index)
                    break
                index += 1
            else:
                raise QueryValidationError("unterminated_quoted_value")
            continue
        index += 1
    return "".join(chars)


def _blank(chars, start, end):
    for index in range(start, end):
        if chars[index] not in {"\n", "\r"}:
            chars[index] = " "


class DLCQueryService:
    def __init__(self, client=None):
        self.client = client or TencentCloudClient.dlc_from_env()

    def submit(self, sql, database_name="", data_engine_name="", datasource_connection_name="", resource_group_name=""):
        max_chars = int(os.environ.get("DLC_QUERY_MAX_SQL_CHARS", "100000"))
        clean_sql = validate_read_only_sql(sql, max_chars=max_chars)
        task_type = os.environ.get("DLC_QUERY_TASK_TYPE", "spark").strip().lower()
        if task_type not in {"spark", "presto"}:
            raise QueryValidationError("invalid_DLC_QUERY_TASK_TYPE")
        task_key = "SparkSQLTask" if task_type == "spark" else "SQLTask"
        payload = {
            "Task": {
                task_key: {
                    "SQL": base64.b64encode(clean_sql.encode("utf-8")).decode("ascii"),
                    "Config": [],
                }
            }
        }
        options = {
            "DatabaseName": database_name or _query_env("DLC_QUERY_DATABASE", "DLC_QUERY_DATABASE_NAME"),
            "DataEngineName": data_engine_name or _query_env("DLC_QUERY_ENGINE", "DLC_QUERY_DATA_ENGINE_NAME"),
            "DatasourceConnectionName": datasource_connection_name
            or _query_env("DLC_QUERY_DATASOURCE", "DLC_QUERY_DATASOURCE_CONNECTION_NAME")
            or os.environ.get("DLC_CATALOG", "DataLakeCatalog"),
            "ResourceGroupName": resource_group_name or _query_env("DLC_QUERY_RESOURCE_GROUP", "DLC_QUERY_RESOURCE_GROUP_NAME"),
        }
        payload.update({key: value for key, value in options.items() if value})
        response = self.client.call("CreateTask", payload)
        body = _response_body(response)
        return {
            "status": "submitted",
            "task_id": body.get("TaskId", ""),
            "request_id": body.get("RequestId", ""),
            "engine_type": task_type,
            "data_engine_name": options["DataEngineName"],
            "database_name": options["DatabaseName"],
            "sql_sha256": hashlib.sha256(clean_sql.encode("utf-8")).hexdigest(),
        }

    def result(self, task_id, next_token="", max_results=1000):
        if not task_id:
            raise QueryValidationError("task_id_required")
        max_results = int(max_results)
        if not 1 <= max_results <= 1000:
            raise QueryValidationError("max_results_out_of_range")
        payload = {
            "TaskId": task_id,
            "MaxResults": max_results,
            "IsTransformDataType": True,
            "DataFieldCutLen": int(os.environ.get("DLC_QUERY_DATA_FIELD_CUT_LEN", "1000")),
        }
        if next_token:
            payload["NextToken"] = next_token
        body = _response_body(self.client.call("DescribeTaskResult", payload))
        info = body.get("TaskInfo") or {}
        state = int(info.get("State", 0))
        return {
            "task_id": task_id,
            "state": state,
            "status": STATE_NAMES.get(state, "unknown"),
            "progress_percent": info.get("Percentage", 0),
            "message": info.get("OutputMessage", ""),
            "schema": info.get("ResultSchema") or [],
            "rows": _parse_result_set(info.get("ResultSet")),
            "next_token": info.get("NextToken", ""),
            "data_amount": info.get("DataAmount", 0),
            "used_time": info.get("UsedTime", 0),
            "total_time": info.get("TotalTime", 0),
            "output_path": info.get("OutputPath", ""),
            "request_id": body.get("RequestId", ""),
        }

    def resource_usage(
        self,
        task_instance_id,
        include_cost=False,
        cost_task_id="",
        cost_start_time="",
        cost_end_time="",
        cost_limit=10,
    ):
        task_instance_id = (task_instance_id or "").strip()
        if not task_instance_id:
            raise QueryValidationError("task_instance_id_required")
        cost_payload = (
            _cost_analysis_payload(cost_task_id, cost_start_time, cost_end_time, cost_limit)
            if include_cost
            else None
        )
        body = _response_body(
            self.client.call("DescribeTaskResourceUsage", {"TaskInstanceId": task_instance_id})
        )
        core_info = body.get("CoreInfo") or {}
        timestamps = [int(value) for value in (core_info.get("Timestamp") or [])]
        core_usage = [int(value) for value in (core_info.get("CoreUsage") or [])]
        result = {
            "task_instance_id": task_instance_id,
            "timestamps": timestamps,
            "core_usage": core_usage,
            "series": [
                {"timestamp": timestamp, "core_usage": core_usage[index] if index < len(core_usage) else None}
                for index, timestamp in enumerate(timestamps)
            ],
            "request_id": body.get("RequestId", ""),
        }
        if cost_payload is not None:
            result["cost_analysis"] = self._cost_analysis(cost_payload)
        return result

    def delete_tables(self, tables):
        configured_database = _query_env("DLC_QUERY_DATABASE", "DLC_QUERY_DATABASE_NAME")
        results = []
        for table in tables:
            database_name = table.get("database_name") or configured_database
            if not database_name:
                raise QueryValidationError("database_name_required_or_configure_DLC_QUERY_DATABASE")
            payload = {
                "Name": table["table_name"],
                "DbName": database_name,
                "DatasourceConnectionName": table.get("datasource_connection_name")
                or _query_env("DLC_QUERY_DATASOURCE", "DLC_QUERY_DATASOURCE_CONNECTION_NAME")
                or os.environ.get("DLC_CATALOG", "DataLakeCatalog"),
                "DeleteData": False,
            }
            try:
                response = self.client.call("DropDMSTable", payload)
                body = _response_body(response)
                if not isinstance(response, dict) or not isinstance(response.get("Response"), dict) or not body:
                    raise RuntimeError("invalid_delete_response")
                results.append({
                    **table,
                    "status": "api_accepted",
                    "request_id": body.get("RequestId", ""),
                    "verification": "not_performed",
                    "database_name_used": database_name,
                    "datasource_connection_name_used": payload["DatasourceConnectionName"],
                })
                try:
                    verification = self._verify_table_absent(
                        table["table_name"], database_name, payload["DatasourceConnectionName"]
                    )
                    results[-1]["verification"] = verification["status"]
                    results[-1]["verification_task_id"] = verification["task_id"]
                    results[-1]["verification_request_id"] = verification["request_id"]
                    if verification["status"] == "table_still_exists":
                        results[-1]["status"] = "api_accepted_table_still_exists"
                    elif verification["status"] != "verified_absent":
                        results[-1]["status"] = "verification_failed"
                        results[-1]["verification_error"] = verification.get("error", verification["status"])
                except Exception as exc:
                    results[-1]["status"] = "verification_failed"
                    results[-1]["verification"] = "failed"
                    results[-1]["verification_error"] = str(exc)
            except Exception as exc:
                results.append({**table, "status": "failed", "error": str(exc)})
        status = "verified" if all(item["status"] == "api_accepted" and item.get("verification") == "verified_absent" for item in results) else "partial"
        return {"status": status, "results": results}

    def _verify_table_absent(self, table_name, database_name, datasource_connection_name):
        escaped_table = table_name.replace("'", "''")
        submitted = self.submit(
            f"SHOW TABLES LIKE '{escaped_table}'",
            database_name=database_name,
            datasource_connection_name=datasource_connection_name,
        )
        task_id = submitted["task_id"]
        if not task_id:
            raise RuntimeError("verification_task_id_missing")
        result = self.result(task_id)
        if result["status"] != "succeeded":
            return {
                "status": "verification_failed",
                "task_id": task_id,
                "request_id": result["request_id"],
                "error": f"verification_query_{result['status']}",
            }
        rows = result["rows"]
        exists = bool(rows)
        return {
            "status": "table_still_exists" if exists else "verified_absent",
            "task_id": task_id,
            "request_id": result["request_id"],
        }

    def task_cost_analysis(self, task_id, start_time="", end_time="", limit=10):
        return self._cost_analysis(_cost_analysis_payload(task_id, start_time, end_time, limit))

    def _cost_analysis(self, payload):
        body = _response_body(self.client.call("DescribeTasksAnalysis", payload))
        tasks = [_analysis_task(item) for item in (body.get("TaskList") or [])]
        return {
            "task_id": payload["Filters"][0]["Values"][0],
            "start_time": payload["StartTime"],
            "end_time": payload["EndTime"],
            "total_count": body.get("TotalCount", 0),
            "tasks": tasks,
            "request_id": body.get("RequestId", ""),
        }


def _cost_analysis_payload(task_id, start_time, end_time, limit):
    task_id = (task_id or "").strip()
    if not task_id:
        raise QueryValidationError("cost_task_id_required")
    limit = int(limit or 10)
    if not 1 <= limit <= 100:
        raise QueryValidationError("cost_limit_out_of_range")
    window_start, window_end = _analysis_time_window(start_time, end_time)
    return {
        "Filters": [{"Name": "task-id", "Values": [task_id]}],
        "Limit": limit,
        "Offset": 0,
        "SortBy": "task-time-sum",
        "Sorting": "desc",
        "StartTime": window_start,
        "EndTime": window_end,
    }


def _analysis_time_window(start_time, end_time):
    now = datetime.now()
    try:
        window_end = datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S") if end_time else now
        window_start = datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S") if start_time else window_end - timedelta(days=7)
    except ValueError:
        raise QueryValidationError("invalid_analysis_time_format")
    if window_start >= window_end:
        raise QueryValidationError("invalid_analysis_time_range")
    if window_end - window_start > timedelta(days=30):
        raise QueryValidationError("analysis_time_range_exceeds_30_days")
    return window_start.strftime("%Y-%m-%d %H:%M:%S"), window_end.strftime("%Y-%m-%d %H:%M:%S")


def _analysis_task(item):
    item = item or {}
    return {
        "id": item.get("Id", ""),
        "state": item.get("State", 0),
        "data_engine_name": item.get("DataEngineName", ""),
        "instance_start_time": item.get("InstanceStartTime", 0),
        "instance_complete_time": item.get("InstanceCompleteTime", 0),
        "job_time_sum_ms": item.get("JobTimeSum", 0),
        "task_time_sum_seconds": item.get("TaskTimeSum", 0),
        "input_bytes_sum": item.get("InputBytesSum", 0),
        "shuffle_read_bytes_sum": item.get("ShuffleReadBytesSum", 0),
        "analysis_status": item.get("AnalysisStatus", ""),
    }


def _response_body(response):
    body = (response or {}).get("Response") or {}
    error = body.get("Error")
    if error:
        raise RuntimeError(f"dlc_api_error:{error.get('Code', 'unknown')}:{error.get('Message', '')}")
    return body


def _query_env(primary, legacy):
    return os.environ.get(primary, "") or os.environ.get(legacy, "")


def _parse_result_set(value):
    if value in (None, ""):
        return []
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return value
