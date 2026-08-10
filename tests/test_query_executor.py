import base64
import json
import socket

import pytest

from dlc_mcp.query_executor import QueryExecutionPolicy, QueryExecutor, QueryResultInvalid, QueryTransportUncertain
from dlc_mcp.query_models import ValidatedQuery


class FakeClient:
    def __init__(self):
        self.calls = []
        self.timeout = False
        self.state = 2
        self.result = [["42"]]

    def call(self, action, payload):
        self.calls.append((action, payload))
        if self.timeout:
            raise socket.timeout()
        if action == "CreateTasks":
            return {"Response": {"TaskIdSet": ["task-1"]}}
        if action == "DescribeMCPTask":
            return {"Response": {"TaskInfo": {"State": self.state}}}
        if action == "DescribeMCPTaskResult":
            return {"Response": {"TaskResult": {"State": 2, "ResultSchema": [{"Name": "row_count", "Type": "bigint"}], "ResultSet": json.dumps(self.result)}}}
        return {"Response": {"RequestId": "r"}}


def policy():
    return QueryExecutionPolicy(True, "dw", "DataLakeCatalog", "query-engine", "query-rg", 300, 2, 7200, 3600)


def validated():
    return ValidatedQuery("dw.orders", {"ds": "2026-08-10"}, "SELECT COUNT(*) AS row_count FROM `dw`.`orders` WHERE `ds` = '2026-08-10'", "h", "k")


def test_submit_uses_only_official_dlc_query_action_and_isolated_resource():
    client = FakeClient()
    ref = QueryExecutor(client, policy()).submit_count_query(validated())
    assert ref.task_id == "task-1"
    action, payload = client.calls[-1]
    assert action == "CreateTasks"
    assert payload["Tasks"]["TaskType"] == "SparkSQLTask"
    assert payload["ResourceGroupName"] == "query-rg"
    assert base64.b64decode(payload["Tasks"]["SQL"]).decode() == validated().sql


def test_transport_uncertainty_is_not_spark_failure():
    client = FakeClient()
    client.timeout = True
    with pytest.raises(QueryTransportUncertain):
        QueryExecutor(client, policy()).submit_count_query(validated())


def test_status_result_and_cancel_are_task_scoped():
    client = FakeClient()
    executor = QueryExecutor(client, policy())
    assert executor.get_status("task-1").status == "SUCCEEDED"
    assert executor.get_result("task-1").row_count == 42
    executor.cancel("task-1")
    assert client.calls[-1] == ("CancelTask", {"TaskId": "task-1"})


def test_malformed_result_is_rejected():
    client = FakeClient()
    client.result = [["1", "2"]]
    with pytest.raises(QueryResultInvalid):
        QueryExecutor(client, policy()).get_result("task-1")
