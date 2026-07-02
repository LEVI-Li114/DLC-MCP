import sqlite3
import unittest

from dlc_mcp.assets import AssetStore
from dlc_mcp.wedata import import_wedata_snapshot, snapshot_from_api_dump


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
                "task_instances": [
                    {
                        "task_id": "task_001",
                        "instance_id": "inst_001",
                        "instance_date": "2026-07-01",
                        "start_time": "2026-07-01 08:00:00",
                        "end_time": "2026-07-01 08:05:30",
                        "duration_seconds": 330,
                        "status": "success",
                    }
                ],
                "data_sources": [
                    {
                        "id": "ds_001",
                        "name": "mysql_prod",
                        "type": "mysql",
                        "owner": "data-platform",
                        "description": "Production MySQL",
                        "config": {"host": "mysql.internal", "database": "crm"},
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
        self.assertEqual(store.get_task_runs("task_001")["runs"][0]["duration_seconds"], 330)
        self.assertEqual(store.get_data_source("ds_001")["name"], "mysql_prod")

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

    def test_maps_real_metadata_columns_quality_and_lineage(self):
        snapshot = snapshot_from_api_dump(
            {
                "tables": {
                    "Response": {
                        "Data": {
                            "Items": [
                                {
                                    "Guid": "guid_1",
                                    "Name": "ads_bill_company_1d_di",
                                    "DatabaseName": "byai_bigdata",
                                    "Description": "客户账单应用表",
                                    "TechnicalMetadata": {"Owner": "prod-bigdata"},
                                    "Columns": [
                                        {"Name": "company_id", "Type": "bigint", "Description": "客户id", "Position": 4}
                                    ],
                                }
                            ]
                        }
                    }
                },
                "lineage": {
                    "Response": {
                        "Data": {
                            "Items": [
                                {
                                    "QueriedTableName": "ads_bill_company_1d_di",
                                    "Resource": {
                                        "ResourceName": "cc_prod.ads_bill_company_1d_di_report",
                                        "ResourceProperties": [{"Name": "TableName", "Value": "ads_bill_company_1d_di_report"}],
                                    },
                                    "Relation": {"Processes": [{"ProcessId": "task_down"}]},
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
                                    "TableName": "ads_bill_company_1d_di",
                                    "Name": "bill_amt_not_null",
                                    "RuleTemplateContent": "完整性: 非空",
                                    "SourceObjectValue": "bill_amt",
                                    "MonitorStatus": 1,
                                    "UpdateTime": "2026-07-01 10:00:00",
                                }
                            ]
                        }
                    }
                },
            }
        )

        self.assertEqual(snapshot["tables"][0]["guid"], "guid_1")
        self.assertEqual(snapshot["tables"][0]["columns"][0]["name"], "company_id")
        self.assertEqual(snapshot["lineage"][0]["downstream"], "ads_bill_company_1d_di_report")
        self.assertEqual(snapshot["quality_rules"][0]["target"], "bill_amt")

    def test_maps_data_sources_from_api_dump(self):
        snapshot = snapshot_from_api_dump(
            {
                "data_sources": {
                    "Response": {
                        "Data": {
                            "Items": [
                                {
                                    "DataSourceId": "ds_001",
                                    "DataSourceName": "mysql_prod",
                                    "Type": "mysql",
                                    "Owner": "data-platform",
                                    "Description": "Production MySQL",
                                    "Host": "mysql.internal",
                                    "DatabaseName": "crm",
                                }
                            ]
                        }
                    }
                }
            }
        )

        self.assertEqual(snapshot["data_sources"][0]["name"], "mysql_prod")
        self.assertEqual(snapshot["data_sources"][0]["config"]["host"], "mysql.internal")

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

    def test_derives_table_asset_from_layer_named_task(self):
        snapshot = snapshot_from_api_dump(
            {
                "tasks": {
                    "Response": {
                        "Data": {
                            "Items": [
                                {
                                    "TaskId": "t_ads",
                                    "TaskName": "ads_bill_company_1d_di",
                                    "TaskTypeId": 32,
                                    "OwnerUin": "100043939904",
                                    "TaskLatestVersionStatus": "Y",
                                },
                                {
                                    "TaskId": "t_check",
                                    "TaskName": "ads_bill_company_1d_di_check",
                                    "TaskTypeId": 32,
                                },
                            ]
                        }
                    }
                }
            }
        )

        self.assertEqual(snapshot["tasks"][0]["outputs"], ["ads_bill_company_1d_di"])
        self.assertEqual(snapshot["tasks"][1]["outputs"], [])
        self.assertEqual(snapshot["tables"][0]["name"], "ads_bill_company_1d_di")
        self.assertEqual(snapshot["tables"][0]["layer"], "ads")
        self.assertEqual(snapshot["tables"][0]["domain"], "finance")

    def test_maps_task_instance_time_fields(self):
        snapshot = snapshot_from_api_dump(
            {
                "task_instances": {
                    "Response": {
                        "Data": {
                            "Items": [
                                {
                                    "TaskId": "task_001",
                                    "InstanceKey": "inst_001",
                                    "SchedulerTime": "2026-07-01 00:00:00",
                                    "StartTime": "2026-07-01 08:00:00",
                                    "EndTime": "2026-07-01 08:03:00",
                                    "CostTime": 180000,
                                    "InstanceState": "COMPLETED",
                                }
                            ]
                        }
                    }
                }
            }
        )

        self.assertEqual(snapshot["task_instances"][0]["duration_seconds"], 180)
        self.assertEqual(snapshot["task_instances"][0]["instance_id"], "inst_001")
        self.assertEqual(snapshot["task_instances"][0]["status"], "COMPLETED")


if __name__ == "__main__":
    unittest.main()
