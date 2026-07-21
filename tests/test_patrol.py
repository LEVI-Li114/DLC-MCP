import sqlite3
import time

from dlc_mcp.asset_patrol import parse_args
from dlc_mcp.assets import AssetStore
from dlc_mcp.patrol import PatrolService


def test_asset_patrol_parse_args():
    args = parse_args(
        [
            "--scope", "daily_p0",
            "--instance-date", "2026-07-16",
            "--limit", "5",
            "--concurrency", "4",
            "--table-timeout-seconds", "90",
            "--retry", "3",
            "--retry-backoff-seconds", "1.5",
            "--api-delay-seconds", "0.1",
            "--failure-threshold", "0.25",
        ]
    )

    assert args.scope == "daily_p0"
    assert args.instance_date == "2026-07-16"
    assert args.limit == 5
    assert args.concurrency == 4
    assert args.table_timeout_seconds == 90
    assert args.retry == 3
    assert args.retry_backoff_seconds == 1.5
    assert args.api_delay_seconds == 0.1
    assert args.failure_threshold == 0.25


def test_asset_patrol_parse_args_new_scopes_and_filters():
    args = parse_args(
        [
            "--scope", "monthly_full",
            "--instance-date", "2026-07-16",
            "--limit", "100",
            "--batch-size", "25",
            "--offset", "50",
            "--table", "ads_360_fin_income_cost_1d_di",
            "--layer", "ads",
            "--owner", "tencent",
            "--core-level", "P1",
        ]
    )

    assert args.scope == "monthly_full"
    assert args.instance_date == "2026-07-16"
    assert args.limit == 100
    assert args.batch_size == 25
    assert args.offset == 50
    assert args.table == "ads_360_fin_income_cost_1d_di"
    assert args.layer == "ads"
    assert args.owner == "tencent"
    assert args.core_level == "P1"


def test_patrol_run_lifecycle_and_report_data():
    store = AssetStore(sqlite3.connect(":memory:"))
    store.init_schema()

    store.create_patrol_run("run-1", "2026-07-16", "daily_p0", {"limit": 10})
    store.upsert_patrol_asset_snapshot(
        {
            "run_id": "run-1",
            "asset_name": "ods_cloud_cost_baidu_day_di",
            "asset_type": "table",
            "layer": "ods",
            "owner": "prod-bigdata",
            "core_level": "非核心",
            "status": "risk",
            "snapshot": {"latest_partition": "dt=20260715"},
        }
    )
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
    store.insert_patrol_metric(
        {
            "run_id": "run-1",
            "metric_name": "checked_count",
            "metric_value": 1,
            "dimension": {"scope": "daily_p0"},
        }
    )
    store.insert_patrol_error(
        {
            "run_id": "run-1",
            "asset_name": "ods_cloud_cost_baidu_day_di",
            "module": "lineage",
            "api_action": "ListLineage",
            "error_code": "InternalError",
            "error_message": "temporary unavailable",
            "retryable": True,
        }
    )
    store.finish_patrol_run("run-1", "partial", {"checked_count": 1, "error_count": 1})

    latest = store.latest_patrol_run("2026-07-16", "daily_p0")
    report = store.get_patrol_report_data("run-1")

    assert latest["run_id"] == "run-1"
    assert latest["status"] == "partial"
    assert report["run"]["run_id"] == "run-1"
    assert report["snapshots"][0]["asset_name"] == "ods_cloud_cost_baidu_day_di"
    assert report["findings"][0]["issue_type"] == "missing_quality_rules"
    assert report["metrics"][0]["metric_name"] == "checked_count"
    assert report["errors"][0]["module"] == "lineage"


class PatrolLive:
    def __init__(self, store):
        self.store = store

    def sync_table_partitions(self, table_name):
        self.store.upsert_table_partition(
            {
                "table_name": table_name,
                "partition_name": "dt=20260715",
                "partition_date": "20260715",
                "row_count": 2,
            }
        )


def test_patrol_service_daily_p0_writes_run_snapshot_and_metric():
    store = AssetStore(sqlite3.connect(":memory:"))
    store.init_schema()
    store.upsert_table({"name": "ods_cloud_cost_baidu_day_di", "layer": "ods", "owner": "prod-bigdata", "database": "byai_bigdata"})
    store.upsert_column("ods_cloud_cost_baidu_day_di", "dt", "string", "", 1)

    result = PatrolService(store, PatrolLive(store)).run_daily_p0("2026-07-16", limit=1)
    report = store.get_patrol_report_data(result["run_id"])

    assert result["status"] == "completed"
    assert report["run"]["scope"] == "daily_p0"
    assert report["snapshots"][0]["asset_name"] == "ods_cloud_cost_baidu_day_di"
    assert report["metrics"][0]["metric_name"] == "checked_count"


