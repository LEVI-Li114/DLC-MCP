import os
import sqlite3

from .assets import AssetStore


def seed(db_path="data/assets.db"):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    store = AssetStore(sqlite3.connect(db_path))
    store.init_schema()
    store.upsert_table(
        {
            "name": "ads_customer_revenue_daily",
            "database": "bi",
            "layer": "ads",
            "domain": "finance",
            "owner": "data-finance",
            "description": "Customer daily revenue metrics for finance dashboards.",
        }
    )
    store.upsert_column("ads_customer_revenue_daily", "stat_date", "date", "Metric date", 1)
    store.upsert_column("ads_customer_revenue_daily", "customer_id", "string", "Customer ID", 2)
    store.upsert_column("ads_customer_revenue_daily", "revenue_amount", "decimal(18,2)", "Revenue amount", 3)
    store.upsert_lineage("dws_customer_order_daily", "ads_customer_revenue_daily", "task_ads_customer_revenue_daily")
    store.upsert_lineage("ads_customer_revenue_daily", "bi_finance_dashboard", "dashboard")
    store.upsert_quality_rule(
        {
            "table_name": "ads_customer_revenue_daily",
            "rule_name": "stat_date_timeliness",
            "rule_type": "timeliness",
            "target": "stat_date",
            "enabled": True,
            "last_status": "passed",
            "last_checked_at": "2026-07-01T08:30:00",
        }
    )
    store.upsert_quality_rule(
        {
            "table_name": "ads_customer_revenue_daily",
            "rule_name": "revenue_amount_not_null",
            "rule_type": "not_null",
            "target": "revenue_amount",
            "enabled": True,
            "last_status": "passed",
            "last_checked_at": "2026-07-01T08:31:00",
        }
    )
    return db_path


if __name__ == "__main__":
    print(seed())
