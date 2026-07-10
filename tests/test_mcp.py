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
        self.assertIn("get_table_partition_profile", [tool["name"] for tool in response["result"]["tools"]])
        self.assertIn("get_table_readiness", [tool["name"] for tool in response["result"]["tools"]])
        self.assertIn("get_table_production_status", [tool["name"] for tool in response["result"]["tools"]])
        self.assertIn("get_table_production_risk_detail", [tool["name"] for tool in response["result"]["tools"]])
        self.assertIn("list_table_production_risks", [tool["name"] for tool in response["result"]["tools"]])
        self.assertIn("search_tasks", [tool["name"] for tool in response["result"]["tools"]])
        self.assertIn("list_data_sources", [tool["name"] for tool in response["result"]["tools"]])
        self.assertIn("list_data_source_tasks", [tool["name"] for tool in response["result"]["tools"]])
        self.assertIn("get_table_risk_profile", [tool["name"] for tool in response["result"]["tools"]])
        self.assertIn("get_asset_value_profile", [tool["name"] for tool in response["result"]["tools"]])
        self.assertIn("get_asset_owner_profile", [tool["name"] for tool in response["result"]["tools"]])
        self.assertIn("get_asset_usage_profile", [tool["name"] for tool in response["result"]["tools"]])
        self.assertIn("get_asset_lifecycle_profile", [tool["name"] for tool in response["result"]["tools"]])
        self.assertIn("get_asset_change_impact", [tool["name"] for tool in response["result"]["tools"]])
        self.assertIn("get_metric_definition", [tool["name"] for tool in response["result"]["tools"]])
        self.assertIn("list_quality_gaps", [tool["name"] for tool in response["result"]["tools"]])
        self.assertIn("get_expert_label", [tool["name"] for tool in response["result"]["tools"]])
        self.assertIn("list_expert_review_queue", [tool["name"] for tool in response["result"]["tools"]])
        self.assertIn("list_metadata", [tool["name"] for tool in response["result"]["tools"]])
        self.assertIn("get_sync_health", [tool["name"] for tool in response["result"]["tools"]])
        self.assertIn("get_asset_coverage", [tool["name"] for tool in response["result"]["tools"]])
        self.assertIn("list_asset_coverage_gaps", [tool["name"] for tool in response["result"]["tools"]])
        self.assertIn("get_asset_governance_daily_report", [tool["name"] for tool in response["result"]["tools"]])

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
        text = response["result"]["content"][0]["text"]
        self.assertIn("标准表画像：dim_customer", text)
        self.assertIn("资产价值与核心表判断", text)
        self.assertIn("字段信息", text)
        self.assertIn("上下游血缘", text)
        self.assertIn("运行状态", text)
        self.assertIn("当前缺口", text)
        self.assertIn("专家标注", text)

    def test_calls_table_partition_profile_tool(self):
        self.store.upsert_table_partition(
            {
                "table_name": "ads_customer_revenue_daily",
                "partition_name": "dt=2026-07-07",
                "partition_date": "2026-07-07",
                "row_count": 1283991,
                "storage_bytes": 2300000000,
                "file_count": 64,
                "updated_at": "2026-07-08 02:13:11",
            }
        )
        self.store.upsert_table_partition(
            {
                "table_name": "ads_customer_revenue_daily",
                "partition_name": "dt=2026-07-06",
                "partition_date": "2026-07-06",
                "row_count": 1278120,
                "storage_bytes": 2200000000,
                "file_count": 63,
                "updated_at": "2026-07-07 02:13:11",
            }
        )
        response = handle_request(
            self.store,
            {
                "jsonrpc": "2.0",
                "id": 26,
                "method": "tools/call",
                "params": {"name": "get_table_partition_profile", "arguments": {"table_name": "ads_customer_revenue_daily", "partition_date": "2026-07-07"}},
            },
        )

        text = response["result"]["content"][0]["text"]
        self.assertIn("表分区画像", text)
        self.assertIn("2026-07-07", text)
        self.assertIn("1283991", text)
        self.assertIn("最近分区", text)
        self.assertIn("正常", text)

    def test_calls_table_readiness_tool(self):
        response = handle_request(
            self.store,
            {
                "jsonrpc": "2.0",
                "id": 21,
                "method": "tools/call",
                "params": {"name": "get_table_readiness", "arguments": {"table_name": "dim_customer"}},
            },
        )

        text = response["result"]["content"][0]["text"]
        self.assertIn("表资产治理就绪度", text)
        self.assertIn("画像维度检查", text)
        self.assertIn("治理动作建议", text)

    def test_calls_table_production_status_tool(self):
        response = handle_request(
            self.store,
            {
                "jsonrpc": "2.0",
                "id": 22,
                "method": "tools/call",
                "params": {"name": "get_table_production_status", "arguments": {"table_name": "dim_customer", "instance_date": "2026-07-01"}},
            },
        )

        text = response["result"]["content"][0]["text"]
        self.assertIn("表产出状态", text)
        self.assertIn("成功", text)
        self.assertIn("build_dim_customer", text)
        self.assertIn("2026-07-01 08:00:00", text)

    def test_calls_table_production_risk_detail_tool(self):
        response = handle_request(
            self.store,
            {
                "jsonrpc": "2.0",
                "id": 24,
                "method": "tools/call",
                "params": {"name": "get_table_production_risk_detail", "arguments": {"table_name": "dws_customer_revenue_1d_di", "instance_date": "2026-07-01"}},
            },
        )

        text = response["result"]["content"][0]["text"]
        self.assertIn("表产出风险诊断", text)
        self.assertIn("dws_customer_revenue_1d_di", text)
        self.assertIn("未执行", text)
        self.assertIn("影响面", text)
        self.assertIn("风险判断", text)
        self.assertIn("处理建议", text)

    def test_calls_table_production_risks_tool(self):
        response = handle_request(
            self.store,
            {
                "jsonrpc": "2.0",
                "id": 23,
                "method": "tools/call",
                "params": {"name": "list_table_production_risks", "arguments": {"layer": "dws", "instance_date": "2026-07-01"}},
            },
        )

        text = response["result"]["content"][0]["text"]
        self.assertIn("表产出风险清单", text)
        self.assertIn("dws_customer_revenue_1d_di", text)
        self.assertIn("未执行", text)
        self.assertIn("未找到产出任务", text)
        self.assertIn("检查 `ListTasks`", text)

    def test_calls_sync_health_tool(self):
        response = handle_request(
            self.store,
            {
                "jsonrpc": "2.0",
                "id": 18,
                "method": "tools/call",
                "params": {"name": "get_sync_health", "arguments": {}},
            },
        )

        text = response["result"]["content"][0]["text"]
        self.assertIn("同步健康检查", text)
        self.assertIn("表资产", text)
        self.assertIn("最新同步线索", text)

    def test_calls_asset_coverage_tool(self):
        response = handle_request(
            self.store,
            {
                "jsonrpc": "2.0",
                "id": 19,
                "method": "tools/call",
                "params": {"name": "get_asset_coverage", "arguments": {}},
            },
        )

        text = response["result"]["content"][0]["text"]
        self.assertIn("资产覆盖率", text)
        self.assertIn("| 层级 | 表数 | 有字段 | 有质量规则 |", text)
        self.assertIn("dwd", text)

    def test_calls_asset_coverage_gaps_tool(self):
        response = handle_request(
            self.store,
            {
                "jsonrpc": "2.0",
                "id": 20,
                "method": "tools/call",
                "params": {"name": "list_asset_coverage_gaps", "arguments": {"gap_type": "quality", "layer": "dwd"}},
            },
        )

        text = response["result"]["content"][0]["text"]
        self.assertIn("资产画像缺口清单", text)
        self.assertIn("dwd_sms_bill", text)
        self.assertIn("缺质量规则", text)

    def test_calls_asset_governance_daily_report_tool(self):
        response = handle_request(
            self.store,
            {
                "jsonrpc": "2.0",
                "id": 25,
                "method": "tools/call",
                "params": {"name": "get_asset_governance_daily_report", "arguments": {"instance_date": "2026-07-01", "layer": "dws"}},
            },
        )

        text = response["result"]["content"][0]["text"]
        self.assertIn("资产巡检日报", text)
        self.assertIn("今日优先动作", text)
        self.assertIn("产出风险 Top 表", text)
        self.assertIn("资产画像缺口", text)
        self.assertIn("说明", text)

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
        self.assertIn("机器初判", text)
        self.assertIn("最终判断", text)

    def test_calls_asset_governance_tools(self):
        calls = [
            ("get_asset_owner_profile", {"table_name": "dim_customer"}, "资产责任画像", "责任人候选"),
            ("get_asset_usage_profile", {"table_name": "dws_customer_revenue_1d_di"}, "资产使用画像", "使用信号"),
            ("get_asset_lifecycle_profile", {"table_name": "dim_customer"}, "资产生命周期", "生命周期证据"),
            ("get_asset_change_impact", {"table_name": "dws_customer_revenue_1d_di", "change_type": "schema_change"}, "资产变更影响分析", "变更前检查"),
        ]
        for index, (name, arguments, title, section) in enumerate(calls, start=30):
            response = handle_request(
                self.store,
                {
                    "jsonrpc": "2.0",
                    "id": index,
                    "method": "tools/call",
                    "params": {"name": name, "arguments": arguments},
                },
            )
            text = response["result"]["content"][0]["text"]
            self.assertIn(title, text)
            self.assertIn(section, text)

    def test_calls_core_table_tool_with_machine_manual_final_sections(self):
        response = handle_request(
            self.store,
            {
                "jsonrpc": "2.0",
                "id": 18,
                "method": "tools/call",
                "params": {"name": "is_core_table", "arguments": {"table_name": "ads_customer_revenue_daily"}},
            },
        )

        text = response["result"]["content"][0]["text"]
        self.assertIn("核心资产判断", text)
        self.assertIn("机器初判", text)
        self.assertIn("人工标注", text)
        self.assertIn("最终判断", text)
        self.assertIn("置信度", text)

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
    def test_tools_list_includes_governance_issue_inventory(self):
        store = AssetStore(sqlite3.connect(":memory:"))
        store.init_schema()
        response = handle_request(store, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

        tool_names = [tool["name"] for tool in response["result"]["tools"]]
        self.assertIn("get_asset_governance_issue_inventory", tool_names)

    def test_can_call_governance_issue_inventory(self):
        store = AssetStore(sqlite3.connect(":memory:"))
        store.init_schema()
        store.upsert_table({"name": "ads_revenue", "layer": "ads"})

        response = handle_request(
            store,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "get_asset_governance_issue_inventory",
                    "arguments": {"issue_type": "missing_quality_rules", "limit": 10},
                },
            },
        )

        text = response["result"]["content"][0]["text"]
        self.assertIn("missing_quality_rules", text)
        self.assertIn("ads_revenue", text)


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
