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
