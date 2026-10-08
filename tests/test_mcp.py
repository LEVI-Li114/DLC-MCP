import os
import sqlite3
import unittest
from unittest.mock import patch

from dlc_mcp.assets import AssetStore
from dlc_mcp.cleanup_derived_tables import cleanup_task_name_pseudo_tables
from dlc_mcp.dlc_query import DLCQueryService
from dlc_mcp.live import LiveWeData
from dlc_mcp.mcp import _call_tool, _code_fence_language, _task_type_display, handle_request


class FakeWeDataClient:
    def __init__(self):
        self.calls = []

    def call(self, action, payload):
        self.calls.append((action, dict(payload)))
        if action == "ListProjects":
            return {"Response": {"Data": {"Items": [{"ProjectId": "project", "ProjectName": "prod", "Owner": "data-platform"}], "TotalPageNumber": 1}}}
        if action == "GetProject":
            return {"Response": {"Data": {"ProjectId": payload.get("ProjectId"), "ProjectName": "prod", "Owner": "data-platform", "Status": "enabled"}}}
        if action == "ListProjectMembers":
            return {"Response": {"Data": {"Items": [{"UserId": "u1", "UserName": "zhangsan", "RoleName": "管理员"}], "TotalPageNumber": 1}}}
        if action == "ListDownstreamTasks":
            return {"Response": {"Data": {"Items": [{"TaskId": "task_down", "TaskName": "downstream_task"}], "TotalPageNumber": 1}}}
        if action == "ListUpstreamTasks":
            return {"Response": {"Data": {"Items": [{"TaskId": "task_up", "TaskName": "upstream_task"}], "TotalPageNumber": 1}}}
        if action == "GetTable":
            return {"Response": {"Data": {"Guid": payload.get("TableGuid", "guid_dim_customer"), "TableName": "dim_customer", "ProjectId": payload.get("ProjectId", "project"), "DatabaseName": "dw", "Owner": "data-customer"}}}
        if action == "ListDataSources":
            return {"Response": {"Data": {"Items": [{"Id": 57738, "Name": "crm_fxiaoke_tx", "Type": "MYSQL"}], "TotalPageNumber": 1}}}
        if action == "GetDataSourceRelatedTasks":
            return {
                "Response": {
                    "Data": [
                        {
                            "ProjectId": "project",
                            "ProjectName": "prod",
                            "TaskInfo": [
                                {
                                    "TaskType": "DataDevelopment",
                                    "TaskList": [
                                        {
                                            "TaskId": "20250808124139850",
                                            "TaskName": "m2c_ods_cloud_cost_aliyun_day_di",
                                        }
                                    ],
                                }
                            ],
                        }
                    ]
                }
            }
        if action == "ListTasks" and payload.get("TaskName"):
            return {
                "Response": {
                    "Data": {
                        "Items": [
                            {
                                "TaskId": "20250808124139850",
                                "TaskName": "m2c_ods_cloud_cost_aliyun_day_di",
                            }
                        ],
                        "TotalPageNumber": 1,
                    }
                }
            }
        if action == "ListProcessLineage":
            return {
                "Response": {
                    "Data": {
                        "Items": [
                            {
                                "Source": [
                                    {
                                        "ResourceName": "crm_fxiaoke.cloud_cost_aliyun_day.billing_date",
                                        "ResourceType": "COLUMN",
                                        "ResourceProperties": [{"Name": "TableName", "Value": "cloud_cost_aliyun_day"}],
                                    }
                                ],
                                "Target": [
                                    {
                                        "ResourceName": "byai_bigdata.ods_cloud_cost_aliyun_day_di.billing_date",
                                        "ResourceType": "COLUMN",
                                        "ResourceProperties": [{"Name": "TableName", "Value": "ods_cloud_cost_aliyun_day_di"}],
                                    }
                                ],
                            }
                        ],
                        "TotalPageNumber": 1,
                    }
                }
            }
        if action == "GetTaskCode":
            return {
                "Response": {
                    "Data": {
                        "CodeInfo": "c2VsZWN0ICogZnJvbSBkaW1fY3VzdG9tZXI7",
                        "CodeFileSize": 27,
                    },
                    "RequestId": "req-task-code",
                }
            }
        if action == "GetTask" and payload.get("TaskId") == "task_sync_config":
            return {
                "Response": {
                    "Data": {
                        "TaskId": "task_sync_config",
                        "TaskName": "sync_sms_bill_1d_di",
                        "TaskConfiguration": {
                            "Source": {"NodeType": "SOURCE", "TableName": "crm_fxiaoke.sms_bill_di"},
                            "Target": {"NodeType": "TARGET", "TableName": "ads_sms_bill_1d_di"},
                        },
                    }
                }
            }
        if action == "GetTask" and payload.get("TaskId") == "task_sync_partial":
            return {
                "Response": {
                    "Data": {
                        "TaskId": "task_sync_partial",
                        "TaskName": "sync_sms_bill_partial_di",
                        "TaskConfiguration": {
                            "Target": {"NodeType": "TARGET", "TableName": "ads_sms_bill_1d_di"},
                        },
                    }
                }
            }
        if action == "GetTask":
            return {"Response": {"Data": {}}}
        return {"Response": {"Data": {"Items": [], "TotalPageNumber": 1}}}


class FailingLive:
    def sync_task_code(self, **kwargs):
        raise RuntimeError("live unavailable")


class FakeLivePartitionClient:
    def call(self, action, payload):
        if action == "DescribeTablePartitions":
            return {
                "Response": {
                    "MixedPartitions": {
                        "TotalSize": 1,
                        "IcebergPartitions": [
                            {
                                "Partition": "dt=20260706",
                                "Records": 2,
                                "DataFileStorage": 123,
                                "DataFileSize": 1,
                                "UpdateTime": "2026-07-16T07:02:22+08:00",
                            }
                        ],
                    }
                }
            }
        return {"Response": {"Data": {"Items": []}}}


class DeleteDlcTablesTest(unittest.TestCase):
    def setUp(self):
        self.store = AssetStore(sqlite3.connect(":memory:"))
        self.store.init_schema()

    def test_requires_exact_confirmation_and_discloses_risks(self):
        response = handle_request(self.store, {"jsonrpc": "2.0", "id": 154, "method": "tools/list"})
        tool = {item["name"]: item for item in response["result"]["tools"]}["delete_dlc_tables"]
        self.assertEqual(tool["annotations"], {"readOnlyHint": False, "destructiveHint": True})
        self.assertIn("Iceberg native tables in DataLakeCatalog", tool["description"])
        self.assertIn("7, 15, or 30 days", tool["description"])
        self.assertIn("underlying files are not guaranteed", tool["description"])
        self.assertIn("DLC_QUERY_DATABASE", tool["description"])

        class FakeQueryService:
            def delete_tables(self, tables):
                raise AssertionError("must not execute without exact confirmation")

        response = handle_request(
            self.store,
            {"jsonrpc": "2.0", "id": 155, "method": "tools/call", "params": {"name": "delete_dlc_tables", "arguments": {"tables": [{"table_name": "t"}]}}},
            query_service=FakeQueryService(),
        )
        text = response["result"]["content"][0]["text"]
        self.assertIn("explicit_confirmation_required", text)
        self.assertIn("DataLakeCatalog", text)
        self.assertIn("7、15 或 30 天", text)
        self.assertIn("立即且不可逆", text)
        self.assertIn("底层文件都会保留", text)
        self.assertIn("DLC_QUERY_DATABASE", text)

    def test_delegates_only_after_confirmation(self):
        class FakeQueryService:
            def __init__(self):
                self.tables = None

            def delete_tables(self, tables):
                self.tables = tables
                return {"status": "completed", "results": [{"status": "deleted"}]}

        service = FakeQueryService()
        tables = [{"table_name": "t"}]
        response = handle_request(
            self.store,
            {"jsonrpc": "2.0", "id": 156, "method": "tools/call", "params": {"name": "delete_dlc_tables", "arguments": {"tables": tables, "confirmation": "DELETE TABLE DEFINITIONS"}}},
            query_service=service,
        )
        self.assertEqual(service.tables, tables)
        self.assertIn("completed", response["result"]["content"][0]["text"])

    def test_service_deletes_tables_individually(self):
        class FakeClient:
            def __init__(self):
                self.calls = []

            def call(self, action, payload):
                self.calls.append((action, payload))
                if payload["TableBaseInfo"]["TableName"] == "bad":
                    raise RuntimeError("delete failed")
                if payload["TableBaseInfo"]["TableName"] == "missing-response":
                    return {}
                if payload["TableBaseInfo"]["TableName"] == "api-error":
                    return {"Response": {"Error": {"Code": "InternalError", "Message": "failed"}}}
                return {"Response": {"RequestId": "req-1"}}

        client = FakeClient()
        result = DLCQueryService(client=client).delete_tables(
            [
                {"table_name": "bad", "database_name": "db"},
                {"table_name": "good", "database_name": "db", "datasource_connection_name": "catalog-x"},
                {"table_name": "missing-response", "database_name": "db"},
                {"table_name": "api-error", "database_name": "db"},
            ]
        )
        self.assertEqual([call[0] for call in client.calls], ["DeleteTable"] * 4)
        self.assertEqual(client.calls[0][1]["TableBaseInfo"], {"TableName": "bad", "DatabaseName": "db", "DatasourceConnectionName": "DataLakeCatalog"})
        self.assertEqual(client.calls[1][1]["TableBaseInfo"]["DatasourceConnectionName"], "catalog-x")
        self.assertEqual(result["status"], "partial")
        self.assertEqual([item["status"] for item in result["results"]], ["failed", "deleted", "failed", "failed"])
        self.assertIn("invalid_delete_response", result["results"][2]["error"])
        self.assertIn("InternalError", result["results"][3]["error"])