def test_patrol_service_summary_includes_execution_controls():
    store = AssetStore(sqlite3.connect(":memory:"))
    store.init_schema()
    store.upsert_table({"name": "ods_cloud_cost_baidu_day_di", "layer": "ods", "owner": "prod-bigdata", "database": "byai_bigdata"})
    store.upsert_column("ods_cloud_cost_baidu_day_di", "dt", "string", "", 1)

    result = PatrolService(store, PatrolLive(store)).run_daily_p0(
        "2026-07-16",
        limit=1,
        concurrency=2,
        table_timeout_seconds=90,
        retry=1,
        retry_backoff_seconds=0,
        api_delay_seconds=0,
        failure_threshold=0.4,
    )

    assert result["timeout_count"] == 0
    assert result["duration_seconds"] >= 0
    assert result["concurrency"] == 2
    assert result["table_timeout_seconds"] == 90
    assert result["retry"] == 1
    assert result["api_delay_seconds"] == 0


def test_daily_core_candidates_exclude_temporary_backup_and_copy_tables():
    store = AssetStore(sqlite3.connect(":memory:"))
    store.init_schema()
    for name in [
        "ads_360_fin_total_1d_df",
        "ads_360_fin_total_1d_df_tmp",
        "ads_360_fin_total_1d_df_bak20250720",
        "ads_360_fin_total_1d_df_copy",
        "ads_xtmp_metric_df",
        "tmp_ads_360_fin_total_1d_df",
        "tmpx_ads_metric_df",
    ]:
        store.upsert_table({"name": name, "layer": "ads", "owner": "tencent", "database": "dw"})

    candidates = PatrolService(store, PatrolLive(store))._daily_core_candidates(10)

    assert [item["name"] for item in candidates] == [
        "ads_360_fin_total_1d_df",
        "ads_xtmp_metric_df",
        "tmpx_ads_metric_df",
    ]


class FailingPatrolLive:
    def sync_table_partitions(self, table_name):
        raise RuntimeError("DescribeTablePartitions failed: InternalError temporary unavailable")


def test_patrol_service_records_table_failure_and_continues():
    store = AssetStore(sqlite3.connect(":memory:"))
    store.init_schema()
    store.upsert_table({"name": "ads_ok", "layer": "ads", "owner": "data", "database": "dw"})
    store.upsert_table({"name": "ads_fail", "layer": "ads", "owner": "data", "database": "dw"})

    class MixedLive:
        def __init__(self, store):
            self.store = store
        def sync_table_partitions(self, table_name):
            if table_name == "ads_fail":
                raise RuntimeError("DescribeTablePartitions failed: InternalError temporary unavailable")
            self.store.upsert_table_partition({"table_name": table_name, "partition_name": "dt=20260715", "partition_date": "20260715", "row_count": 1})

    result = PatrolService(store, MixedLive(store)).run_daily_p0(
        "2026-07-16",
        limit=2,
        concurrency=2,
        retry=0,
        api_delay_seconds=0,
        failure_threshold=0.75,
    )
    report = store.get_patrol_report_data(result["run_id"])

    assert result["status"] == "partial"
    assert result["checked_count"] == 2
    assert result["error_count"] == 1
    assert len(report["snapshots"]) == 2
    assert report["errors"][0]["asset_name"] == "ads_fail"
    assert report["errors"][0]["module"] == "partition"


def test_patrol_service_marks_failed_above_failure_threshold():
    store = AssetStore(sqlite3.connect(":memory:"))
    store.init_schema()
    store.upsert_table({"name": "ads_fail", "layer": "ads", "owner": "data", "database": "dw"})

    result = PatrolService(store, FailingPatrolLive()).run_daily_p0(
        "2026-07-16",
        limit=1,
        concurrency=1,
        retry=0,
        api_delay_seconds=0,
        failure_threshold=0.3,
    )

    assert result["status"] == "failed"
    assert result["checked_count"] == 1
    assert result["error_count"] == 1


class SlowPatrolLive:
    def sync_table_partitions(self, table_name):
        time.sleep(0.2)


def test_patrol_service_records_timeout_as_check_failed():
    store = AssetStore(sqlite3.connect(":memory:"))
    store.init_schema()
    store.upsert_table({"name": "ads_slow", "layer": "ads", "owner": "data", "database": "dw"})

    result = PatrolService(store, SlowPatrolLive()).run_daily_p0(
        "2026-07-16",
        limit=1,
        concurrency=1,
        table_timeout_seconds=0.01,
        retry=0,
        api_delay_seconds=0,
        failure_threshold=1.0,
    )
    report = store.get_patrol_report_data(result["run_id"])

    assert result["status"] == "partial"
    assert result["timeout_count"] == 1
    assert report["snapshots"][0]["status"] == "check_failed"
    assert report["errors"][0]["error_code"] == "Timeout"
    assert report["errors"][0]["module"] == "table_check"


