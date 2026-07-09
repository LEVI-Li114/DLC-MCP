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
                "table_partitions": [
                    {
                        "table_name": "dws_customer_order_daily",
                        "partition_name": "dt=2026-07-01",
                        "partition_date": "2026-07-01",
                        "row_count": 100,
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
        self.assertEqual(store.get_table_partition_profile("dws_customer_order_daily", "2026-07-01")["target_partition"]["row_count"], 100)

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
                                    "DatasourceId": 55975,
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
        self.assertEqual(snapshot["tables"][0]["data_source_id"], "55975")
        self.assertEqual(snapshot["tables"][0]["columns"][0]["name"], "company_id")
        self.assertEqual(snapshot["lineage"][0]["downstream"], "ads_bill_company_1d_di_report")
        self.assertEqual(snapshot["quality_rules"][0]["target"], "bill_amt")

    def test_maps_table_partitions_from_api_dump(self):
        snapshot = snapshot_from_api_dump(
            {
                "table_partitions": {
                    "Response": {
                        "Data": {
                            "Items": [
                                {
                                    "QueriedTableName": "ads_bill_company_1d_di",
                                    "PartitionName": "dt=20260708",
                                    "RowCount": 123,
                                    "StorageBytes": 456,
                                    "FileCount": 7,
                                }
                            ]
                        }
                    }
                }
            }
        )

        partition = snapshot["table_partitions"][0]
        self.assertEqual(partition["table_name"], "ads_bill_company_1d_di")
        self.assertEqual(partition["partition_date"], "2026-07-08")
        self.assertEqual(partition["row_count"], 123)

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

    def test_maps_real_list_data_sources_properties(self):
        snapshot = snapshot_from_api_dump(
            {
                "data_sources": {
                    "Response": {
                        "Data": {
                            "Items": [
                                {
                                    "Id": 73103,
                                    "Name": "tech_support",
                                    "Type": "MYSQL",
                                    "CreateUser": "100043939904",
                                    "Description": "技术支持",
                                    "ProdConProperties": "{\"ip\":\"172.19.128.6\",\"port\":\"3306\",\"db\":\"flow_boost\",\"url\":\"jdbc:mysql://172.19.128.6:3306/flow_boost\",\"username\":\"tech_support\",\"password\":\"********\"}",
                                }
                            ]
                        }
                    }
                }
            }
        )

        data_source = snapshot["data_sources"][0]
        self.assertEqual(data_source["id"], "73103")
        self.assertEqual(data_source["owner"], "100043939904")
        self.assertEqual(data_source["config"]["database"], "flow_boost")
        self.assertEqual(data_source["config"]["username"], "tech_support")

    def test_maps_dlc_table_catalog_source(self):
        snapshot = snapshot_from_api_dump(
            {
                "tables": {
                    "Response": {
                        "Data": {
                            "Items": [
                                {
                                    "Guid": "guid_1",
                                    "Name": "dws_360_fin_job_seat_1d_di",
                                    "DatabaseName": "byai_bigdata",
                                    "DatasourceId": None,
                                    "DatasourceType": "DLC",
                                }
                            ]
                        }
                    }
                }
            }
        )

        self.assertEqual(snapshot["tables"][0]["data_source_id"], "DLC")
        self.assertEqual(snapshot["data_sources"][0]["id"], "DLC")

    def test_maps_data_source_related_tasks(self):
        snapshot = snapshot_from_api_dump(
            {
                "data_source_tasks": {
                    "67186": {
                        "Response": {
                            "Data": [
                                {
                                    "ProjectId": "2881307738992685056",
                                    "ProjectName": "byai_bigdata_prod",
                                    "TaskInfo": [
                                        {
                                            "TaskType": "DataDevelopment",
                                            "TaskList": [
                                                {
                                                    "TaskId": "20251023184047084",
                                                    "TaskName": "c2f_ads_call_company_yizhifu_1d_di",
                                                    "CreateTime": "2025-10-23 18:40:47",
                                                    "OwnerUinList": ["100043939904"],
                                                }
                                            ],
                                        }
                                    ],
                                }
                            ]
                        }
                    }
                }
            }
        )

        related = snapshot["data_source_tasks"][0]
        self.assertEqual(related["data_source_id"], "67186")
        self.assertEqual(related["tasks"][0]["task_name"], "c2f_ads_call_company_yizhifu_1d_di")

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
                                    "CycleType": "DAY",
                                    "ScheduleTime": "08:00",
                                    "ScheduleDesc": "每天 08:00 调度",
                                    "InputTableList": [{"TableName": "dwd_bill_company_di"}],
                                    "OutputTables": "ads_bill_company_1d_di, ads_bill_company_7d_di",
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
                "cycle": "DAY",
                "schedule_time": "08:00",
                "schedule_desc": "每天 08:00 调度",
                "owner": "100043939904",
                "status": "Y11",
                "inputs": ["dwd_bill_company_di"],
                "outputs": ["ads_bill_company_1d_di", "ads_bill_company_7d_di"],
            },
        )

    def test_maps_task_table_names_from_nested_dependency_variants(self):
        snapshot = snapshot_from_api_dump(
            {
                "tasks": {
                    "Response": {
                        "Data": {
                            "Items": [
                                {
                                    "TaskId": "task_nested",
                                    "TaskName": "build_ads_bill_company_1d_di",
                                    "SourceTables": '[{"TableName":"dwd_bill_company_di"},{"Name":"dim_company"}]',
                                    "DependencyConfig": {
                                        "TargetTableList": [
                                            {"DbTableName": "byai_bigdata.ads_bill_company_1d_di"},
                                            {"ResourceName": "byai_bigdata.ads_bill_company_1d_di"},
                                        ]
                                    },
                                }
                            ]
                        }
                    }
                }
            }
        )

        self.assertEqual(snapshot["tasks"][0]["inputs"], ["dwd_bill_company_di", "dim_company"])
        self.assertEqual(snapshot["tasks"][0]["outputs"], ["ads_bill_company_1d_di"])

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

    def test_maps_task_table_names_from_sql_when_structured_fields_missing(self):
        snapshot = snapshot_from_api_dump(
            {
                "tasks": {
                    "Response": {
                        "Data": {
                            "Items": [
                                {
                                    "TaskId": "task_sql",
                                    "TaskName": "sql_task",
                                    "SqlContent": """
                                        -- ignore ods_commented
                                        insert overwrite table ads_bill_company_1d_di
                                        select a.company_id, b.company_name
                                        from byai_bigdata.dwd_bill_company_di a
                                        join dim_company b on a.company_id = b.company_id
                                    """,
                                }
                            ]
                        }
                    }
                }
            }
        )

        self.assertEqual(snapshot["tasks"][0]["outputs"], ["ads_bill_company_1d_di"])
        self.assertEqual(snapshot["tasks"][0]["inputs"], ["dwd_bill_company_di", "dim_company"])

    def test_maps_task_table_names_from_nested_sql_content(self):
        snapshot = snapshot_from_api_dump(
            {
                "tasks": {
                    "Response": {
                        "Data": {
                            "Items": [
                                {
                                    "TaskId": "task_sql_nested",
                                    "TaskName": "nested_sql_task",
                                    "TaskExt": '{"Sql":"create table dws_bill_company_1d_di as select * from ods_bill_company_di"}',
                                }
                            ]
                        }
                    }
                }
            }
        )

        self.assertEqual(snapshot["tasks"][0]["outputs"], ["dws_bill_company_1d_di"])
        self.assertEqual(snapshot["tasks"][0]["inputs"], ["ods_bill_company_di"])

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
