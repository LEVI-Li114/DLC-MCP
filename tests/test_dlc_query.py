import base64
import json
import unittest
from unittest.mock import patch

from dlc_mcp.dlc_query import DLCQueryService, QueryValidationError, validate_read_only_sql


class FakeDLCClient:
    def __init__(self):
        self.calls = []
        self.keep_table = False

    def call(self, action, payload):
        self.calls.append((action, payload))
        if action == "CreateTask":
            encoded_sql = next(iter(payload["Task"].values()))["SQL"]
            sql = base64.b64decode(encoded_sql).decode("utf-8")
            task_id = "verify-task" if sql.startswith("SHOW TABLES") else "task-123"
            return {"Response": {"TaskId": task_id, "RequestId": "request-1"}}
        if action == "DescribeTaskResult" and payload["TaskId"] == "verify-task":
            result_set = json.dumps([{"tableName": "api-still-there"}]) if self.keep_table else "[]"
            return {
                "Response": {
                    "RequestId": "verify-result-request",
                    "TaskInfo": {
                        "State": 2,
                        "Percentage": 100,
                        "ResultSchema": [],
                        "ResultSet": result_set,
                    },
                }
            }
        if action == "DescribeTaskResult":
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
        if action == "DropDMSTable":
            if payload["Name"] == "api-still-there":
                self.keep_table = True
            return {"Response": {"RequestId": "request-2"}}
        if action == "DescribeTaskResourceUsage":
            return {
                "Response": {
                    "RequestId": "request-3",
                    "CoreInfo": {
                        "Timestamp": [1750238853000, 1750238854000],
                        "CoreUsage": [1, 3],
                    },
                }
            }
        if action == "DescribeTasksAnalysis":
            return {
                "Response": {
                    "RequestId": "request-4",
                    "TotalCount": 1,
                    "TaskList": [
                        {
                            "Id": "67ea3d234006dc901",
                            "State": 2,
                            "DataEngineName": "super_spark_270",
                            "InstanceStartTime": 1733842361290,
                            "InstanceCompleteTime": 1733842401892,
                            "JobTimeSum": 35589,
                            "TaskTimeSum": 403,
                            "InputBytesSum": 20648020108,
                            "ShuffleReadBytesSum": 0,
                            "AnalysisStatus": "[\"SPARK-OutputSmallFile\"]",
                        }
                    ],
                }
            }
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

    def test_allows_show_tables_like_for_deletion_verification(self):
        sql = "SHOW TABLES LIKE 'tmp_w547_w1'"
        self.assertEqual(validate_read_only_sql(sql), sql)

    def test_rejects_other_show_statements(self):
        for sql in (
            "SHOW DATABASES",
            "SHOW TABLES IN db",
            "SHOW TABLES LIKE x",
            "SHOW TABLES LIKE 'x' LIKE 'y'",
            "SHOW TABLES LIKE 'x'; DROP TABLE y",
        ):
            with self.subTest(sql=sql), self.assertRaises(QueryValidationError):
                validate_read_only_sql(sql)

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
                "DLC_QUERY_ENGINE": "spark-engine",
                "DLC_QUERY_DATABASE": "crm",
                "DLC_QUERY_DATASOURCE": "DataLakeCatalog",
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

    def test_deletes_tables_using_configured_database_and_catalog(self):
        client = FakeDLCClient()
        service = DLCQueryService(client)
        with patch.dict(
            "os.environ",
            {"DLC_QUERY_DATABASE": "configured_db", "DLC_QUERY_DATASOURCE": "configured_catalog"},
            clear=False,
        ):
            result = service.delete_tables([{"table_name": "t"}])

        self.assertEqual([action for action, _ in client.calls], ["DropDMSTable", "CreateTask", "DescribeTaskResult"])
        verify_payload = client.calls[1][1]
        verify_sql = base64.b64decode(verify_payload["Task"]["SparkSQLTask"]["SQL"]).decode("utf-8")
        self.assertEqual(verify_sql, "SHOW TABLES LIKE 't'")
        self.assertEqual(verify_payload["DatabaseName"], "configured_db")
        self.assertEqual(verify_payload["DatasourceConnectionName"], "configured_catalog")
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["results"][0]["status"], "api_accepted")
        self.assertEqual(result["results"][0]["verification"], "verified_absent")
        self.assertEqual(result["results"][0]["verification_task_id"], "verify-task")
        self.assertEqual(result["results"][0]["verification_request_id"], "verify-result-request")
        self.assertEqual(result["results"][0]["database_name_used"], "configured_db")

    def test_delete_verification_reports_table_still_present(self):
        client = FakeDLCClient()
        result = DLCQueryService(client).delete_tables(
            [{"table_name": "api-still-there", "database_name": "db"}]
        )

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["results"][0]["status"], "api_accepted_table_still_exists")
        self.assertEqual(result["results"][0]["verification"], "table_still_exists")

    def test_delete_requires_configured_or_explicit_database(self):
        client = FakeDLCClient()
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(QueryValidationError, "database_name_required_or_configure_DLC_QUERY_DATABASE"):
                DLCQueryService(client).delete_tables([{"table_name": "t"}])
        self.assertEqual(client.calls, [])

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

    def test_reads_core_usage_curve_for_explicit_dlc_task_instance_id(self):
        client = FakeDLCClient()
        result = DLCQueryService(client).resource_usage("15eb48854c1c11f083e8525400e26adf")

        action, payload = client.calls[0]
        self.assertEqual(action, "DescribeTaskResourceUsage")
        self.assertEqual(payload["TaskInstanceId"], "15eb48854c1c11f083e8525400e26adf")
        self.assertEqual(result["timestamps"], [1750238853000, 1750238854000])
        self.assertEqual(result["core_usage"], [1, 3])
        self.assertEqual(
            result["series"],
            [
                {"timestamp": 1750238853000, "core_usage": 1},
                {"timestamp": 1750238854000, "core_usage": 3},
            ],
        )

    def test_requires_task_instance_id_without_calling_the_api(self):
        client = FakeDLCClient()
        with self.assertRaises(QueryValidationError):
            DLCQueryService(client).resource_usage("  ")
        self.assertEqual(client.calls, [])

    def test_reads_cost_analysis_for_explicit_dlc_task_id(self):
        client = FakeDLCClient()
        result = DLCQueryService(client).task_cost_analysis(
            "e386471f-139a-4e59-877f-50ece8135b99",
            start_time="2025-06-18 00:00:00",
            end_time="2025-06-18 12:00:00",
            limit=5,
        )

        action, payload = client.calls[0]
        self.assertEqual(action, "DescribeTasksAnalysis")
        self.assertEqual(payload["Filters"], [{"Name": "task-id", "Values": ["e386471f-139a-4e59-877f-50ece8135b99"]}])
        self.assertEqual(payload["StartTime"], "2025-06-18 00:00:00")
        self.assertEqual(payload["EndTime"], "2025-06-18 12:00:00")
        self.assertEqual(payload["Limit"], 5)
        self.assertEqual(payload["SortBy"], "task-time-sum")
        self.assertEqual(result["total_count"], 1)
        self.assertEqual(result["tasks"][0]["task_time_sum_seconds"], 403)
        self.assertEqual(result["tasks"][0]["job_time_sum_ms"], 35589)

    def test_unified_resource_usage_appends_cost_analysis(self):
        client = FakeDLCClient()
        result = DLCQueryService(client).resource_usage(
            "15eb48854c1c11f083e8525400e26adf",
            include_cost=True,
            cost_task_id="e386471f-139a-4e59-877f-50ece8135b99",
            cost_start_time="2025-06-18 00:00:00",
            cost_end_time="2025-06-18 12:00:00",
        )

        self.assertEqual([action for action, _ in client.calls], ["DescribeTaskResourceUsage", "DescribeTasksAnalysis"])
        self.assertEqual(result["core_usage"], [1, 3])
        self.assertEqual(result["cost_analysis"]["task_id"], "e386471f-139a-4e59-877f-50ece8135b99")
        self.assertEqual(result["cost_analysis"]["tasks"][0]["id"], "67ea3d234006dc901")

    def test_unified_resource_usage_does_not_derive_cost_task_id(self):
        client = FakeDLCClient()
        with self.assertRaises(QueryValidationError) as ctx:
            DLCQueryService(client).resource_usage("15eb48854c1c11f083e8525400e26adf", include_cost=True)
        self.assertEqual(str(ctx.exception), "cost_task_id_required")
        self.assertEqual(client.calls, [])

    def test_rejects_cost_window_out_of_range_without_calling_the_api(self):
        client = FakeDLCClient()
        with self.assertRaises(QueryValidationError) as ctx:
            DLCQueryService(client).task_cost_analysis(
                "task-1",
                start_time="2025-01-01 00:00:00",
                end_time="2025-06-01 00:00:00",
            )
        self.assertEqual(str(ctx.exception), "analysis_time_range_exceeds_30_days")
        self.assertEqual(client.calls, [])

    def test_surfaces_dlc_api_error(self):
        class ErrorClient:
            def call(self, action, payload):
                return {"Response": {"Error": {"Code": "InvalidParameter.TaskNotFound", "Message": "not found"}}}

        with self.assertRaises(RuntimeError) as ctx:
            DLCQueryService(ErrorClient()).resource_usage("missing")
        self.assertIn("InvalidParameter.TaskNotFound", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
