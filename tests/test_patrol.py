import sqlite3

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
