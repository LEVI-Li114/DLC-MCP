import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import datetime

from .live_assets import LiveAssetService
from .source import Source


class PatrolService:
    def __init__(self, store, live):
        self.store = store
        self.live = live

    def run(self, scope, instance_date, **options):
        if scope in {"daily_p0", "daily_core"}:
            return self.run_daily_p0(
                instance_date,
                limit=options.get("limit", 50),
                concurrency=options.get("concurrency", 3),
                table_timeout_seconds=options.get("table_timeout_seconds", 120),
                retry=options.get("retry", 2),
                retry_backoff_seconds=options.get("retry_backoff_seconds", 2),
                api_delay_seconds=options.get("api_delay_seconds", 0.2),
                failure_threshold=options.get("failure_threshold", 0.3),
            )
        raise SystemExit(f"unsupported scope: {scope}")

    def run_daily_p0(
        self,
        instance_date,
        limit=50,
        concurrency=3,
        table_timeout_seconds=120,
        retry=2,
        retry_backoff_seconds=2,
        api_delay_seconds=0.2,
        failure_threshold=0.3,
    ):
        run_id = f"{instance_date}_daily_p0"
        candidates = self._daily_p0_candidates(limit)
        self.store.create_patrol_run(run_id, instance_date, "daily_p0", {"limit": limit})
        started = time.monotonic()
        checked = 0
        errors = 0
        timeouts = 0
        executor = ThreadPoolExecutor(max_workers=max(1, int(concurrency or 1)))
        try:
            future_items = [
                (
                    table,
                    executor.submit(
                        self._check_table,
                        table,
                        retry=retry,
                        retry_backoff_seconds=retry_backoff_seconds,
                        api_delay_seconds=api_delay_seconds,
                    ),
                )
                for table in candidates
            ]
            for table, future in future_items:
                checked += 1
                try:
                    item = future.result(timeout=table_timeout_seconds)
                except TimeoutError:
                    future.cancel()
                    timeouts += 1
                    item = self._timeout_result(table, table_timeout_seconds)
                except Exception as exc:
                    item = self._exception_result(table, exc)
                self._persist_table_result(run_id, item)
                errors += 1 if item.get("errors") else 0
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        self.store.insert_patrol_metric(
            {"run_id": run_id, "metric_name": "checked_count", "metric_value": checked, "dimension": {"scope": "daily_p0"}}
        )
        self.store.insert_patrol_metric(
            {"run_id": run_id, "metric_name": "error_count", "metric_value": errors, "dimension": {"scope": "daily_p0"}}
        )
        self.store.insert_patrol_metric(
            {"run_id": run_id, "metric_name": "timeout_count", "metric_value": timeouts, "dimension": {"scope": "daily_p0"}}
        )
        status = "completed" if errors == 0 else "partial"
        if checked and errors / checked > failure_threshold:
            status = "failed"
        summary = {
            "checked_count": checked,
            "error_count": errors,
            "timeout_count": timeouts,
            "duration_seconds": round(time.monotonic() - started, 3),
            "concurrency": concurrency,
            "table_timeout_seconds": table_timeout_seconds,
            "retry": retry,
            "api_delay_seconds": api_delay_seconds,
            "failure_threshold": failure_threshold,
            "finished_at": datetime.utcnow().isoformat(),
        }
        self.store.finish_patrol_run(run_id, status, summary)
        return {"run_id": run_id, "status": status, **summary}

    def _check_table(self, table, retry=2, retry_backoff_seconds=2, api_delay_seconds=0.2):
        if api_delay_seconds:
            time.sleep(api_delay_seconds)
        attempts = 0
        last_result = None
        while attempts <= retry:
            result = LiveAssetService(self.store, self.live).get_partition_profile(table["name"], "")
            last_result = result
            if result.source != Source.PARTIAL_LIVE:
                return {
                    "asset_name": table["name"],
                    "table": table,
                    "status": "ok",
                    "snapshot": result.as_dict(),
                    "errors": [],
                    "timed_out": False,
                }
            retryable = any(error.get("retryable") for error in result.errors)
            if not retryable or attempts == retry:
                return {
                    "asset_name": table["name"],
                    "table": table,
                    "status": "check_failed",
                    "snapshot": result.as_dict(),
                    "errors": result.errors,
                    "timed_out": False,
                }
            attempts += 1
            if retry_backoff_seconds:
                time.sleep(retry_backoff_seconds * attempts)
        return {
            "asset_name": table["name"],
            "table": table,
            "status": "check_failed",
            "snapshot": last_result.as_dict() if last_result else {},
            "errors": last_result.errors if last_result else [],
            "timed_out": False,
        }

    def _timeout_result(self, table, table_timeout_seconds):
        return {
            "asset_name": table["name"],
            "table": table,
            "status": "check_failed",
            "snapshot": {"status": "unknown", "source": Source.PARTIAL_LIVE},
            "errors": [
                {
                    "module": "table_check",
                    "status": "check_failed",
                    "api_action": "patrol_table_check",
                    "error_code": "Timeout",
                    "error_message": f"table check exceeded {table_timeout_seconds} seconds",
                    "retryable": True,
                }
            ],
            "timed_out": True,
        }

    def _exception_result(self, table, exc):
        return {
            "asset_name": table["name"],
            "table": table,
            "status": "check_failed",
            "snapshot": {"status": "unknown", "source": Source.PARTIAL_LIVE},
            "errors": [
                {
                    "module": "table_check",
                    "status": "check_failed",
                    "api_action": "patrol_table_check",
                    "error_code": exc.__class__.__name__,
                    "error_message": str(exc),
                    "retryable": False,
                }
            ],
            "timed_out": False,
        }

    def _persist_table_result(self, run_id, item):
        table = item["table"]
        for error in item.get("errors", []):
            self.store.insert_patrol_error(
                {
                    "run_id": run_id,
                    "asset_name": table["name"],
                    "module": error.get("module", ""),
                    "api_action": error.get("api_action", ""),
                    "error_code": error.get("error_code", ""),
                    "error_message": error.get("error_message", ""),
                    "retryable": error.get("retryable", False),
                }
            )
        self.store.upsert_patrol_asset_snapshot(
            {
                "run_id": run_id,
                "asset_name": table["name"],
                "asset_type": "table",
                "layer": table.get("layer", ""),
                "owner": table.get("owner", ""),
                "core_level": "",
                "status": item.get("status", "unknown"),
                "snapshot": item.get("snapshot") or {},
            }
        )

    def _daily_p0_candidates(self, limit):
        rows = self.store._all(
            """
            select name, layer, owner, database_name
            from tables
            where layer in ('ods', 'dim', 'dwd', 'dws', 'mid', 'ads')
            order by case when layer in ('ads', 'dws', 'dwd') then 0 else 1 end, name
            limit ?
            """,
            (int(limit or 50),),
        )
        return [dict(row) for row in rows]
