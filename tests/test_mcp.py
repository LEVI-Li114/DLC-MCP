import sqlite3
import unittest

from dlc_mcp.assets import AssetStore
from dlc_mcp.mcp import handle_request


class McpTest(unittest.TestCase):
    def setUp(self):
        conn = sqlite3.connect(":memory:")
        self.store = AssetStore(conn)
        self.store.init_schema()
        self.store.upsert_table(
            {
                "name": "dim_customer",
                "database": "dw",
                "layer": "dim",
                "domain": "customer",
                "owner": "data-customer",
                "description": "Customer dimension",
            }
        )
        self.store.upsert_table({"name": "dwd_sms_bill", "layer": "dwd", "domain": "finance", "owner": "tencent"})
        self.store.upsert_table({"name": "dws_customer_revenue_1d_di", "layer": "dws", "domain": "finance", "owner": "data-finance"})
        self.store.upsert_table({"name": "ads_customer_revenue_daily", "layer": "ads", "domain": "finance", "owner": "data-finance"})
        self.store.upsert_column("dws_customer_revenue_1d_di", "revenue_amount", "decimal(18,2)", "Revenue amount", 1)
        self.store.upsert_lineage("dws_customer_revenue_1d_di", "ads_customer_revenue_daily", "task_ads_revenue")
        for index in range(5):
            self.store.upsert_lineage("dwd_sms_bill", f"dws_downstream_{index}", f"task_{index}")
        self.store.upsert_column("dim_customer", "customer_id", "string", "Customer ID", 1)
        self.store.upsert_task(
            {
                "id": "task_001",
                "name": "build_dim_customer",
                "task_type": "32",
                "cycle": "DAY",
                "owner": "100043939904",
                "status": "Y11",
                "outputs": ["dim_customer"],
            }
        )
        self.store.upsert_task_run(
            {
                "task_id": "task_001",
                "instance_id": "inst_001",
                "instance_date": "2026-07-01",
                "start_time": "2026-07-01 08:00:00",
                "end_time": "2026-07-01 08:05:00",
                "duration_seconds": 300,
                "status": "success",
            }
        )
        self.store.upsert_data_source(
            {
                "id": "ds_001",
                "name": "mysql_prod",
                "type": "mysql",
                "owner": "data-platform",
                "description": "Production MySQL",
                "config": {"host": "mysql.internal", "database": "crm"},
            }
        )
        self.store.replace_data_source_tasks(
            "ds_001",
            [{"task_id": "sync_001", "task_name": "sync_mysql_prod", "task_type": "DataDevelopment", "project_name": "prod"}],
        )
        self.store.upsert_expert_label({"asset_name": "dim_customer", "core_level": "P1", "value_tier": "重要", "domain": "客户", "use_case": "客户分析"})

    def test_lists_tools(self):
        response = handle_request(self.store, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

        self.assertEqual(response["id"], 1)
        self.assertIn("get_table_profile", [tool["name"] for tool in response["result"]["tools"]])
        self.assertIn("search_tasks", [tool["name"] for tool in response["result"]["tools"]])
        self.assertIn("list_data_sources", [tool["name"] for tool in response["result"]["tools"]])
        self.assertIn("list_data_source_tasks", [tool["name"] for tool in response["result"]["tools"]])
        self.assertIn("get_table_risk_profile", [tool["name"] for tool in response["result"]["tools"]])
        self.assertIn("get_asset_value_profile", [tool["name"] for tool in response["result"]["tools"]])
        self.assertIn("get_metric_definition", [tool["name"] for tool in response["result"]["tools"]])
        self.assertIn("list_quality_gaps", [tool["name"] for tool in response["result"]["tools"]])
        self.assertIn("get_expert_label", [tool["name"] for tool in response["result"]["tools"]])
        self.assertIn("list_expert_review_queue", [tool["name"] for tool in response["result"]["tools"]])
        self.assertIn("list_metadata", [tool["name"] for tool in response["result"]["tools"]])

    def test_calls_table_profile_tool(self):
        response = handle_request(
            self.store,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "get_table_profile", "arguments": {"table_name": "dim_customer"}},
            },
        )

        self.assertEqual(response["result"]["content"][0]["type"], "text")
        self.assertIn("dim_customer", response["result"]["content"][0]["text"])
        self.assertIn("专家标注", response["result"]["content"][0]["text"])

    def test_calls_search_tasks_tool(self):
        response = handle_request(
            self.store,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "search_tasks", "arguments": {"query": "customer"}},
            },
        )

        self.assertIn("build_dim_customer", response["result"]["content"][0]["text"])

    def test_calls_get_task_runs_tool(self):
        response = handle_request(
            self.store,
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "get_task_runs", "arguments": {"task_id": "task_001"}},
            },
        )

        self.assertIn("耗时秒", response["result"]["content"][0]["text"])

    def test_calls_get_task_runs_by_name_and_date(self):
        response = handle_request(
            self.store,
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {
                    "name": "get_task_runs",
                    "arguments": {"task_name": "build_dim_customer", "instance_date": "2026-07-01"},
                },
            },
        )

        text = response["result"]["content"][0]["text"]
        self.assertIn("build_dim_customer", text)
        self.assertIn("耗时秒", text)

    def test_calls_data_source_tools(self):
        response = handle_request(
            self.store,
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {"name": "get_data_source", "arguments": {"data_source_id": "ds_001"}},
            },
        )

        self.assertIn("mysql.internal", response["result"]["content"][0]["text"])

    def test_calls_data_source_tasks_tool(self):
        response = handle_request(
            self.store,
            {
                "jsonrpc": "2.0",
                "id": 11,
                "method": "tools/call",
                "params": {"name": "list_data_source_tasks", "arguments": {"data_source_id": "ds_001"}},
            },
        )

        text = response["result"]["content"][0]["text"]
        self.assertIn("sync_mysql_prod", text)
        self.assertIn("数据源关联任务", text)

    def test_data_sources_are_rendered_as_markdown_table(self):
        response = handle_request(
            self.store,
            {
                "jsonrpc": "2.0",
                "id": 10,
                "method": "tools/call",
                "params": {"name": "list_data_sources", "arguments": {"query": "mysql"}},
            },
        )

        text = response["result"]["content"][0]["text"]
        self.assertIn("| ID | 名称 | 类型 | 负责人 | 花名 | 任务数 |", text)
        self.assertIn("mysql_prod", text)

    def test_calls_metadata_tool(self):
        response = handle_request(
            self.store,
            {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "list_metadata", "arguments": {}}},
        )

        self.assertIn("dim_customer", response["result"]["content"][0]["text"])

    def test_calls_table_risk_profile_tool(self):
        response = handle_request(
            self.store,
            {
                "jsonrpc": "2.0",
                "id": 12,
                "method": "tools/call",
                "params": {"name": "get_table_risk_profile", "arguments": {"table_name": "dwd_sms_bill"}},
            },
        )

        text = response["result"]["content"][0]["text"]
        self.assertIn("风险等级：**高**", text)
        self.assertIn("missing quality rules", text)

    def test_calls_asset_value_profile_tool(self):
        response = handle_request(
            self.store,
            {
                "jsonrpc": "2.0",
                "id": 16,
                "method": "tools/call",
                "params": {"name": "get_asset_value_profile", "arguments": {"table_name": "dwd_sms_bill"}},
            },
        )

        text = response["result"]["content"][0]["text"]
        self.assertIn("资产价值模型", text)
        self.assertIn("L2 重要公共资产", text)

    def test_calls_metric_definition_tool(self):
        response = handle_request(
            self.store,
            {
                "jsonrpc": "2.0",
                "id": 17,
                "method": "tools/call",
                "params": {"name": "get_metric_definition", "arguments": {"table_name": "ads_customer_revenue_daily"}},
            },
        )

        text = response["result"]["content"][0]["text"]
        self.assertIn("指标口径", text)
        self.assertIn("指标应用结果层", text)
        self.assertIn("统计粒度", text)
        self.assertIn("维度字段", text)
        self.assertIn("指标字段", text)
        self.assertIn("dws_customer_revenue_1d_di", text)

    def test_calls_quality_gaps_tool(self):
        response = handle_request(
            self.store,
            {
                "jsonrpc": "2.0",
                "id": 13,
                "method": "tools/call",
                "params": {"name": "list_quality_gaps", "arguments": {"layer": "dwd"}},
            },
        )

        self.assertIn("dwd_sms_bill", response["result"]["content"][0]["text"])

    def test_calls_expert_label_tool(self):
        response = handle_request(
            self.store,
            {
                "jsonrpc": "2.0",
                "id": 14,
                "method": "tools/call",
                "params": {"name": "get_expert_label", "arguments": {"asset_name": "dim_customer"}},
            },
        )

        self.assertIn("P1", response["result"]["content"][0]["text"])

    def test_calls_expert_review_queue_tool(self):
        response = handle_request(
            self.store,
            {
                "jsonrpc": "2.0",
                "id": 15,
                "method": "tools/call",
                "params": {"name": "list_expert_review_queue", "arguments": {"layer": "dwd"}},
            },
        )

        self.assertIn("dwd_sms_bill", response["result"]["content"][0]["text"])

    def test_live_fallback_search_tasks(self):
        live = FakeLive(self.store)
        response = handle_request(
            self.store,
            {
                "jsonrpc": "2.0",
                "id": 8,
                "method": "tools/call",
                "params": {"name": "search_tasks", "arguments": {"query": "live_task"}},
            },
            live,
        )

        self.assertIn("live_task", response["result"]["content"][0]["text"])
        self.assertEqual(live.calls, ["sync_tasks"])

    def test_live_fallback_data_sources(self):
        live = FakeLive(self.store)
        response = handle_request(
            self.store,
            {
                "jsonrpc": "2.0",
                "id": 9,
                "method": "tools/call",
                "params": {"name": "list_data_sources", "arguments": {"query": "live_ds"}},
            },
            live,
        )

        self.assertIn("live_ds", response["result"]["content"][0]["text"])


class FakeLive:
    def __init__(self, store):
        self.store = store
        self.calls = []

    def sync_tasks(self, query):
        self.calls.append("sync_tasks")
        self.store.upsert_task({"id": "live_001", "name": query, "task_type": "32", "status": "Y"})

    def sync_data_sources(self, query=""):
        self.calls.append("sync_data_sources")
        self.store.upsert_data_source({"id": "ds_live", "name": query, "type": "MYSQL", "owner": "owner", "config": {"database": "db"}})

    def sync_table(self, table_name):
        self.calls.append("sync_table")
        self.store.upsert_table({"name": table_name, "layer": "ads", "domain": "finance"})

    def sync_task_runs(self, task_name="", task_id="", instance_date=""):
        self.calls.append("sync_task_runs")


if __name__ == "__main__":
    unittest.main()