def test_patrol_scope_candidates_monthly_full_uses_all_tables_with_filters():
    store = AssetStore(sqlite3.connect(":memory:"))
    store.init_schema()
    store.upsert_table({"name": "ods_a", "layer": "ods", "owner": "data", "database": "dw"})
    store.upsert_table({"name": "ads_b", "layer": "ads", "owner": "tencent", "database": "dw"})
    store.upsert_table({"name": "ads_c", "layer": "ads", "owner": "other", "database": "dw"})

    service = PatrolService(store, PatrolLive(store))
    candidates = service._scope_candidates("monthly_full", limit=10, layer="ads", owner="tencent")

    assert [item["name"] for item in candidates] == ["ads_b"]


def test_patrol_scope_candidates_manual_accepts_single_table():
    store = AssetStore(sqlite3.connect(":memory:"))
    store.init_schema()
    store.upsert_table({"name": "ads_360_fin_income_cost_1d_di", "layer": "ads", "owner": "tencent", "database": "dw"})
    store.upsert_table({"name": "ads_other", "layer": "ads", "owner": "tencent", "database": "dw"})

    service = PatrolService(store, PatrolLive(store))
    candidates = service._scope_candidates("manual", limit=10, table="ads_360_fin_income_cost_1d_di")

    assert [item["name"] for item in candidates] == ["ads_360_fin_income_cost_1d_di"]


class PatrolEvidenceLive:
    def __init__(self, tasks=None, quality=None, production=None, fail_quality=False):
        self.tasks = tasks if tasks is not None else {"tasks": []}
        self.quality = quality if quality is not None else {"has_monitoring": False, "rule_count": 0, "latest_status": "missing"}
        self.production = production if production is not None else {"summary_status": "not_run", "producer_task_count": 0, "runs": []}
        self.fail_quality = fail_quality

    def get_table_tasks_live(self, table_name):
        return self.tasks

    def get_quality_status_live(self, table_name):
        if self.fail_quality:
            raise RuntimeError("ListQualityRules failed: InternalError temporary unavailable")
        return self.quality

    def get_table_production_status_live(self, table_name, instance_date):
        return self.production


def test_patrol_collects_cached_and_live_only_evidence_without_registry_writes():
    store = AssetStore(sqlite3.connect(":memory:"))
    store.init_schema()
    store.upsert_table({
        "name": "ads_360_fin_income_cost_1d_di",
        "layer": "ads",
        "domain": "finance",
        "owner": "tencent",
        "database": "byai_bigdata",
        "data_source_id": "DLC",
        "description": "消耗型产品确认收入和成本汇总表",
    })
    store.upsert_column("ads_360_fin_income_cost_1d_di", "dt", "string", "分区", 1)
    store.upsert_lineage("dws_360_fin_job_line_1d_di", "ads_360_fin_income_cost_1d_di", "task_lineage")
    store.upsert_lineage("ads_360_fin_income_cost_1d_di", "ads_360_fin_income_cost_1d_df", "task_lineage")

    live = PatrolEvidenceLive()
    service = PatrolService(store, live)
    evidence = service._collect_table_evidence(
        {"name": "ads_360_fin_income_cost_1d_di", "layer": "ads", "owner": "tencent", "database_name": "byai_bigdata"},
        "2026-07-16",
    )

    assert evidence["source_policy"] == {
        "metadata": "cache",
        "columns": "cache",
        "lineage": "cache",
        "tasks": "live_only",
        "quality": "live_only",
        "runs": "live_only",
    }
    assert evidence["cached"]["metadata"]["status"] == "complete"
    assert evidence["cached"]["columns"]["count"] == 1
    assert evidence["cached"]["lineage"]["upstream_count"] == 1
    assert evidence["cached"]["lineage"]["downstream_count"] == 1
    assert evidence["live"]["tasks"]["status"] == "missing"
    assert evidence["live"]["quality"]["status"] == "missing"
    assert evidence["live"]["runs"]["status"] == "missing"
    assert evidence["errors"] == []
    assert store.get_table_tasks("ads_360_fin_income_cost_1d_di")["tasks"] == []


