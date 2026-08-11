import base64
import json
import unittest
from unittest.mock import patch

from dlc_mcp.dlc_query import DLCQueryService, QueryValidationError, validate_read_only_sql


class FakeDLCClient:
    def __init__(self):
        self.calls = []

    def call(self, action, payload):
        self.calls.append((action, payload))
        if action == "CreateTask":
            return {"Response": {"TaskId": "task-123", "RequestId": "request-1"}}
        return {
            "Response": {
                "RequestId": "request-2",
                "TaskInfo": {
                    "State": 2,
                    "Percentage": 100,
                    "ResultSchema": [{"Name": "id", "Type": "bigint"}],
                    "ResultSet": json.dumps([{"id": 1}, {"id": 2}]),
                    "NextToken": "next-page",
                    "UsedTime": 12,
                },
            }
        }


class ReadOnlySQLValidationTest(unittest.TestCase):
    def test_allows_select_with_full_outer_join(self):
        sql = "select a.id from a full outer join b on a.id = b.id;"
        self.assertEqual(validate_read_only_sql(sql), sql[:-1])

    def test_allows_cte_and_ignores_keywords_in_literals_comments_and_identifiers(self):
        sql = """-- DELETE is documentation
        WITH src AS (SELECT 'drop table x' AS `insert`)
        SELECT * FROM src"""
        self.assertEqual(validate_read_only_sql(sql), sql.strip())

    def test_rejects_mutation_and_multiple_statements(self):
        invalid = (
            "INSERT INTO x SELECT 1",
            "WITH x AS (SELECT 1) DELETE FROM y",
            "SELECT 1; SELECT 2",
            "DROP TABLE x",
        )
        for sql in invalid:
            with self.subTest(sql=sql), self.assertRaises(QueryValidationError):
                validate_read_only_sql(sql)

    def test_rejects_unterminated_literals_and_comments(self):
        for sql in ("SELECT 'oops", "SELECT 1 /* oops"):
            with self.subTest(sql=sql), self.assertRaises(QueryValidationError):
                validate_read_only_sql(sql)


class DLCQueryServiceTest(unittest.TestCase):
    def test_submits_base64_spark_sql_with_configured_context(self):
        client = FakeDLCClient()
        service = DLCQueryService(client)
        with patch.dict(
            "os.environ",
            {
                "DLC_QUERY_TASK_TYPE": "spark",
                "DLC_QUERY_DATA_ENGINE_NAME": "spark-engine",
                "DLC_QUERY_DATABASE_NAME": "crm",
                "DLC_QUERY_DATASOURCE_CONNECTION_NAME": "DataLakeCatalog",
            },
            clear=False,
        ):
            result = service.submit("SELECT 1")

        action, payload = client.calls[0]
        encoded = payload["Task"]["SparkSQLTask"]["SQL"]
        self.assertEqual(action, "CreateTask")
        self.assertEqual(base64.b64decode(encoded).decode("utf-8"), "SELECT 1")
        self.assertEqual(payload["DataEngineName"], "spark-engine")
        self.assertEqual(payload["DatabaseName"], "crm")
        self.assertEqual(result["task_id"], "task-123")

    def test_reads_paginated_task_result(self):
        client = FakeDLCClient()
        result = DLCQueryService(client).result("task-123", next_token="page-1", max_results=20)

        action, payload = client.calls[0]
        self.assertEqual(action, "DescribeTaskResult")
        self.assertEqual(payload["TaskId"], "task-123")
        self.assertEqual(payload["NextToken"], "page-1")
        self.assertEqual(payload["MaxResults"], 20)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["rows"], [{"id": 1}, {"id": 2}])
        self.assertEqual(result["next_token"], "next-page")


if __name__ == "__main__":
    unittest.main()
