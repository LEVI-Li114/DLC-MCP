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
            "cycle": "DAY",
            "schedule_time": "08:00",
            "schedule_desc": "每天 08:00 调度",
            "owner": "data-finance",
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
        self.assertIn("machine", value)
        self.assertIn("manual", value)
        self.assertIn("final", value)
        self.assertEqual(value["machine"]["task_dependency"], {"producer_task_count": 1, "consumer_task_count": 0, "total_task_count": 1})
        self.assertIn("缺最近运行实例", value["gaps"])

    def test_manual_label_overrides_machine_decision_with_confidence(self):
        store = make_store()
        store.upsert_expert_label(
            {
                "asset_name": "ads_customer_revenue_daily",
                "core_level": "P1",
                "value_tier": "核心",
                "reviewer": "data-team",
                "reason": "财务看板核心依赖",
            }
        )

        value = store.get_asset_value_profile("ads_customer_revenue_daily")

        self.assertEqual(value["source"], "manual_override")
        self.assertEqual(value["core_level"], "P1")
        self.assertTrue(value["is_core"])
        self.assertEqual(value["manual"]["reviewer"], "data-team")
        self.assertIn(value["confidence"], {"medium", "high"})
        self.assertIn("缺", value["review_suggestion"])

    def test_asset_owner_profile_collects_responsibility_chain(self):
        owner = make_store().get_asset_owner_profile("ads_customer_revenue_daily")

        self.assertEqual(owner["table_owner"], "data-finance")
        self.assertEqual(owner["data_source_owner"], "100043939904")
        self.assertEqual(owner["producer_task_owners"], ["data-finance"])
        self.assertIn("data-finance", owner["owner_candidates"])
        self.assertTrue(owner["suggestions"])

    def test_asset_usage_profile_uses_metadata_proxy_signals(self):
        usage = make_store().get_asset_usage_profile("ads_customer_revenue_daily")

        self.assertEqual(usage["usage_source"], "metadata_proxy")
        self.assertEqual(usage["downstream_count"], 1)
        self.assertEqual(usage["producer_task_count"], 1)
        self.assertEqual(usage["quality_rule_count"], 1)
        self.assertIn("缺真实查询日志", usage["gaps"])
        self.assertTrue(usage["signals"])

    def test_asset_lifecycle_profile_reports_state_from_available_evidence(self):
        store = make_store()
        store.upsert_task_run(
            {
                "task_id": "task_001",
                "instance_id": "inst_lifecycle",
                "instance_date": "2026-07-08",
                "start_time": "2026-07-08 08:00:00",
                "end_time": "2026-07-08 08:05:00",
                "duration_seconds": 300,
                "status": "success",
            }
        )

        lifecycle = store.get_asset_lifecycle_profile("ads_customer_revenue_daily")

        self.assertIn(lifecycle["lifecycle_status"], {"活跃", "稳定", "待治理"})
        self.assertEqual(lifecycle["latest_run_time"], "2026-07-08 08:05:00")
        self.assertEqual(lifecycle["producer_task_count"], 1)
        self.assertTrue(lifecycle["evidence"])
        self.assertTrue(lifecycle["suggestions"])

    def test_asset_change_impact_lists_downstream_and_tasks(self):
        impact = make_store().get_asset_change_impact("ads_customer_revenue_daily", "schema_change")

        self.assertEqual(impact["change_type"], "schema_change")
        self.assertEqual(impact["direct_downstream"][0]["downstream"], "bi_finance_dashboard")
        self.assertTrue(impact["affected_tasks"])
        self.assertIn(impact["risk_level"], {"低", "中", "高"})
        self.assertTrue(impact["checks"])
        self.assertTrue(impact["suggestions"])

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

    def test_sync_health_and_asset_coverage(self):
        store = make_store()
        store.upsert_task_run(
            {
                "task_id": "task_001",
                "instance_id": "inst_001",
                "instance_date": "2026-07-07",
                "start_time": "2026-07-07 08:00:00",
                "end_time": "2026-07-07 08:05:00",
                "duration_seconds": 300,
                "status": "success",
            }
        )

        health = store.get_sync_health()
        coverage = store.get_asset_coverage()

        self.assertEqual(health["counts"]["tables"], 2)
        self.assertEqual(health["counts"]["tasks"], 1)
        self.assertEqual(health["latest_signals"]["latest_task_run_start"], "2026-07-07 08:00:00")
        self.assertNotIn("未同步任务运行实例", health["gaps"])
        self.assertEqual(coverage["layers"][0]["layer"], "ads")
        self.assertEqual(coverage["layers"][0]["tables_with_quality_rules"], 1)
        self.assertEqual(coverage["layers"][1]["layer"], "dws")

    def test_asset_coverage_gaps_filter_by_type_and_layer(self):
        gaps = make_store().list_asset_coverage_gaps(gap_type="quality", layer="dws", limit=10)

        self.assertEqual(gaps["results"][0]["name"], "dws_customer_revenue_1d_di")
        self.assertIn("quality", gaps["results"][0]["gap_keys"])
        self.assertIn("缺质量规则", gaps["results"][0]["gaps"])
        self.assertEqual(gaps["supported_gap_types"][0], "fields")

    def test_asset_governance_daily_report_aggregates_patrol_sections(self):
        report = make_store().get_asset_governance_daily_report("2026-07-08", layer="ads")

        self.assertEqual(report["instance_date"], "2026-07-08")
        self.assertEqual(report["layer"], "ads")
        self.assertIn("summary", report)
        self.assertIn("production_risk_count", report["summary"])
        self.assertIn("coverage_gaps", report)
        self.assertIn("quality_gaps", report)
        self.assertIn("owner_gaps", report)
        self.assertIn("lifecycle_watch", report)
        self.assertTrue(report["top_actions"])
        self.assertLessEqual(len(report["production_risks"]), 20)

    def test_asset_governance_daily_report_filters_core_level(self):
        store = make_store()
        store.upsert_expert_label(
            {
                "asset_name": "ads_customer_revenue_daily",
                "core_level": "P1",
                "value_tier": "核心",
                "owner": "data-finance",
                "reviewer": "data-team",
                "reason": "核心看板",
            }
        )

        report = store.get_asset_governance_daily_report("2026-07-08", layer="ads", core_level="P1")

        self.assertEqual(report["core_level"], "P1")
        self.assertTrue(all(item.get("name") == "ads_customer_revenue_daily" for item in report["owner_gaps"] + report["lifecycle_watch"]))

    def test_table_partition_profile_reports_volume_and_health(self):
        store = make_store()
        for day, rows in [("2026-07-07", 1200), ("2026-07-06", 1100), ("2026-07-05", 1000)]:
            store.upsert_table_partition(
                {
                    "table_name": "ads_customer_revenue_daily",
                    "partition_name": f"dt={day}",
                    "partition_date": day,
                    "row_count": rows,
                    "storage_bytes": rows * 10,
                    "file_count": 2,
                    "updated_at": f"{day} 08:00:00",
                    "collected_at": "2026-07-08 09:00:00",
                }
            )

        profile = store.get_table_partition_profile("ads_customer_revenue_daily", "2026-07-07")

        self.assertTrue(profile["is_partitioned"])
        self.assertEqual(profile["partition_count"], 3)
        self.assertEqual(profile["target_partition"]["row_count"], 1200)
        self.assertEqual(profile["total_rows"], 3300)
        self.assertEqual(profile["health_status"], "normal")
        self.assertEqual([row["partition_date"] for row in profile["recent_partitions"]], ["2026-07-07", "2026-07-06", "2026-07-05"])

    def test_table_partition_profile_flags_missing_and_empty_partitions(self):
        store = make_store()
        store.upsert_table_partition({"table_name": "ads_customer_revenue_daily", "partition_name": "dt=2026-07-06", "partition_date": "2026-07-06", "row_count": 1000})
        store.upsert_table_partition({"table_name": "ads_customer_revenue_daily", "partition_name": "dt=2026-07-07", "partition_date": "2026-07-07", "row_count": 0})

        missing = store.get_table_partition_profile("ads_customer_revenue_daily", "2026-07-05")
        empty = store.get_table_partition_profile("ads_customer_revenue_daily", "2026-07-07")

        self.assertEqual(missing["health_status"], "missing_partition")
        self.assertEqual(empty["health_status"], "empty_partition")
        self.assertIn("空分区", empty["health_label"])

    def test_table_readiness_reports_profile_completeness_and_actions(self):
        readiness = make_store().get_table_readiness("ads_customer_revenue_daily")

        self.assertEqual(readiness["table_name"], "ads_customer_revenue_daily")
        self.assertIn(readiness["status"], {"部分通过", "通过"})
        self.assertGreater(readiness["score"], 0)
        self.assertEqual(readiness["summary"]["layer"], "ads")
        self.assertIn("缺最近运行实例", readiness["gaps"])
        self.assertTrue(any("WEDATA_INSTANCE" in action for action in readiness["next_actions"]))
        self.assertEqual(readiness["related_tasks"][0]["task_name"], "ads_customer_revenue_daily")
        self.assertEqual(readiness["related_tasks"][0]["owner"], "data-finance")
        self.assertEqual(readiness["related_tasks"][0]["cycle"], "DAY")
        self.assertEqual(readiness["related_tasks"][0]["schedule_time"], "08:00")
        self.assertEqual(readiness["related_tasks"][0]["schedule_desc"], "每天 08:00 调度")
        self.assertEqual(readiness["task_runs"][0]["execution_status"], "未执行")
        self.assertEqual([check["name"] for check in readiness["checks"]][:3], ["基础信息", "字段", "血缘"])

    def test_table_production_status_summarizes_output_task_runs(self):
        store = make_store()
        store.upsert_task_run(
            {
                "task_id": "task_001",
                "instance_id": "inst_001",
                "instance_date": "2026-07-08",
                "start_time": "2026-07-08 08:00:00",
                "end_time": "2026-07-08 08:05:00",
                "duration_seconds": 300,
                "status": "COMPLETED",
            }
        )

        status = store.get_table_production_status("ads_customer_revenue_daily", "2026-07-08")

        self.assertEqual(status["status"], "success")
        self.assertEqual(status["status_label"], "成功")
        self.assertEqual(status["producer_task_count"], 1)
        self.assertEqual(status["tasks"][0]["owner"], "data-finance")
        self.assertEqual(status["tasks"][0]["schedule_time"], "08:00")
        self.assertEqual(status["tasks"][0]["latest_run"]["raw_status"], "COMPLETED")
        self.assertEqual(status["tasks"][0]["latest_run"]["duration_seconds"], 300)

    def test_table_production_status_handles_missing_task_or_run(self):
        store = make_store()
        no_run = store.get_table_production_status("ads_customer_revenue_daily", "2026-07-08")
        no_task = store.get_table_production_status("dws_customer_revenue_1d_di", "2026-07-08")

        self.assertEqual(no_run["status"], "not_run")
        self.assertIn("没有匹配的运行实例", "；".join(no_run["reasons"]))
        self.assertEqual(no_task["status"], "not_run")
        self.assertIn("未找到产出任务", no_task["reasons"])

    def test_table_production_risks_lists_non_success_tables(self):
        store = make_store()
        store.upsert_task_run(
            {
                "task_id": "task_001",
                "instance_id": "inst_success",
                "instance_date": "2026-07-08",
                "start_time": "2026-07-08 08:00:00",
                "end_time": "2026-07-08 08:05:00",
                "duration_seconds": 300,
                "status": "COMPLETED",
            }
        )
        store.upsert_task({"id": "task_dws", "name": "dws_customer_revenue_1d_di", "owner": "data-finance", "outputs": ["dws_customer_revenue_1d_di"]})

        risks = store.list_table_production_risks(layer="dws", instance_date="2026-07-08", limit=10)

        self.assertEqual([item["name"] for item in risks["results"]], ["dws_customer_revenue_1d_di"])
        self.assertEqual(risks["results"][0]["status"], "not_run")
        self.assertEqual(risks["results"][0]["status_label"], "未执行")
        self.assertIn("core_level", risks["results"][0])
        self.assertIn("value_tier", risks["results"][0])
        self.assertNotIn("ads_customer_revenue_daily", [item["name"] for item in risks["results"]])

        filtered = store.list_table_production_risks(layer="dws", status="not_run", instance_date="2026-07-08", limit=10)
        self.assertEqual(filtered["results"][0]["name"], "dws_customer_revenue_1d_di")

    def test_table_production_risk_detail_explains_missing_run(self):
        store = make_store()
        store.upsert_task({"id": "task_dws", "name": "dws_customer_revenue_1d_di", "owner": "data-finance", "outputs": ["dws_customer_revenue_1d_di"]})

        detail = store.get_table_production_risk_detail("dws_customer_revenue_1d_di", "2026-07-08")

        self.assertEqual(detail["status"], "not_run")
        self.assertEqual(detail["status_label"], "未执行")
        self.assertEqual(detail["table"]["layer"], "dws")
        self.assertIn("core_level", detail["core"])
        self.assertEqual(detail["impact"]["downstream_count"], 1)
        self.assertIn("没有匹配的运行实例", "；".join(detail["reasons"]))
        self.assertTrue(detail["diagnosis"])
        self.assertTrue(detail["suggestions"])

    def test_table_production_risk_detail_explains_failed_run(self):
        store = make_store()
        store.upsert_task({"id": "task_dws", "name": "dws_customer_revenue_1d_di", "owner": "data-finance", "outputs": ["dws_customer_revenue_1d_di"]})
        store.upsert_task_run(
            {
                "task_id": "task_dws",
                "instance_id": "inst_failed",
                "instance_date": "2026-07-08",
                "start_time": "2026-07-08 07:00:00",
                "end_time": "2026-07-08 07:03:00",
                "duration_seconds": 180,
                "status": "FAILED",
            }
        )

        detail = store.get_table_production_risk_detail("dws_customer_revenue_1d_di", "2026-07-08")

        self.assertEqual(detail["status"], "failed")
        self.assertIn("存在失败实例", "；".join(detail["diagnosis"]))
        self.assertIn("优先联系产出任务负责人", "；".join(detail["suggestions"]))


