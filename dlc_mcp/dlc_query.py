import base64
import hashlib
import json
import os
import re

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
    if not keywords or keywords[0] not in {"SELECT", "WITH"}:
        raise QueryValidationError("only_select_or_with_allowed")
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
            "DatabaseName": database_name or os.environ.get("DLC_QUERY_DATABASE_NAME", ""),
            "DataEngineName": data_engine_name or os.environ.get("DLC_QUERY_DATA_ENGINE_NAME", ""),
            "DatasourceConnectionName": datasource_connection_name
            or os.environ.get("DLC_QUERY_DATASOURCE_CONNECTION_NAME", os.environ.get("DLC_CATALOG", "DataLakeCatalog")),
            "ResourceGroupName": resource_group_name or os.environ.get("DLC_QUERY_RESOURCE_GROUP_NAME", ""),
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


def _response_body(response):
    body = (response or {}).get("Response") or {}
    error = body.get("Error")
    if error:
        raise RuntimeError(f"dlc_api_error:{error.get('Code', 'unknown')}:{error.get('Message', '')}")
    return body


def _parse_result_set(value):
    if value in (None, ""):
        return []
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return value
