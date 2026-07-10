import sqlite3
import unittest

from dlc_mcp.assets import AssetStore
from dlc_mcp.check_foundation import render_foundation_report


class CheckFoundationTest(unittest.TestCase):
    def test_renders_readable_markdown_without_jsonrpc_wrapper(self):
        conn = sqlite3.connect(":memory:")
        store = AssetStore(conn)
        store.init_schema()
        store.upsert_table({"name": "ads_customer_revenue_daily", "layer": "ads", "owner": "data-finance"})
        store.upsert_column("ads_customer_revenue_daily", "customer_id", "string", "Customer ID", 1)
        store.upsert_quality_rule(
            {
                "table_name": "ads_customer_revenue_daily",
                "rule_name": "customer_id_not_null",
                "rule_type": "not_null",
                "last_status": "passed",
            }
        )

        report = render_foundation_report(store, "demo.db", ["tasks", "runs", "data_source"], 5)

        self.assertIn("# DLC-MCP 资产底座检查报告", report)
        self.assertIn("数据库：`demo.db`", report)
        self.assertIn("## 同步健康", report)
        self.assertIn("| 表资产 | 1 |", report)
        self.assertIn("## 资产覆盖率", report)
        self.assertIn("## 资产画像缺口：tasks", report)
        self.assertIn("缺相关任务", report)
        self.assertIn("优先跑通 `ListTasks`", report)
        self.assertNotIn("jsonrpc", report.lower())
        self.assertNotIn('"result"', report)

    def test_renders_service_inspection_baselines_when_supplied(self):
        conn = sqlite3.connect(":memory:")
        store = AssetStore(conn)
        store.init_schema()

        report = render_foundation_report(
            store,
            "service.db",
            ["quality"],
            5,
            report_source="latest service asset inspection",
            quality_rule_count=62,
            unknown_layer_count=2141,
        )

        self.assertIn("## 巡检来源", report)
        self.assertIn("latest service asset inspection", report)
        self.assertIn("质量规则基线：**62**", report)
        self.assertIn("unknown 层表基线：**2141**", report)


if __name__ == "__main__":
    unittest.main()
