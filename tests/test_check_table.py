import sqlite3
import unittest

from dlc_mcp.assets import AssetStore
from dlc_mcp.check_table import render_table_readiness


class CheckTableTest(unittest.TestCase):
    def test_renders_any_table_readiness_report(self):
        store = AssetStore(sqlite3.connect(":memory:"))
        store.init_schema()
        store.upsert_table({"name": "ads_bill_company_1d_di", "layer": "ads", "domain": "finance", "owner": "data-finance"})
        store.upsert_column("ads_bill_company_1d_di", "company_id", "string", "Company ID", 1)
        store.upsert_quality_rule({"table_name": "ads_bill_company_1d_di", "rule_name": "company_id_not_null"})

        store.upsert_task(
            {
                "id": "task_001",
                "name": "ads_bill_company_1d_di",
                "cycle": "DAY",
                "schedule_time": "08:00",
                "schedule_desc": "每天 08:00 调度",
                "owner": "data-finance",
                "outputs": ["ads_bill_company_1d_di"],
            }
        )

        report = render_table_readiness(store, "ads_bill_company_1d_di")

        self.assertIn("表资产治理就绪度", report)
        self.assertIn("ads_bill_company_1d_di", report)
        self.assertIn("画像维度检查", report)
        self.assertIn("字段", report)
        self.assertIn("治理动作建议", report)
        self.assertIn("相关任务明细", report)
        self.assertIn("最近任务执行实例", report)
        self.assertIn("08:00", report)
        self.assertIn("每天 08:00 调度", report)
        self.assertIn("未执行", report)


if __name__ == "__main__":
    unittest.main()