def test_live_sync_table_partitions_imports_dlc_partition_facts():
    conn = sqlite3.connect(":memory:")
    store = AssetStore(conn)
    store.init_schema()
    store.upsert_table({"name": "ods_cloud_cost_baidu_day_di", "database": "byai_bigdata"})
    store.upsert_column("ods_cloud_cost_baidu_day_di", "dt", "string", "", 1)

    with patch.dict(
        os.environ,
        {
            "WEDATA_PROJECT_ID": "project",
            "WEDATA_PARTITION_SERVICE": "dlc",
            "WEDATA_PARTITION_ACTION": "DescribeTablePartitions",
            "DLC_CATALOG": "DataLakeCatalog",
        },
        clear=False,
    ), patch("dlc_mcp.live._partition_client", return_value=FakeLivePartitionClient()):
        live = LiveWeData(store, client=FakeLivePartitionClient())
        live.sync_table_partitions("ods_cloud_cost_baidu_day_di")

    profile = store.get_table_partition_profile("ods_cloud_cost_baidu_day_di", "")
    assert profile["partition_fact_available"] is True
    assert profile["partition_count"] == 1
    assert profile["latest_partition"]["partition_name"] == "dt=20260706"


class FakePartitionLive:
    def __init__(self):
        self.synced = []

    def sync_table_partitions(self, table_name):
        self.synced.append(table_name)


class RefreshingPartitionLive:
    def __init__(self, store):
        self.store = store
        self.synced = []

    def sync_table_partitions(self, table_name):
        self.synced.append(table_name)
        self.store.upsert_table_partition(
            {
                "table_name": table_name,
                "partition_name": "dt=20260715",
                "partition_date": "20260715",
                "row_count": 2,
                "storage_bytes": 21127,
                "file_count": 1,
                "updated_at": "2026-07-16T07:02:22+08:00",
            }
        )


def test_partition_profile_auto_refreshes_stale_cache_for_requested_partition():
    conn = sqlite3.connect(":memory:")
    store = AssetStore(conn)
    store.init_schema()
    store.upsert_table({"name": "ods_cloud_cost_baidu_day_di", "database": "byai_bigdata"})
    store.upsert_column("ods_cloud_cost_baidu_day_di", "dt", "string", "", 1)
    store.upsert_table_partition(
        {
            "table_name": "ods_cloud_cost_baidu_day_di",
            "partition_name": "dt=20260706",
            "partition_date": "20260706",
            "row_count": 2,
            "storage_bytes": 21127,
            "file_count": 1,
            "updated_at": "2026-07-16T07:02:22+08:00",
        }
    )
    live = RefreshingPartitionLive(store)
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "get_table_partition_profile",
            "arguments": {"table_name": "ods_cloud_cost_baidu_day_di", "partition_date": "20260715"},
        },
    }

    response = _call_tool(store, request, live)
    text = response["result"]["content"][0]["text"]

    assert live.synced == ["ods_cloud_cost_baidu_day_di"]
    assert "数据来源：live" in text
    assert "dt=20260715" in text


def test_partition_profile_legacy_cache_does_not_refresh():
    conn = sqlite3.connect(":memory:")
    store = AssetStore(conn)
    store.init_schema()
    store.upsert_table({"name": "ods_cloud_cost_baidu_day_di", "database": "byai_bigdata"})
    store.upsert_column("ods_cloud_cost_baidu_day_di", "dt", "string", "", 1)
    store.upsert_table_partition(
        {
            "table_name": "ods_cloud_cost_baidu_day_di",
            "partition_name": "dt=20260706",
            "partition_date": "20260706",
            "row_count": 2,
            "storage_bytes": 21127,
            "file_count": 1,
            "updated_at": "2026-07-16T07:02:22+08:00",
        }
    )
    live = RefreshingPartitionLive(store)
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "get_table_partition_profile",
            "arguments": {
                "table_name": "ods_cloud_cost_baidu_day_di",
                "partition_date": "20260715",
                "source": "legacy_cache",
            },
        },
    }

    response = _call_tool(store, request, live)
    text = response["result"]["content"][0]["text"]

    assert live.synced == []
    assert "数据来源：legacy_cache" in text
    assert "dt=20260706" in text
    assert "dt=20260715" not in text


def test_partition_profile_live_true_triggers_partition_refresh():
    conn = sqlite3.connect(":memory:")
    store = AssetStore(conn)
    store.init_schema()
    store.upsert_table({"name": "ods_cloud_cost_baidu_day_di", "database": "byai_bigdata"})
    store.upsert_column("ods_cloud_cost_baidu_day_di", "dt", "string", "", 1)
    live = FakePartitionLive()
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "get_table_partition_profile",
            "arguments": {"table_name": "ods_cloud_cost_baidu_day_di", "partition_date": "", "live": True},
        },
    }

    response = _call_tool(store, request, live)
    text = response["result"]["content"][0]["text"]

    assert live.synced == ["ods_cloud_cost_baidu_day_di"]
    assert "实时刷新：是" in text
    assert "触发原因：user_requested" in text


class FailingTaskRunLive:
    def sync_task_runs(self, task_name="", task_id="", instance_date=""):
        raise RuntimeError("ListTaskInstances failed: InternalError temporary unavailable")


def test_daily_report_auto_requires_patrol_snapshot():
    conn = sqlite3.connect(":memory:")
    store = AssetStore(conn)
    store.init_schema()
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "get_asset_governance_daily_report",
            "arguments": {"instance_date": "2026-07-16"},
        },
    }

    response = _call_tool(store, request)
    text = response["result"]["content"][0]["text"]

    assert "数据来源：patrol_snapshot" in text
    assert "patrol_snapshot_not_found" in text


def test_daily_report_auto_reads_latest_patrol_snapshot():
    conn = sqlite3.connect(":memory:")
    store = AssetStore(conn)
    store.init_schema()
    store.create_patrol_run("run-1", "2026-07-16", "daily_p0", {})
    store.insert_patrol_metric({"run_id": "run-1", "metric_name": "checked_count", "metric_value": 1, "dimension": {}})
    store.finish_patrol_run("run-1", "completed", {"checked_count": 1, "error_count": 0})
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "get_asset_governance_daily_report",
            "arguments": {"instance_date": "2026-07-16"},
        },
    }

    response = _call_tool(store, request)
    text = response["result"]["content"][0]["text"]

    assert "数据来源：patrol_snapshot" in text
    assert "run-1" in text
    assert "checked_count" in text


