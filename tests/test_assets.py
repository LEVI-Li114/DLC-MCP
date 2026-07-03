import sqlite3
import unittest

from dlc_mcp.assets import AssetStore


def make_store():
    conn = sqlite3.connect(":memory:")
    store = AssetStore(conn)
    store.init_schema()
    store.upsert_table(
        {
            "name": "ads_customer_revenue_daily",
            "data_source_id": "ds_001",
            "database": "bi",
            "layer": "ads",
            "domain": "finance",
            "owner": "data-finance",
            "description": "Customer daily revenue metrics",
            "manual_core_level": None,
        }
    )
    store.upsert_column("ads_customer_revenue_daily", "customer_id", "string", "Customer ID", 1)
    store.upsert_column("ads_customer_revenue_daily", "revenue_amount", "decimal(18,2)", "Revenue", 2)
    store.upsert_table({"name": "dws_customer_revenue_1d_di", "layer": "dws", "domain": "finance", "owner": "data-finance"})
    store.upsert_column("dws_customer_revenue_1d_di", "customer_id", "string", "Customer ID", 1)
    store.upsert_column("dws_customer_revenue_1d_di", "customer_name", "string", "Customer name", 2)
    store.upsert_column("dws_customer_revenue_1d_di", "revenue_amount", "decimal(18,2)", "Revenue amount", 3)
    store.upsert_column("dws_customer_revenue_1d_di", "pay_count", "bigint", "Pay count", 4)
    store.upsert_column("dws_customer_revenue_1d_di", "bill_date", "string", "Bill date", 5)
    store.upsert_lineage("dws_customer_revenue_1d_di", "ads_customer_revenue_daily", "task_ads_revenue_daily")
    store.upsert_lineage("ods_order", "ads_customer_revenue_daily", "task_revenue_daily")
    store.upsert_lineage("ads_customer_revenue_daily", "bi_finance_dashboard", "bi_report")
    store.upsert_quality_rule(
        {
            "table_name": "ads_customer_revenue_daily",
            "rule_name": "revenue_amount_not_null",
            "rule_type": "not_null",
            "target": "revenue_amount",
            "enabled": True,
            "last_status": "passed",
            "last_checked_at": "2026-07-01T08:10:00",
        }
    )
    store.upsert_task(
        {
            "id": "task_001",
            "name": "ads_customer_revenue_daily",
            "outputs": ["ads_customer_revenue_daily"],
        }
    )
    store.upsert_data_source({"id": "ds_001", "name": "mysql_prod", "owner": "100043939904", "config": {}})
    return store


def make_risky_store():
    store = make_store()
    store.upsert_table({"name": "dwd_sms_bill", "layer": "dwd", "domain": "finance", "owner": "tencent"})
    for index in range(5):
        store.upsert_lineage("dwd_sms_bill", f"dws_downstream_{index}", f"task_{index}")
    store.upsert_task({"id": "task_risk", "name": "dwd_sms_bill", "outputs": ["dwd_sms_bill"]})
    return store


class AssetStoreTest(unittest.TestCase):
    def test_table_profile_includes_columns_and_quality_summary(self):
        profile = make_store().get_table_profile("ads_customer_revenue_daily")

        self.assertEqual(profile["table"]["name"], "ads_customer_revenue_daily")
        self.assertEqual([column["name"] for column in profile["columns"]], ["customer_id", "revenue_amount"])
        self.assertEqual(profile["quality"]["rule_count"], 1)
        self.assertEqual(profile["quality"]["latest_status"], "passed")

    def test_core_table_decision_is_explainable(self):
        decision = make_store().is_core_table("ads_customer_revenue_daily")

        self.assertIs(decision["is_core"], False)
        self.assertEqual(decision["core_level"], "P2")
        self.assertGreaterEqual(decision["score"], 50)
        self.assertIn("ads layer", decision["reasons"])
        self.assertIn("finance domain", decision["reasons"])
        self.assertIn("1 quality rules", decision["reasons"])

    def test_unknown_table_returns_not_found(self):
        self.assertEqual(make_store().get_table_profile("missing")["error"], "table_not_found")

    def test_data_source_includes_owner_name_and_task_count(self):
        source = make_store().get_data_source("ds_001")

        self.assertEqual(source["owner_name"], "luyuan")
        self.assertEqual(source["task_count"], 1)

    def test_data_source_task_count_prefers_related_tasks(self):
        store = make_store()
        store.replace_data_source_tasks("ds_001", [{"task_id": "sync_001", "task_name": "sync_mysql"}])

        self.assertEqual(store.get_data_source("ds_001")["task_count"], 1)

    def test_table_risk_profile_flags_missing_quality_rules(self):
        risk = make_risky_store().get_table_risk_profile("dwd_sms_bill")

        self.assertEqual(risk["risk_level"], "高")
        self.assertEqual(risk["downstream_count"], 5)
        self.assertEqual(risk["quality_rule_count"], 0)
        self.assertIn("missing quality rules", risk["reasons"])

    def test_quality_gaps_find_tables_with_downstream_and_no_rules(self):
        gaps = make_risky_store().list_quality_gaps(layer="dwd")

        self.assertEqual(gaps["results"][0]["name"], "dwd_sms_bill")

    def test_expert_label_overrides_core_decision(self):
        store = make_risky_store()
        store.upsert_expert_label(
            {
                "asset_name": "dwd_sms_bill",
                "core_level": "P0",
                "value_tier": "核心",
                "domain": "财务分析",
                "use_case": "短信计费核算",
                "reviewer": "data-expert",
                "reason": "影响短信账单与成本分析",
            }
        )

        self.assertEqual(store.get_table_profile("dwd_sms_bill")["expert_label"]["core_level"], "P0")
        self.assertTrue(store.is_core_table("dwd_sms_bill")["is_core"])
        self.assertEqual(store.list_expert_review_queue(layer="dwd")["results"], [])

    def test_asset_value_profile_scores_new_tables(self):
        value = make_risky_store().get_asset_value_profile("dwd_sms_bill")

        self.assertEqual(value["value_tier"], "L2 重要公共资产")
        self.assertEqual(value["core_level"], "P2")
        self.assertFalse(value["is_core"])
        self.assertEqual(value["dimensions"]["usage_heat"], 0)

    def test_metric_definition_explains_ads_and_dws_roles(self):
        store = make_store()

        ads = store.get_metric_definition("ads_customer_revenue_daily")
        dws = store.get_metric_definition("dws_customer_revenue_1d_di")

        self.assertEqual(ads["role"]["name"], "指标应用结果层")
        self.assertEqual(ads["upstream_dws"][0]["upstream"], "dws_customer_revenue_1d_di")
        self.assertEqual(dws["role"]["name"], "指标统计口径层")
        self.assertEqual([field["metric_type"] for field in dws["metric_fields"]], ["金额类", "数量类"])
        self.assertEqual([field["name"] for field in dws["time_fields"]], ["bill_date"])
        self.assertEqual([field["name"] for field in dws["dimension_fields"]], ["customer_id"])
        self.assertEqual([field["name"] for field in dws["description_fields"]], ["customer_name"])
        self.assertIn("金额类、数量类", dws["summary"])


if __name__ == "__main__":
    unittest.main()
