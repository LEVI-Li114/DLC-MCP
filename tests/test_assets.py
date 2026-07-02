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

        self.assertIs(decision["is_core"], True)
        self.assertGreaterEqual(decision["score"], 70)
        self.assertIn("ads layer", decision["reasons"])
        self.assertIn("finance domain", decision["reasons"])
        self.assertIn("has quality rules", decision["reasons"])

    def test_unknown_table_returns_not_found(self):
        self.assertEqual(make_store().get_table_profile("missing")["error"], "table_not_found")


if __name__ == "__main__":
    unittest.main()