def test_issue_inventory_auto_reads_patrol_findings():
    conn = sqlite3.connect(":memory:")
    store = AssetStore(conn)
    store.init_schema()
    store.create_patrol_run("run-1", "2026-07-16", "daily_p0", {})
    store.insert_patrol_finding(
        {
            "run_id": "run-1",
            "asset_name": "ods_cloud_cost_baidu_day_di",
            "issue_type": "missing_quality_rules",
            "severity": "P1",
            "evidence": {"quality_rule_count": 0},
            "owner_bucket": "warehouse_owner",
            "suggested_action": "Add or confirm quality monitoring rule coverage.",
        }
    )
    store.finish_patrol_run("run-1", "completed", {"checked_count": 1, "error_count": 0})
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "get_asset_governance_issue_inventory",
            "arguments": {"instance_date": "2026-07-16"},
        },
    }

    response = _call_tool(store, request)
    text = response["result"]["content"][0]["text"]

    assert "数据来源：patrol_snapshot" in text
    assert "missing_quality_rules" in text
    assert "ods_cloud_cost_baidu_day_di" in text



def test_daily_report_markdown_renders_enriched_patrol_snapshot():
    store = AssetStore(sqlite3.connect(":memory:"))
    store.init_schema()
    store.create_patrol_run("run-rich", "2026-07-16", "daily_core", {})
    store.upsert_patrol_asset_snapshot(
        {
            "run_id": "run-rich",
            "asset_name": "ads_360_fin_income_cost_1d_di",
            "asset_type": "table",
            "layer": "ads",
            "owner": "tencent",
            "core_level": "P2",
            "status": "p1",
            "snapshot": {
                "source_policy": {"metadata": "cache", "tasks": "live_only", "quality": "live_only", "runs": "live_only"},
                "cached": {"columns": {"count": 36}, "lineage": {"upstream_count": 26, "downstream_count": 13}},
                "live": {"tasks": {"status": "missing"}, "quality": {"status": "missing"}, "runs": {"status": "missing"}},
                "coverage_status": "p1",
            },
        }
    )
    store.insert_patrol_finding(
        {
            "run_id": "run-rich",
            "asset_name": "ads_360_fin_income_cost_1d_di",
            "issue_type": "missing_producer_task",
            "severity": "P1",
            "evidence": {"source": "live", "status": "missing"},
            "owner_bucket": "warehouse_owner",
            "suggested_action": "Check ListTasks inputs/outputs or SQL parsing for this table.",
        }
    )
    store.finish_patrol_run(
        "run-rich",
        "partial",
        {"checked_count": 1, "error_count": 0, "live_partial_count": 1, "p1_count": 1},
    )

    text = _call_tool(
        store,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "get_asset_governance_daily_report", "arguments": {"instance_date": "2026-07-16"}},
        },
    )["result"]["content"][0]["text"]

    assert "数据来源与查询策略" in text
    assert "ads_360_fin_income_cost_1d_di" in text
    assert "missing_producer_task" in text
    assert "live_only" in text



def test_task_and_table_profile_render_resolved_owner():
    store = AssetStore(sqlite3.connect(":memory:"))
    store.init_schema()
    store.upsert_table({"name": "ads_system_owned", "layer": "ads", "owner": "tencent", "data_source_id": "ds_001"})
    store.upsert_column("ads_system_owned", "dt", "string", "", 1)
    store.upsert_data_source({"id": "ds_001", "name": "DLC", "owner": "100043939904", "config": {}})
    store.upsert_task({"id": "task_owner", "name": "ads_system_owned", "owner": "100043939904", "outputs": ["ads_system_owned"]})

    task_text = _call_tool(
        store,
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "search_tasks", "arguments": {"query": "ads_system_owned"}}},
    )["result"]["content"][0]["text"]
    profile_text = _call_tool(
        store,
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "get_table_profile", "arguments": {"table_name": "ads_system_owned"}}},
    )["result"]["content"][0]["text"]

    assert "100043939904 / luyuan" in task_text
    assert "解析负责人：`luyuan`" in profile_text
    assert "producer_task_owner" in profile_text


