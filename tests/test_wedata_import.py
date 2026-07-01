import sqlite3
import unittest

from dlc_agent.assets import AssetStore
from dlc_agent.wedata import import_wedata_snapshot, snapshot_from_api_dump


class WeDataImportTest(unittest.TestCase):
    def test_imports_tables_tasks_lineage_and_quality_rules(self):
        store = AssetStore(sqlite3.connect(":memory:"))
        store.init_schema()

        import_wedata_snapshot(
            store,
            {
                "tables": [
                    {
                        "name": "dws_customer_order_daily",
                        "database": "dw",
                        "layer": "dws",
                        "domain": "customer",
                        "owner": "data-customer",
                        "description": "Customer order summary",
                        "columns": [
                            {"name": "stat_date", "type": "date", "description": "Metric date"},
                            {"name": "customer_id", "type": "string", "description": "Customer ID"},
                        ],
                    }
                ],
                "tasks": [
                    {
                        "id": "task_001",
                        "name": "build_dws_customer_order_daily",
                        "task_type": "SQL",
                        "cycle": "DAY",
                        "owner": "etl-owner",
                        "status": "success",
                        "inputs": ["ods_order"],
                        "outputs": ["dws_customer_order_daily"],
                    }
                ],
                "quality_rules": [
                    {
                        "table_name": "dws_customer_order_daily",
                        "rule_name": "customer_id_not_null",
                        "rule_type": "not_null",
                        "target": "customer_id",
                        "enabled": True,
                        "last_status": "passed",
                        "last_checked_at": "2026-07-01T09:00:00",
                    }
                ],
            },
        )

        profile = store.get_table_profile("dws_customer_order_daily")
        self.assertEqual(profile["table"]["owner"], "data-customer")
        self.assertEqual([column["name"] for column in profile["columns"]], ["stat_date", "customer_id"])
        self.assertEqual(profile["quality"]["rule_count"], 1)
        self.assertEqual(store.get_table_lineage("dws_customer_order_daily")["upstream"][0]["upstream"], "ods_order")
        self.assertEqual(store.get_task("task_001")["outputs"], ["dws_customer_order_daily"])

    def test_builds_snapshot_from_api_dump(self):
        snapshot = snapshot_from_api_dump(
            {
                "tables": {
                    "Response": {
                        "Data": {
                            "Items": [
                                {
                                    "TableName": "ads_revenue",
                                    "DatabaseName": "bi",
                                    "Layer": "ads",
                                    "Owner": "data-finance",
                                    "Description": "Revenue table",
                                }
                            ]
                        }
                    }
                },
                "tasks": {
                    "Response": {
                        "Data": {
                            "Items": [
                                {
                                    "TaskId": "t1",
                                    "TaskName": "build_ads_revenue",
                                    "TaskType": "SQL",
                                    "CycleType": "DAY",
                                    "Owner": "etl",
                                }
                            ]
                        }
                    }
                },
                "quality_rules": {
                    "Response": {
                        "Data": {
                            "Items": [
                                {
                                    "TableName": "ads_revenue",
                                    "RuleName": "amount_not_null",
                                    "RuleType": "not_null",
                                    "Target": "amount",
                                    "Status": "passed",
                                }
                            ]
                        }
                    }
                },
            }
        )

        self.assertEqual(snapshot["tables"][0]["name"], "ads_revenue")
        self.assertEqual(snapshot["tasks"][0]["id"], "t1")
        self.assertEqual(snapshot["quality_rules"][0]["rule_name"], "amount_not_null")

    def test_maps_real_list_tasks_fields(self):
        snapshot = snapshot_from_api_dump(
            {
                "tasks": {
                    "Response": {
                        "Data": {
                            "Items": [
                                {
                                    "TaskId": "20251013191831005",
                                    "TaskName": "1",
                                    "TaskTypeId": 32,
                                    "TaskLatestVersionStatus": "Y11",
                                    "OwnerUin": "100043939904",
                                }
                            ]
                        }
                    }
                }
            }
        )

        self.assertEqual(
            snapshot["tasks"][0],
            {
                "id": "20251013191831005",
                "name": "1",
                "task_type": "32",
                "cycle": "",
                "owner": "100043939904",
                "status": "Y11",
                "inputs": [],
                "outputs": [],
            },
        )


if __name__ == "__main__":
    unittest.main()
