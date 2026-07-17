from datetime import datetime

from .live_assets import LiveAssetService
from .source import Source


class PatrolService:
    def __init__(self, store, live):
        self.store = store
        self.live = live

    def run_daily_p0(self, instance_date, limit=50):
        run_id = f"{instance_date}_daily_p0"
        candidates = self._daily_p0_candidates(limit)
        self.store.create_patrol_run(run_id, instance_date, "daily_p0", {"limit": limit})
        checked = 0
        errors = 0
        for table in candidates:
            checked += 1
            result = LiveAssetService(self.store, self.live).get_partition_profile(table["name"], "")
            if result.source == Source.PARTIAL_LIVE:
                errors += len(result.errors)
                for error in result.errors:
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
            status = "check_failed" if result.source == Source.PARTIAL_LIVE else "ok"
            self.store.upsert_patrol_asset_snapshot(
                {
                    "run_id": run_id,
                    "asset_name": table["name"],
                    "asset_type": "table",
                    "layer": table.get("layer", ""),
                    "owner": table.get("owner", ""),
                    "core_level": "",
                    "status": status,
                    "snapshot": result.as_dict(),
                }
            )
        self.store.insert_patrol_metric(
            {
                "run_id": run_id,
                "metric_name": "checked_count",
                "metric_value": checked,
                "dimension": {"scope": "daily_p0"},
            }
        )
        self.store.insert_patrol_metric(
            {
                "run_id": run_id,
                "metric_name": "error_count",
                "metric_value": errors,
                "dimension": {"scope": "daily_p0"},
            }
        )
        status = "completed" if errors == 0 else "partial"
        if checked and errors / checked > 0.30:
            status = "failed"
        summary = {"checked_count": checked, "error_count": errors, "finished_at": datetime.utcnow().isoformat()}
        self.store.finish_patrol_run(run_id, status, summary)
        return {"run_id": run_id, "status": status, **summary}

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