class AssetGovernanceIssueInventoryTest(unittest.TestCase):
    def _store(self):
        store = AssetStore(sqlite3.connect(":memory:"))
        store.init_schema()
        return store

    def test_lists_unknown_layer_issue_with_evidence(self):
        store = self._store()
        store.upsert_table({"name": "mystery_daily", "layer": "unknown", "owner": "data-owner"})

        data = store.get_asset_governance_issue_inventory(issue_type="unknown_layer")

        self.assertEqual(data["issue_type"], "unknown_layer")
        self.assertEqual(data["supported_issue_types"][0], "unknown_layer")
        self.assertEqual(len(data["results"]), 1)
        issue = data["results"][0]
        self.assertEqual(issue["issue_type"], "unknown_layer")
        self.assertEqual(issue["asset_type"], "table")
        self.assertEqual(issue["asset_name"], "mystery_daily")
        self.assertEqual(issue["layer"], "unknown")
        self.assertEqual(issue["owner"], "data-owner")
        self.assertEqual(issue["suspected_root_cause"], "manual_mapping_needed")
        self.assertIn("layer", issue["evidence"])

    def test_lists_missing_quality_rule_issue_with_downstream_evidence(self):
        store = self._store()
        store.upsert_table({"name": "ads_revenue", "layer": "ads", "owner": "finance"})
        store.upsert_column("ads_revenue", "amount", "decimal", "", 1)
        store.upsert_lineage("ads_revenue", "report_revenue", "dashboard")

        data = store.get_asset_governance_issue_inventory(issue_type="missing_quality_rules")

        issue = data["results"][0]
        self.assertEqual(issue["issue_type"], "missing_quality_rules")
        self.assertEqual(issue["severity"], "P1")
        self.assertEqual(issue["evidence"]["quality_rule_count"], 0)
        self.assertEqual(issue["evidence"]["downstream_count"], 1)
        self.assertEqual(issue["suspected_root_cause"], "source_governance_gap")

    def test_separates_missing_task_mapping_and_missing_task_runs(self):
        store = self._store()
        store.upsert_table({"name": "ads_no_task", "layer": "ads"})
        store.upsert_table({"name": "ads_no_run", "layer": "ads"})
        store.upsert_task({"id": "task_1", "name": "build_ads_no_run", "outputs": ["ads_no_run"]})

        no_task = store.get_asset_governance_issue_inventory(issue_type="missing_task_mapping")
        no_run = store.get_asset_governance_issue_inventory(issue_type="missing_task_runs")

        self.assertEqual([item["asset_name"] for item in no_task["results"]], ["ads_no_task"])
        self.assertEqual([item["asset_name"] for item in no_run["results"]], ["ads_no_run"])
        self.assertEqual(no_run["results"][0]["suspected_root_cause"], "instance_window_gap")

    def test_filters_by_layer_and_limit(self):
        store = self._store()
        store.upsert_table({"name": "ads_a", "layer": "ads"})
        store.upsert_table({"name": "dwd_b", "layer": "dwd"})

        data = store.get_asset_governance_issue_inventory(layer="ads", issue_type="missing_quality_rules", limit=1)

        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["asset_name"], "ads_a")

    def test_invalid_issue_type_returns_supported_types_and_no_results(self):
        store = self._store()
        store.upsert_table({"name": "ads_a", "layer": "ads"})

        data = store.get_asset_governance_issue_inventory(issue_type="not_real")

        self.assertEqual(data["issue_type"], "not_real")
        self.assertEqual(data["results"], [])
        self.assertIn("missing_quality_rules", data["supported_issue_types"])

    def test_issue_type_filter_applies_before_limit(self):
        store = self._store()
        store.upsert_table({"name": "a_no_task", "layer": "ads"})
        store.upsert_table({"name": "z_no_run", "layer": "ads"})
        store.upsert_task({"id": "task_1", "name": "build_z_no_run", "outputs": ["z_no_run"]})

        data = store.get_asset_governance_issue_inventory(issue_type="missing_task_runs", limit=1)

        self.assertEqual([item["asset_name"] for item in data["results"]], ["z_no_run"])

    def test_daily_report_includes_governance_issue_summaries(self):
        store = self._store()
        store.upsert_table({"name": "ads_revenue", "layer": "ads", "owner": "finance"})
        store.upsert_table({"name": "unknown_table", "layer": "unknown", "owner": ""})

        report = store.get_asset_governance_daily_report()

        self.assertIn("issue_summary_by_type", report)
        self.assertGreaterEqual(report["issue_summary_by_type"]["missing_quality_rules"], 1)
        self.assertGreaterEqual(report["issue_summary_by_type"]["unknown_layer"], 1)
        self.assertIn("issue_summary_by_severity", report)
        self.assertIn("issue_summary_by_owner", report)
        self.assertIn("unknown owner", report["issue_summary_by_owner"])
        self.assertIn("top_governance_issues", report)
        self.assertIn("responsibility_buckets", report)


if __name__ == "__main__":
    unittest.main()