def test_task_runs_live_failure_returns_unknown_not_empty_runs():
    conn = sqlite3.connect(":memory:")
    store = AssetStore(conn)
    store.init_schema()
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "get_task_runs",
            "arguments": {"task_id": "task-1", "instance_date": "2026-07-15"},
        },
    }

    response = _call_tool(store, request, FailingTaskRunLive())
    text = response["result"]["content"][0]["text"]

    assert "数据来源：partial_live" in text
    assert "task_runs" in text
    assert "check_failed" in text
    assert "InternalError" in text


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
        self.store.upsert_task(
            {
                "id": "sync_002",
                "name": "m2c_ods_crm_payment_plan_df",
                "outputs": ["m2c_ods_crm_payment_plan_df"],
            }
        )
        self.store.replace_data_source_tasks(
            "ds_001",
            [
                {"task_id": "sync_001", "task_name": "sync_mysql_prod", "task_type": "DataDevelopment", "project_name": "prod"},
                {"task_id": "sync_002", "task_name": "m2c_ods_crm_payment_plan_df", "task_type": "DataDevelopment", "project_name": "prod"},
            ],
        )
        self.store.upsert_column("m2c_ods_crm_payment_plan_df", "id", "bigint", "Primary key", 1)
        self.store.upsert_expert_label({"asset_name": "dim_customer", "core_level": "P1", "value_tier": "重要", "domain": "客户", "use_case": "客户分析"})

    def test_live_wedata_syncs_task_code(self):
        client = FakeWeDataClient()
        with patch.dict(os.environ, {"WEDATA_PROJECT_ID": "project"}, clear=False):
            live = LiveWeData(self.store, client=client)
            live.sync_task_code(task_id="task_001")

        actions = [action for action, payload in client.calls]
        get_task_code_payloads = [payload for action, payload in client.calls if action == "GetTaskCode"]
        cached = self.store.get_task_code(project_id="project", task_id="task_001")

        self.assertIn("GetTaskCode", actions)
        self.assertEqual(get_task_code_payloads[0]["ProjectId"], "project")
        self.assertEqual(get_task_code_payloads[0]["TaskId"], "task_001")
        self.assertEqual(cached["code_text"], "select * from dim_customer;")
        self.assertEqual(cached["encoding"], "base64")

    def test_tools_list_includes_get_task_code(self):
        response = handle_request(self.store, {"jsonrpc": "2.0", "id": 40, "method": "tools/list"})
        tools = {tool["name"]: tool for tool in response["result"]["tools"]}
        self.assertIn("get_task_code", tools)
        self.assertEqual(tools["get_task_code"]["annotations"], {"readOnlyHint": True})
        self.assertEqual(tools["search_tasks"]["annotations"], {"readOnlyHint": True})

    def test_tools_list_includes_dlc_sql_tools_with_safety_annotations(self):
        response = handle_request(self.store, {"jsonrpc": "2.0", "id": 140, "method": "tools/list"})
        tools = {tool["name"]: tool for tool in response["result"]["tools"]}

        self.assertEqual(
            tools["submit_dlc_sql_query"]["annotations"],
            {"readOnlyHint": False, "destructiveHint": False},
        )
        self.assertEqual(tools["get_dlc_sql_query_result"]["annotations"], {"readOnlyHint": True})

    def test_dlc_sql_tools_delegate_to_query_service(self):
        class FakeQueryService:
            def submit(self, sql, **options):
                return {"status": "submitted", "task_id": "task-1", "engine_type": "spark", "sql_sha256": "abc", **options}

            def result(self, task_id, **options):
                return {"task_id": task_id, "state": 2, "status": "succeeded", "progress_percent": 100, "rows": [{"count": 2}], **options}

        submitted = handle_request(
            self.store,
            {"jsonrpc": "2.0", "id": 141, "method": "tools/call", "params": {"name": "submit_dlc_sql_query", "arguments": {"sql": "SELECT 1", "database_name": "crm"}}},
            query_service=FakeQueryService(),
        )
        fetched = handle_request(
            self.store,
            {"jsonrpc": "2.0", "id": 142, "method": "tools/call", "params": {"name": "get_dlc_sql_query_result", "arguments": {"task_id": "task-1", "max_results": 10}}},
            query_service=FakeQueryService(),
        )

        self.assertIn("task-1", submitted["result"]["content"][0]["text"])
        self.assertIn("succeeded", fetched["result"]["content"][0]["text"])
        self.assertIn("count", fetched["result"]["content"][0]["text"])

    def test_dlc_task_resource_usage_tool_requires_explicit_task_instance_id(self):
        response = handle_request(self.store, {"jsonrpc": "2.0", "id": 143, "method": "tools/list"})
        tools = {tool["name"]: tool for tool in response["result"]["tools"]}

        self.assertIn("get_dlc_task_resource_usage", tools)
        self.assertEqual(tools["get_dlc_task_resource_usage"]["annotations"], {"readOnlyHint": True})
        self.assertEqual(tools["get_dlc_task_resource_usage"]["inputSchema"]["required"], ["task_instance_id"])
        self.assertNotIn("source", tools["get_dlc_task_resource_usage"]["inputSchema"]["properties"])

    def test_dlc_task_resource_usage_tool_delegates_to_query_service(self):
        class FakeQueryService:
            def __init__(self):
                self.calls = []

            def resource_usage(self, task_instance_id, **options):
                self.calls.append((task_instance_id, options))
                return {
                    "task_instance_id": task_instance_id,
                    "timestamps": [1750238853000],
                    "core_usage": [2],
                    "series": [{"timestamp": 1750238853000, "core_usage": 2}],
                    "request_id": "request-3",
                }

        service = FakeQueryService()
        response = handle_request(
            self.store,
            {
                "jsonrpc": "2.0",
                "id": 144,
                "method": "tools/call",
                "params": {"name": "get_dlc_task_resource_usage", "arguments": {"task_instance_id": "15eb48854c1c11f083e8525400e26adf"}},
            },
            query_service=service,
        )

        self.assertEqual(
            service.calls,
            [
                (
                    "15eb48854c1c11f083e8525400e26adf",
                    {"include_cost": False, "cost_task_id": "", "cost_start_time": "", "cost_end_time": "", "cost_limit": 10},
                )
            ],
        )
        text = response["result"]["content"][0]["text"]
        self.assertIn("15eb48854c1c11f083e8525400e26adf", text)
        self.assertIn("Core 用量曲线", text)
        self.assertIn("dlc_live", text)

    def test_dlc_task_resource_usage_tool_passes_cost_options_without_mapping_ids(self):
        class FakeQueryService:
            def __init__(self):
                self.calls = []

            def resource_usage(self, task_instance_id, **options):
                self.calls.append((task_instance_id, options))
                return {
                    "task_instance_id": task_instance_id,
                    "timestamps": [],
                    "core_usage": [],
                    "series": [],
                    "request_id": "request-3",
                    "cost_analysis": {
                        "task_id": options.get("cost_task_id"),
                        "start_time": "2025-06-18 00:00:00",
                        "end_time": "2025-06-18 12:00:00",
                        "total_count": 1,
                        "tasks": [
                            {
                                "id": "67ea3d234006dc901",
                                "state": 2,
                                "data_engine_name": "super_spark_270",
                                "instance_start_time": 1733842361290,
                                "job_time_sum_ms": 35589,
                                "task_time_sum_seconds": 403,
                            }
                        ],
                    },
                }

        service = FakeQueryService()
        response = handle_request(
            self.store,
            {
                "jsonrpc": "2.0",
                "id": 146,
                "method": "tools/call",
                "params": {
                    "name": "get_dlc_task_resource_usage",
                    "arguments": {
                        "task_instance_id": "15eb48854c1c11f083e8525400e26adf",
                        "include_cost": True,
                        "cost_task_id": "e386471f-139a-4e59-877f-50ece8135b99",
                        "cost_start_time": "2025-06-18 00:00:00",
                        "cost_end_time": "2025-06-18 12:00:00",
                        "cost_limit": 5,
                    },
                },
            },
            query_service=service,
        )

        task_instance_id, options = service.calls[0]
        self.assertEqual(task_instance_id, "15eb48854c1c11f083e8525400e26adf")
        self.assertTrue(options["include_cost"])
        self.assertEqual(options["cost_task_id"], "e386471f-139a-4e59-877f-50ece8135b99")
        self.assertEqual(options["cost_limit"], 5)
        text = response["result"]["content"][0]["text"]
        self.assertIn("DLC CU 消耗分析", text)
        self.assertIn("e386471f-139a-4e59-877f-50ece8135b99", text)
        self.assertIn("403", text)

    def test_dlc_task_resource_usage_tool_does_not_map_wedata_instance_id(self):
        self.store.upsert_task_run(
            {
                "project_id": "project",
                "task_id": "20250808121806623",
                "task_name": "dwd_fin_other_cost_data_df",
                "instance_id": "20250808121806623_2026-09-29 00:00:00",
                "instance_date": "2026-09-29",
                "status": "COMPLETED",
            }
        )

        class RecordingQueryService:
            def __init__(self):
                self.calls = []

            def resource_usage(self, task_instance_id, **options):
                self.calls.append(task_instance_id)
                return {"task_instance_id": task_instance_id, "timestamps": [], "core_usage": [], "series": [], "request_id": "r"}

        service = RecordingQueryService()
        response = handle_request(
            self.store,
            {
                "jsonrpc": "2.0",
                "id": 145,
                "method": "tools/call",
                "params": {"name": "get_dlc_task_resource_usage", "arguments": {"task_instance_id": "20250808121806623_2026-09-29 00:00:00"}},
            },
            query_service=service,
        )

        self.assertEqual(service.calls, ["20250808121806623_2026-09-29 00:00:00"])
        self.assertIn("未返回 Core 用量曲线", response["result"]["content"][0]["text"])

    def test_dlc_task_resource_usage_tool_reports_missing_id_and_service(self):
        missing_id = handle_request(
            self.store,
            {"jsonrpc": "2.0", "id": 146, "method": "tools/call", "params": {"name": "get_dlc_task_resource_usage", "arguments": {}}},
            query_service=None,
        )
        no_service = handle_request(
            self.store,
            {"jsonrpc": "2.0", "id": 147, "method": "tools/call", "params": {"name": "get_dlc_task_resource_usage", "arguments": {"task_instance_id": "abc"}}},
            query_service=None,
        )

        self.assertIn("dlc_query_service_unavailable", missing_id["result"]["content"][0]["text"])
        self.assertIn("dlc_query_service_unavailable", no_service["result"]["content"][0]["text"])

    def test_get_task_code_returns_cached_sql(self):
        self.store.upsert_task_code(
            "project",
            "task_001",
            "build_dim_customer",
            "c2VsZWN0IDE7",
            "select 1;",
            9,
            "base64",
            {"CodeInfo": "c2VsZWN0IDE7", "CodeFileSize": 9},
        )

        response = handle_request(
            self.store,
            {"jsonrpc": "2.0", "id": 41, "method": "tools/call", "params": {"name": "get_task_code", "arguments": {"task_id": "task_001"}}},
        )
        text = response["result"]["content"][0]["text"]

        self.assertIn("任务代码", text)
        self.assertIn("task_001", text)
        self.assertIn("build_dim_customer", text)
        self.assertIn("```sql", text)
        self.assertIn("select 1;", text)

    def test_get_task_code_cache_hit_includes_query_metadata(self):
        self.store.upsert_task_code(
            "project",
            "task_001",
            "build_dim_customer",
            "c2VsZWN0IDE7",
            "select 1;",
            9,
            "base64",
            {"CodeInfo": "c2VsZWN0IDE7", "CodeFileSize": 9},
        )

        response = handle_request(
            self.store,
            {"jsonrpc": "2.0", "id": 141, "method": "tools/call", "params": {"name": "get_task_code", "arguments": {"task_id": "task_001"}}},
        )
        text = response["result"]["content"][0]["text"]

        self.assertIn("查询元信息", text)
        self.assertIn("数据来源：live", text)
        self.assertIn("实时刷新：否", text)

    def test_get_task_code_live_success_includes_refresh_metadata(self):
        client = FakeWeDataClient()
        with patch.dict(os.environ, {"WEDATA_PROJECT_ID": "project"}, clear=False):
            live = LiveWeData(self.store, client=client)
            response = handle_request(
                self.store,
                {"jsonrpc": "2.0", "id": 142, "method": "tools/call", "params": {"name": "get_task_code", "arguments": {"task_id": "task_001", "live": True}}},
                live=live,
            )

        text = response["result"]["content"][0]["text"]
        self.assertIn("数据来源：cache_after_live_refresh", text)
        self.assertIn("实时刷新：是", text)
        self.assertIn("触发原因：user_requested", text)
        self.assertIn("select * from dim_customer;", text)

    def test_get_task_code_live_failure_keeps_cached_data_and_reports_error(self):
        self.store.upsert_task_code(
            "project",
            "task_001",
            "build_dim_customer",
            "c2VsZWN0IDE7",
            "select 1;",
            9,
            "base64",
            {"CodeInfo": "c2VsZWN0IDE7", "CodeFileSize": 9},
        )
        with patch.dict(os.environ, {"WEDATA_PROJECT_ID": "project"}, clear=False):
            response = handle_request(
                self.store,
                {"jsonrpc": "2.0", "id": 143, "method": "tools/call", "params": {"name": "get_task_code", "arguments": {"task_id": "task_001", "live": True}}},
                live=FailingLive(),
            )

        text = response["result"]["content"][0]["text"]
        self.assertIn("数据来源：live_refresh_failed_cache", text)
        self.assertIn("实时刷新：失败", text)
        self.assertIn("失败原因：live unavailable", text)
        self.assertIn("select 1;", text)

    def test_daily_report_uses_snapshot_metadata_without_live_refresh(self):
        response = handle_request(
            self.store,
            {"jsonrpc": "2.0", "id": 144, "method": "tools/call", "params": {"name": "get_asset_governance_daily_report", "arguments": {}}},
            live=FailingLive(),
        )

        text = response["result"]["content"][0]["text"]
        self.assertIn("数据来源：patrol_snapshot", text)
        self.assertIn("实时刷新：否", text)
        self.assertIn("patrol_snapshot_not_found", text)

    def test_daily_report_markdown_renders_execution_sections(self):
        self.store.create_patrol_run("run-sections", "", "daily_p0", {})
        self.store.insert_patrol_metric({"run_id": "run-sections", "metric_name": "checked_count", "metric_value": 1, "dimension": {}})
        self.store.finish_patrol_run("run-sections", "completed", {"checked_count": 1, "error_count": 0})
        response = handle_request(
            self.store,
            {"jsonrpc": "2.0", "id": 145, "method": "tools/call", "params": {"name": "get_asset_governance_daily_report", "arguments": {}}},
        )
        text = response["result"]["content"][0]["text"]

        self.assertIn("每日巡检报告", text)
        self.assertIn("巡检指标", text)
        self.assertIn("本次巡检未完成检查", text)

    def test_get_task_code_validates_missing_identity(self):
        response = handle_request(
            self.store,
            {"jsonrpc": "2.0", "id": 42, "method": "tools/call", "params": {"name": "get_task_code", "arguments": {}}},
        )
        self.assertIn("missing_task_identity", response["result"]["content"][0]["text"])

    def test_get_task_code_live_refreshes_and_returns_decoded_sql(self):
        client = FakeWeDataClient()
        with patch.dict(os.environ, {"WEDATA_PROJECT_ID": "project"}, clear=False):
            live = LiveWeData(self.store, client=client)
            response = handle_request(
                self.store,
                {"jsonrpc": "2.0", "id": 43, "method": "tools/call", "params": {"name": "get_task_code", "arguments": {"task_id": "task_001", "live": True}}},
                live=live,
            )

        text = response["result"]["content"][0]["text"]
        self.assertIn("select * from dim_customer;", text)
        self.assertIn("base64", text)
        self.assertIn("GetTaskCode", [action for action, payload in client.calls])

    def test_get_task_code_query_mode_falls_back_live_on_cache_miss(self):
        client = FakeWeDataClient()
        with patch.dict(os.environ, {"WEDATA_PROJECT_ID": "project"}, clear=False):
            live = LiveWeData(self.store, client=client)
            response = handle_request(
                self.store,
                {"jsonrpc": "2.0", "id": 45, "method": "tools/call", "params": {"name": "get_task_code", "arguments": {"task_id": "task_001"}}},
                live=live,
            )

        text = response["result"]["content"][0]["text"]
        cached = self.store.get_task_code(project_id="project", task_id="task_001")
        self.assertIn("select * from dim_customer;", text)
        self.assertEqual(cached["code_text"], "select * from dim_customer;")
        self.assertIn("GetTaskCode", [action for action, payload in client.calls])

    def test_get_task_code_query_mode_uses_cache_without_live_call(self):
        self.store.upsert_task_code(
            "project",
            "task_001",
            "build_dim_customer",
            "c2VsZWN0IDE7",
            "select 1;",
            9,
            "base64",
            {"CodeInfo": "c2VsZWN0IDE7", "CodeFileSize": 9},
        )
        client = FakeWeDataClient()
        with patch.dict(os.environ, {"WEDATA_PROJECT_ID": "project"}, clear=False):
            live = LiveWeData(self.store, client=client)
            response = handle_request(
                self.store,
                {"jsonrpc": "2.0", "id": 46, "method": "tools/call", "params": {"name": "get_task_code", "arguments": {"task_id": "task_001"}}},
                live=live,
            )

        text = response["result"]["content"][0]["text"]
        self.assertIn("select 1;", text)
        self.assertNotIn("GetTaskCode", [action for action, payload in client.calls])

    def test_get_task_code_parses_output_tables_and_writes_mapping(self):
        self.store.upsert_task_code(
            "project",
            "task_001",
            "build_dim_customer",
            "",
            "insert overwrite table dws_new_output select * from ods_customer;",
            62,
            "base64",
            {"CodeInfo": "", "CodeFileSize": 62},
        )

        response = handle_request(
            self.store,
            {"jsonrpc": "2.0", "id": 148, "method": "tools/call", "params": {"name": "get_task_code", "arguments": {"task_id": "task_001"}}},
        )
        text = response["result"]["content"][0]["text"]

        self.assertIn("输出表：`dws_new_output`", text)
        self.assertEqual(self.store.get_table_tasks("dws_new_output")["tasks"][0]["id"], "task_001")
        self.assertEqual(self.store.get_table_tasks("dim_customer")["tasks"][0]["id"], "task_001")

    def test_get_task_code_reports_no_output_tables_for_unsupported_task_type(self):
        self.store.upsert_task({"id": "task_pyspark", "name": "build_pyspark", "task_type": "31"})
        self.store.upsert_task_code(
            "project",
            "task_pyspark",
            "build_pyspark",
            "",
            "df.write.saveAsTable('ads_pyspark')",
            33,
            "base64",
            {"CodeInfo": "", "CodeFileSize": 33},
        )

        response = handle_request(
            self.store,
            {"jsonrpc": "2.0", "id": 149, "method": "tools/call", "params": {"name": "get_task_code", "arguments": {"task_id": "task_pyspark"}}},
        )
        text = response["result"]["content"][0]["text"]

        self.assertIn("仅支持 SQL 类任务解析", text)
        self.assertEqual(self.store.get_table_tasks("ads_pyspark")["tasks"], [])

    def test_get_task_code_resolves_offline_sync_tables_from_task_config(self):
        self.store.upsert_task({"id": "task_sync_config", "name": "sync_sms_bill_1d_di", "task_type": "26"})
        client = FakeWeDataClient()
        with patch.dict(os.environ, {"WEDATA_PROJECT_ID": "project"}, clear=False):
            live = LiveWeData(self.store, client=client)
            response = handle_request(
                self.store,
                {
                    "jsonrpc": "2.0",
                    "id": 150,
                    "method": "tools/call",
                    "params": {"name": "get_task_code", "arguments": {"task_id": "task_sync_config", "live": True}},
                },
                live=live,
            )
        text = response["result"]["content"][0]["text"]
        actions = [action for action, payload in client.calls]

        self.assertIn("输入表：`sms_bill_di`", text)
        self.assertIn("输出表：`ads_sms_bill_1d_di`", text)
        self.assertIn("证据来源：`wedata_task_config`", text)
        self.assertNotIn("ListProcessLineage", actions)
        self.assertNotIn("GetTaskCode", actions)
        cached = self.store.get_task("task_sync_config")
        self.assertEqual(cached["inputs"], ["sms_bill_di"])
        self.assertEqual(cached["outputs"], ["ads_sms_bill_1d_di"])

    def test_get_task_code_falls_back_to_lineage_when_sync_config_is_incomplete(self):
        self.store.upsert_task({"id": "task_sync_partial", "name": "sync_sms_bill_partial_di", "task_type": "26"})
        client = FakeWeDataClient()
        with patch.dict(os.environ, {"WEDATA_PROJECT_ID": "project"}, clear=False):
            live = LiveWeData(self.store, client=client)
            response = handle_request(
                self.store,
                {
                    "jsonrpc": "2.0",
                    "id": 151,
                    "method": "tools/call",
                    "params": {"name": "get_task_code", "arguments": {"task_id": "task_sync_partial", "live": True}},
                },
                live=live,
            )
        text = response["result"]["content"][0]["text"]
        actions = [action for action, payload in client.calls]

        self.assertIn("ListProcessLineage", actions)
        self.assertIn("输入表：`cloud_cost_aliyun_day`", text)
        self.assertIn("输出表：`ads_sms_bill_1d_di`", text)
        self.assertNotIn("ods_cloud_cost_aliyun_day_di", text)
        self.assertIn("证据来源：`wedata_task_lineage`", text)

    def test_get_task_code_returns_cached_sync_mapping_without_live(self):
        self.store.upsert_task({"id": "task_sync_cached", "name": "sync_cached_di", "task_type": "26"})
        self.store.upsert_task_table_mappings("task_sync_cached", ["ods_sms_bill_di"], "input")
        self.store.upsert_task_table_mappings("task_sync_cached", ["ads_sms_bill_di"], "output")

        response = handle_request(
            self.store,
            {"jsonrpc": "2.0", "id": 152, "method": "tools/call", "params": {"name": "get_task_code", "arguments": {"task_id": "task_sync_cached"}}},
        )
        text = response["result"]["content"][0]["text"]

        self.assertIn("输入表：`ods_sms_bill_di`", text)
        self.assertIn("输出表：`ads_sms_bill_di`", text)
        self.assertIn("证据来源：`cache`", text)

    def test_get_task_code_reports_cache_miss_for_sync_task_without_evidence(self):
        self.store.upsert_task({"id": "task_sync_empty", "name": "sync_empty_di", "task_type": "26"})

        response = handle_request(
            self.store,
            {"jsonrpc": "2.0", "id": 153, "method": "tools/call", "params": {"name": "get_task_code", "arguments": {"task_id": "task_sync_empty"}}},
        )
        text = response["result"]["content"][0]["text"]

        self.assertIn("task_code_not_found", text)
        self.assertEqual(self.store.get_task("task_sync_empty")["outputs"], [])

    def test_list_tasks_renders_total_count_and_rows(self):
        self.store.upsert_task({"id": "task_dlc_1", "name": "build_dws_a", "task_type": "32", "owner": "alice"})
        self.store.upsert_task({"id": "task_dlc_2", "name": "build_ads_a", "task_type": "32", "owner": "bob"})

        response = handle_request(
            self.store,
            {"jsonrpc": "2.0", "id": 150, "method": "tools/call", "params": {"name": "list_tasks", "arguments": {"task_type": "32", "limit": 1}}},
        )
        text = response["result"]["content"][0]["text"]

        total = self.store.list_tasks(task_type="32")["total_count"]
        self.assertIn(f"总数：**{total}**", text)
        self.assertIn("本页：1（limit=1，offset=0）", text)
        self.assertIn("task_dlc_2", text)
        self.assertNotIn("task_dlc_1", text)

    def test_list_tasks_is_listed_in_tools(self):
        response = handle_request(
            self.store,
            {"jsonrpc": "2.0", "id": 151, "method": "tools/list", "params": {}},
        )
        names = [tool["name"] for tool in response["result"]["tools"]]

        self.assertIn("list_tasks", names)

    def test_list_tasks_live_refreshes_by_keyword(self):
        client = FakeWeDataClient()
        with patch.dict(os.environ, {"WEDATA_PROJECT_ID": "project"}, clear=False):
            live = LiveWeData(self.store, client=client)
            response = handle_request(
                self.store,
                {
                    "jsonrpc": "2.0",
                    "id": 152,
                    "method": "tools/call",
                    "params": {"name": "list_tasks", "arguments": {"keyword": "m2c_ods_cloud_cost_aliyun_day_di", "live": True}},
                },
                live=live,
            )

        text = response["result"]["content"][0]["text"]

        self.assertIn("m2c_ods_cloud_cost_aliyun_day_di", text)
        self.assertTrue(any(call[0] == "ListTasks" and call[1].get("TaskName") == "m2c_ods_cloud_cost_aliyun_day_di" for call in client.calls))

    def test_list_tasks_live_requires_keyword(self):
        response = handle_request(
            self.store,
            {"jsonrpc": "2.0", "id": 153, "method": "tools/call", "params": {"name": "list_tasks", "arguments": {"live": True}}},
        )
        text = response["result"]["content"][0]["text"]

        self.assertIn("keyword_required_for_live", text)

    def test_get_task_code_resolves_cached_task_name(self):
        self.store.upsert_task_code(
            "project",
            "task_001",
            "build_dim_customer",
            "c2VsZWN0IDE7",
            "select 1;",
            9,
            "base64",
            {"CodeInfo": "c2VsZWN0IDE7", "CodeFileSize": 9},
        )

        response = handle_request(
            self.store,
            {"jsonrpc": "2.0", "id": 44, "method": "tools/call", "params": {"name": "get_task_code", "arguments": {"task_name": "build_dim_customer"}}},
        )
        text = response["result"]["content"][0]["text"]

        self.assertIn("task_001", text)
        self.assertIn("select 1;", text)

    def test_calls_project_tools_from_cache(self):
        self.store.upsert_project({"id": "project", "name": "prod", "display_name": "生产项目", "owner": "data-platform", "status": "enabled"})
        self.store.replace_project_members("project", [{"member_id": "u1", "member_name": "zhangsan", "role_name": "管理员", "role_id": "r1"}])

        list_response = handle_request(self.store, {"jsonrpc": "2.0", "id": 31, "method": "tools/call", "params": {"name": "list_projects", "arguments": {"query": "生产"}}})
        get_response = handle_request(self.store, {"jsonrpc": "2.0", "id": 32, "method": "tools/call", "params": {"name": "get_project", "arguments": {"project_id": "project"}}})
        members_response = handle_request(self.store, {"jsonrpc": "2.0", "id": 33, "method": "tools/call", "params": {"name": "list_project_members", "arguments": {"project_id": "project"}}})

        self.assertIn("项目列表", list_response["result"]["content"][0]["text"])
        self.assertIn("生产项目", list_response["result"]["content"][0]["text"])
        self.assertIn("项目详情", get_response["result"]["content"][0]["text"])
        self.assertIn("data-platform", get_response["result"]["content"][0]["text"])
        self.assertIn("项目成员", members_response["result"]["content"][0]["text"])
        self.assertIn("zhangsan", members_response["result"]["content"][0]["text"])

    def test_list_projects_query_mode_falls_back_live_on_empty_cache(self):
        client = FakeWeDataClient()
        with patch.dict(os.environ, {"WEDATA_PROJECT_ID": "project"}, clear=False):
            live = LiveWeData(self.store, client=client)
            response = handle_request(
                self.store,
                {"jsonrpc": "2.0", "id": 47, "method": "tools/call", "params": {"name": "list_projects", "arguments": {"query": "prod"}}},
                live=live,
            )

        text = response["result"]["content"][0]["text"]
        self.assertIn("项目列表", text)
        self.assertIn("prod", text)
        self.assertIn("ListProjects", [action for action, payload in client.calls])

    def test_search_tasks_query_mode_falls_back_live_on_empty_cache(self):
        client = FakeWeDataClient()
        with patch.dict(os.environ, {"WEDATA_PROJECT_ID": "project"}, clear=False):
            live = LiveWeData(self.store, client=client)
            response = handle_request(
                self.store,
                {"jsonrpc": "2.0", "id": 48, "method": "tools/call", "params": {"name": "search_tasks", "arguments": {"query": "m2c_ods_cloud_cost_aliyun_day_di"}}},
                live=live,
            )

        text = response["result"]["content"][0]["text"]
        self.assertIn("m2c_ods_cloud_cost_aliyun_day_di", text)
        self.assertIn("ListTasks", [action for action, payload in client.calls])

    def test_cleanup_task_name_pseudo_tables_cli_dry_runs_and_applies(self):
        self.store.upsert_data_source({"id": "57738", "name": "crm_fxiaoke_tx"})
        self.store.upsert_table({"name": "m2c_ods_cloud_cost_aliyun_day_di", "data_source_id": "57738"})
        self.store.upsert_table({"name": "ods_cloud_cost_aliyun_day_di", "guid": "guid_001", "database": "byai_bigdata"})
        self.store.upsert_task({"id": "sync_aliyun", "name": "m2c_ods_cloud_cost_aliyun_day_di", "outputs": ["ods_cloud_cost_aliyun_day_di"]})

        dry_run = cleanup_task_name_pseudo_tables(self.store.conn, "57738")
        applied = cleanup_task_name_pseudo_tables(self.store.conn, "57738", apply=True)

        self.assertEqual(dry_run["candidate_tables"], 1)
        self.assertEqual(applied["deleted_tables"], 1)
        self.assertEqual(self.store.get_table_profile("m2c_ods_cloud_cost_aliyun_day_di")["error"], "table_not_found")
        self.assertNotIn("error", self.store.get_table_profile("ods_cloud_cost_aliyun_day_di"))

        self.store.replace_task_relations("project", "task_001", "downstream", [{"related_task_id": "task_002", "related_task_name": "build_ads_customer"}])
        self.store.replace_task_relations("project", "task_001", "upstream", [{"related_task_id": "task_000", "related_task_name": "build_ods_customer"}])
        self.store.upsert_table({"name": "dim_customer", "guid": "guid_dim_customer", "project_id": "project", "database": "dw", "owner": "data-customer", "table_type": "MANAGED_TABLE"})

        downstream = handle_request(self.store, {"jsonrpc": "2.0", "id": 34, "method": "tools/call", "params": {"name": "list_task_relations", "arguments": {"project_id": "project", "task_id": "task_001", "direction": "downstream"}}})
        upstream = handle_request(self.store, {"jsonrpc": "2.0", "id": 35, "method": "tools/call", "params": {"name": "list_task_relations", "arguments": {"project_id": "project", "task_id": "task_001", "direction": "upstream"}}})
        table = handle_request(self.store, {"jsonrpc": "2.0", "id": 36, "method": "tools/call", "params": {"name": "get_table", "arguments": {"table_name": "dim_customer", "project_id": "project"}}})

        self.assertIn("下游任务", downstream["result"]["content"][0]["text"])
        self.assertIn("task_002", downstream["result"]["content"][0]["text"])
        self.assertIn("上游任务", upstream["result"]["content"][0]["text"])
        self.assertIn("task_000", upstream["result"]["content"][0]["text"])
        self.assertIn("表元数据详情", table["result"]["content"][0]["text"])
        self.assertIn("dim_customer", table["result"]["content"][0]["text"])

    def test_new_tools_return_readable_validation_errors(self):
        with patch.dict(os.environ, {}, clear=True):
            project = handle_request(self.store, {"jsonrpc": "2.0", "id": 37, "method": "tools/call", "params": {"name": "get_project", "arguments": {}}})
        table = handle_request(self.store, {"jsonrpc": "2.0", "id": 38, "method": "tools/call", "params": {"name": "get_table", "arguments": {}}})

        self.assertIn("missing_project_id", project["result"]["content"][0]["text"])
        self.assertIn("missing_table_identity", table["result"]["content"][0]["text"])

    def test_live_wedata_syncs_new_api_families_with_default_project_id(self):
        client = FakeWeDataClient()
        with patch.dict(os.environ, {"WEDATA_PROJECT_ID": "project"}, clear=False):
            live = LiveWeData(self.store, client=client)
            live.sync_projects()
            live.sync_project()
            live.sync_project_members()
            live.sync_task_relations("task_001", "downstream")
            live.sync_task_relations("task_001", "upstream")
            live.sync_table_detail(table_guid="guid_dim_customer")

        actions = [action for action, payload in client.calls]
        self.assertIn("ListProjects", actions)
        self.assertIn("GetProject", actions)
        self.assertIn("ListProjectMembers", actions)
        self.assertIn("ListDownstreamTasks", actions)
        self.assertIn("ListUpstreamTasks", actions)
        self.assertIn("GetTable", actions)
        get_table_payload = [payload for action, payload in client.calls if action == "GetTable"][0]
        self.assertEqual(get_table_payload, {"TableGuid": "guid_dim_customer"})
        self.assertEqual(self.store.get_project("project")["name"], "prod")
        self.assertEqual(self.store.list_project_members("project")["members"][0]["member_id"], "u1")
        self.assertEqual(self.store.list_task_relations("project", "task_001", "downstream")["relations"][0]["related_task_id"], "task_down")

    def test_lists_tools(self):
        response = handle_request(self.store, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

        tools = [tool["name"] for tool in response["result"]["tools"]]
        self.assertIn("get_table_profile", tools)
        self.assertIn("get_table_partition_profile", tools)
        self.assertIn("search_tasks", tools)
        self.assertIn("list_data_sources", tools)
        self.assertIn("get_data_source_inventory", tools)
        self.assertIn("list_asset_gaps", tools)
        self.assertIn("list_metadata", tools)
        self.assertIn("get_sync_health", tools)
        self.assertIn("get_asset_coverage", tools)
        self.assertIn("get_asset_governance_daily_report", tools)
        self.assertIn("list_projects", tools)
        self.assertIn("get_project", tools)
        self.assertIn("list_project_members", tools)
        self.assertIn("list_task_relations", tools)
        for removed in (
            "get_table_risk_profile",
            "list_table_production_risks",
            "get_asset_value_profile",
            "get_asset_owner_profile",
            "get_asset_profile",
            "get_asset_change_impact",
            "get_expert_label",
        ):
            self.assertNotIn(removed, tools)
        self.assertIn("get_table", [tool["name"] for tool in response["result"]["tools"]])

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

    def test_calls_table_profile_tool_with_sections(self):
        response = handle_request(
            self.store,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "get_table_profile", "arguments": {"table_name": "dim_customer", "sections": ["columns"]}},
            },
        )

        text = response["result"]["content"][0]["text"]
        self.assertIn("字段信息", text)
        self.assertNotIn("标准表画像", text)
        self.assertNotIn("上下游血缘", text)

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
                "params": {"name": "get_table_partition_profile", "arguments": {"table_name": "ads_customer_revenue_daily", "partition_date": "2026-07-07", "source": "legacy_cache"}},
            },
        )

        text = response["result"]["content"][0]["text"]
        self.assertIn("表分区画像", text)
        self.assertIn("2026-07-07", text)
        self.assertIn("1283991", text)
        self.assertIn("最近分区", text)
        self.assertIn("正常", text)

    def test_table_partition_profile_shows_partition_metadata_without_facts(self):
        self.store.upsert_table({"name": "ods_cloud_cost_baidu_day_di", "database": "byai_bigdata"})
        self.store.upsert_column("ods_cloud_cost_baidu_day_di", "dt", "string", "", 1)

        response = handle_request(
            self.store,
            {
                "jsonrpc": "2.0",
                "id": 99,
                "method": "tools/call",
                "params": {"name": "get_table_partition_profile", "arguments": {"table_name": "ods_cloud_cost_baidu_day_di", "source": "legacy_cache"}},
            },
        )

        text = response["result"]["content"][0]["text"]
        self.assertIn("是否分区表：**True**", text)
        self.assertIn("分区字段：`dt`", text)
        self.assertIn("分区事实：`missing`", text)
        self.assertIn("表元数据/字段显示为分区表，但未同步到分区统计事实", text)

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
                "params": {"name": "list_asset_gaps", "arguments": {"view": "coverage", "gap_type": "quality", "layer": "dwd"}},
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
                "params": {"name": "get_asset_governance_daily_report", "arguments": {"instance_date": "2026-07-01", "layer": "dws", "source": "legacy_cache"}},
            },
        )

        text = response["result"]["content"][0]["text"]
        self.assertIn("资产巡检日报", text)
        self.assertIn("今日优先动作", text)
        self.assertIn("产出风险 Top 表", text)
        self.assertIn("资产画像缺口", text)
        self.assertIn("今日优先人工判断问题", text)
        self.assertIn("需要人工判断的资产覆盖问题", text)
        self.assertIn("层级待人工判断", text)
        self.assertIn("产出任务映射待确认", text)
        self.assertIn("运行实例窗口待确认", text)
        self.assertIn("Owner 责任待确认", text)
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
        self.assertIn("DLC SQL (32)", response["result"]["content"][0]["text"])

    def test_task_type_display_maps_codes_and_passes_through_unknown(self):
        self.assertEqual(_task_type_display("32"), "DLC SQL (32)")
        self.assertEqual(_task_type_display("31"), "PySpark (31)")
        self.assertEqual(_task_type_display("36"), "Spark SQL (36)")
        self.assertEqual(_task_type_display(26), "离线同步 (26)")
        self.assertEqual(_task_type_display(""), "")
        self.assertEqual(_task_type_display(None), "")
        self.assertEqual(_task_type_display("DataDevelopment"), "DataDevelopment")

    def test_code_fence_language_detects_pyspark_and_sql(self):
        self.assertEqual(_code_fence_language("select 1;"), "sql")
        self.assertEqual(_code_fence_language("from pyspark.sql import SparkSession"), "python")
        self.assertEqual(_code_fence_language("#!/bin/bash\necho $HOME"), "shell")
        self.assertEqual(_code_fence_language(""), "")

    def test_calls_get_task_runs_tool(self):
        response = handle_request(
            self.store,
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "get_task_runs", "arguments": {"task_id": "task_001", "source": "legacy_cache"}},
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
                    "arguments": {"task_name": "build_dim_customer", "instance_date": "2026-07-01", "source": "legacy_cache"},
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

    def test_calls_data_source_tasks_view(self):
        response = handle_request(
            self.store,
            {
                "jsonrpc": "2.0",
                "id": 11,
                "method": "tools/call",
                "params": {"name": "get_data_source_inventory", "arguments": {"data_source_id": "ds_001", "view": "tasks"}},
            },
        )

        text = response["result"]["content"][0]["text"]
        self.assertIn("sync_mysql_prod", text)
        self.assertIn("数据源关联任务", text)

    def test_calls_data_source_inventory_tool(self):
        response = handle_request(
            self.store,
            {
                "jsonrpc": "2.0",
                "id": 12,
                "method": "tools/call",
                "params": {"name": "get_data_source_inventory", "arguments": {"data_source_name": "mysql_prod"}},
            },
        )

        text = response["result"]["content"][0]["text"]
        self.assertIn("数据源资产清单：mysql_prod", text)
        self.assertIn("sync_mysql_prod", text)
        self.assertIn("未解析", text)
        self.assertIn("m2c_ods_crm_payment_plan_df", text)
        self.assertIn("CREATE TABLE `m2c_ods_crm_payment_plan_df`", text)

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

    def test_calls_quality_gaps_tool(self):
        response = handle_request(
            self.store,
            {
                "jsonrpc": "2.0",
                "id": 13,
                "method": "tools/call",
                "params": {"name": "list_asset_gaps", "arguments": {"view": "quality", "layer": "dwd"}},
            },
        )

        self.assertIn("dwd_sms_bill", response["result"]["content"][0]["text"])

    def test_calls_expert_review_queue_tool(self):
        response = handle_request(
            self.store,
            {
                "jsonrpc": "2.0",
                "id": 15,
                "method": "tools/call",
                "params": {"name": "list_asset_gaps", "arguments": {"view": "expert_review", "layer": "dwd"}},
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

    def test_live_data_source_inventory_fetches_related_task_definition(self):
        store = AssetStore(sqlite3.connect(":memory:"))
        store.init_schema()
        client = FakeWeDataClient()
        with patch.dict(os.environ, {"WEDATA_PROJECT_ID": "project"}):
            live = LiveWeData(store, client=client)
        response = handle_request(
            store,
            {
                "jsonrpc": "2.0",
                "id": 27,
                "method": "tools/call",
                "params": {"name": "get_data_source_inventory", "arguments": {"data_source_name": "crm_fxiaoke_tx", "live": True}},
            },
            live,
        )

        text = response["result"]["content"][0]["text"]
        self.assertIn("m2c_ods_cloud_cost_aliyun_day_di", text)
        self.assertIn("ods_cloud_cost_aliyun_day_di", text)
        self.assertNotIn("| m2c_ods_cloud_cost_aliyun_day_di | 缺字段 |", text)
        self.assertTrue(any(call[0] == "ListTasks" and call[1].get("TaskName") == "m2c_ods_cloud_cost_aliyun_day_di" for call in client.calls))
        self.assertTrue(any(call[0] == "ListProcessLineage" and call[1].get("ProcessId") == "20250808124139850" for call in client.calls))

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
                    "arguments": {"issue_type": "missing_quality_rules", "limit": 10, "source": "legacy_cache"},
                },
            },
        )

        text = response["result"]["content"][0]["text"]
        self.assertIn("missing_quality_rules", text)
        self.assertIn("ads_revenue", text)

    def test_get_asset_coverage_formats_warehouse_and_unknown_sections(self):
        store = AssetStore(sqlite3.connect(":memory:"))
        store.init_schema()
        store.upsert_table({"name": "ads_revenue", "layer": "ads", "data_source_id": "DLC"})
        store.upsert_table({"name": "mystery_table", "layer": "unknown"})

        response = handle_request(
            store,
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "get_asset_coverage", "arguments": {}}},
        )
        text = response["result"]["content"][0]["text"]

        self.assertIn("有效数仓覆盖", text)
        self.assertIn("unknown 资产池", text)
        self.assertIn("unknown 不计入主覆盖率", text)

    def test_coverage_gap_markdown_includes_producer_task_and_run_reason(self):
        store = AssetStore(sqlite3.connect(":memory:"))
        store.init_schema()
        store.upsert_table({"name": "ads_has_output_no_run", "layer": "ads", "data_source_id": "DLC"})
        store.upsert_task({"id": "producer_no_run", "name": "producer_no_run", "outputs": ["ads_has_output_no_run"]})

        response = handle_request(
            store,
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "list_asset_gaps", "arguments": {"view": "coverage", "gap_type": "runs", "layer": "ads", "limit": 10}}},
        )
        text = response["result"]["content"][0]["text"]

        self.assertIn("产出任务", text)
        self.assertIn("运行实例缺口原因", text)
        self.assertIn("有产出任务但缺运行实例", text)

    def test_coverage_gap_markdown_includes_producer_diagnosis(self):
        store = AssetStore(sqlite3.connect(":memory:"))
        store.init_schema()
        store.upsert_table({"name": "ads_has_only_input", "layer": "ads", "data_source_id": "DLC"})
        store.upsert_task({"id": "consumer", "name": "consumer", "inputs": ["ads_has_only_input"]})

        text = _call_tool(
            store,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "list_asset_gaps", "arguments": {"view": "coverage", "gap_type": "producer_tasks", "layer": "ads", "limit": 10}},
            },
        )["result"]["content"][0]["text"]

        assert "疑似原因" in text
        assert "下一步检查" in text
        assert "consumer_only_mapping" in text
        assert "SQL INSERT/CREATE" in text


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