def test_patrol_normalizes_missing_live_evidence_into_findings():
    store = AssetStore(sqlite3.connect(":memory:"))
    store.init_schema()
    table = {"name": "ads_360_fin_income_cost_1d_di", "layer": "ads", "owner": "tencent", "database_name": "dw"}
    evidence = {
        "source_policy": {"metadata": "cache", "columns": "cache", "lineage": "cache", "tasks": "live_only", "quality": "live_only", "runs": "live_only"},
        "cached": {
            "metadata": {"status": "complete", "core_level": "P2"},
            "columns": {"status": "complete", "count": 36},
            "lineage": {"status": "complete", "upstream_count": 26, "downstream_count": 13},
        },
        "live": {
            "tasks": {"status": "missing", "producer_count": 0, "consumer_count": 0},
            "quality": {"status": "missing", "rule_count": 0},
            "runs": {"status": "missing", "run_count": 0, "summary_status": "not_run"},
        },
        "errors": [],
    }

    result = PatrolService(store, PatrolLive(store))._normalize_table_result(table, evidence)

    assert result["status"] == "p1"
    assert result["snapshot"]["source_policy"]["tasks"] == "live_only"
    assert [finding["issue_type"] for finding in result["findings"]] == [
        "missing_producer_task",
        "missing_quality_rules",
        "missing_task_runs",
    ]
    assert all(finding["severity"] == "P1" for finding in result["findings"])
    producer_finding = next(finding for finding in result["findings"] if finding["issue_type"] == "missing_producer_task")
    diagnosis = producer_finding["evidence"]["producer_diagnosis"]
    assert diagnosis["root_cause"] == "lineage_without_task_mapping"
    assert diagnosis["evidence_source"] == "patrol_live_context"
    assert diagnosis["evidence"]["live_checked"] is True
    assert diagnosis["evidence"]["live_producer_task_count"] == 0


def test_patrol_producer_diagnosis_records_live_task_error():
    store = AssetStore(sqlite3.connect(":memory:"))
    store.init_schema()
    table = {"name": "ads_need_live", "layer": "ads", "owner": "tencent", "database_name": "dw"}
    evidence = {
        "source_policy": {"metadata": "cache", "columns": "cache", "lineage": "cache", "tasks": "live_only", "quality": "live_only", "runs": "live_only"},
        "cached": {
            "metadata": {"status": "complete", "core_level": "P2"},
            "columns": {"status": "complete", "count": 10},
            "lineage": {"status": "complete", "upstream_count": 1, "downstream_count": 0},
        },
        "live": {
            "tasks": {"status": "live_failed", "producer_count": 0, "consumer_count": 0, "raw": {"error": "live_failed", "message": "ListTasks failed: InternalError temporary unavailable"}},
            "quality": {"status": "missing", "rule_count": 0},
            "runs": {"status": "missing", "run_count": 0, "summary_status": "not_run"},
        },
        "errors": [],
    }

    result = PatrolService(store, PatrolLive(store))._normalize_table_result(table, evidence)

    producer_finding = next(finding for finding in result["findings"] if finding["issue_type"] == "missing_producer_task")
    diagnosis = producer_finding["evidence"]["producer_diagnosis"]
    assert diagnosis["root_cause"] == "live_evidence_unavailable"
    assert diagnosis["evidence_source"] == "patrol_live_context"
    assert diagnosis["evidence"]["live_checked"] is False
    assert "InternalError" in diagnosis["evidence"]["live_error"]


def test_patrol_summary_counts_live_and_severity_buckets():
    store = AssetStore(sqlite3.connect(":memory:"))
    store.init_schema()
    store.upsert_table({"name": "ads_missing", "layer": "ads", "owner": "tencent", "database": "dw"})
    store.upsert_column("ads_missing", "dt", "string", "", 1)

    result = PatrolService(store, PatrolEvidenceLive()).run(
        "daily_core",
        "2026-07-16",
        limit=1,
        concurrency=1,
        retry=0,
        api_delay_seconds=0,
    )

    assert result["live_success_count"] == 0
    assert result["live_partial_count"] == 1
    assert result["live_failed_count"] == 0
    assert result["p0_count"] == 0
    assert result["p1_count"] == 1
    assert result["p2_count"] == 0


def test_patrol_snapshot_includes_resolved_owner_from_producer_task():
    store = AssetStore(sqlite3.connect(":memory:"))
    store.init_schema()
    store.upsert_table({"name": "ads_system_owned", "layer": "ads", "owner": "tencent", "database": "dw"})
    store.upsert_column("ads_system_owned", "dt", "string", "", 1)
    store.upsert_task({"id": "task_owner", "name": "ads_system_owned", "owner": "100043939904", "outputs": ["ads_system_owned"]})

    result = PatrolService(store, PatrolEvidenceLive()).run(
        "manual",
        "2026-07-16",
        table="ads_system_owned",
        limit=1,
        concurrency=1,
        retry=0,
        api_delay_seconds=0,
    )
    report = store.get_patrol_report_data(result["run_id"])
    snapshot = report["snapshots"][0]["snapshot_json"]

    assert "luyuan" in snapshot
    assert "producer_task_owner" in snapshot
