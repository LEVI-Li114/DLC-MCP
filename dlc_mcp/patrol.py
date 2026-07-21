import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import datetime

from .assets import diagnose_producer_mapping_gap
from .source import Source


class PatrolService:
    def __init__(self, store, live):
        self.store = store
        self.live = live
        self._store_lock = threading.RLock()

    def run(self, scope, instance_date, **options):
        if scope == "daily_p0":
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
        if scope in {"daily_core", "monthly_full", "manual"}:
            return self._run_scope(scope, instance_date, **options)
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
        return self._run_candidates(
            run_id,
            instance_date,
            "daily_p0",
            candidates,
            limit=limit,
            concurrency=concurrency,
            table_timeout_seconds=table_timeout_seconds,
            retry=retry,
            retry_backoff_seconds=retry_backoff_seconds,
            api_delay_seconds=api_delay_seconds,
            failure_threshold=failure_threshold,
        )

    def _run_scope(self, scope, instance_date, **options):
        limit = options.get("limit", 50)
        run_id = f"{instance_date}_{scope}"
        candidates = self._scope_candidates(
            scope,
            limit=limit,
            offset=options.get("offset", 0),
            table=options.get("table", ""),
            layer=options.get("layer", ""),
            owner=options.get("owner", ""),
            core_level=options.get("core_level", ""),
        )
        return self._run_candidates(
            run_id,
            instance_date,
            scope,
            candidates,
            limit=limit,
            concurrency=options.get("concurrency", 3),
            table_timeout_seconds=options.get("table_timeout_seconds", 120),
            retry=options.get("retry", 2),
            retry_backoff_seconds=options.get("retry_backoff_seconds", 2),
            api_delay_seconds=options.get("api_delay_seconds", 0.2),
            failure_threshold=options.get("failure_threshold", 0.3),
        )

    def _run_candidates(
        self,
        run_id,
        instance_date,
        scope,
        candidates,
        limit=50,
        concurrency=3,
        table_timeout_seconds=120,
        retry=2,
        retry_backoff_seconds=2,
        api_delay_seconds=0.2,
        failure_threshold=0.3,
    ):
        self.store.create_patrol_run(run_id, instance_date, scope, {"limit": limit})
        started = time.monotonic()
        checked = 0
        errors = 0
        timeouts = 0
        live_success_count = 0
        live_partial_count = 0
        live_failed_count = 0
        p0_count = 0
        p1_count = 0
        p2_count = 0
        executor = ThreadPoolExecutor(max_workers=max(1, int(concurrency or 1)))
        try:
            future_items = [
                (
                    table,
                    executor.submit(
                        self._check_table,
                        {**table, "instance_date": instance_date},
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
                status_value = item.get("status", "unknown")
                if status_value == "healthy":
                    live_success_count += 1
                elif status_value in {"p0", "p1", "p2"}:
                    live_partial_count += 1
                elif status_value in {"live_failed", "check_failed"}:
                    live_failed_count += 1
                if status_value == "p0":
                    p0_count += 1
                elif status_value == "p1":
                    p1_count += 1
                elif status_value == "p2":
                    p2_count += 1
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        for metric_name, metric_value in (
            ("checked_count", checked),
            ("error_count", errors),
            ("timeout_count", timeouts),
            ("live_success_count", live_success_count),
            ("live_partial_count", live_partial_count),
            ("live_failed_count", live_failed_count),
            ("p0_count", p0_count),
            ("p1_count", p1_count),
            ("p2_count", p2_count),
        ):
            self.store.insert_patrol_metric(
                {"run_id": run_id, "metric_name": metric_name, "metric_value": metric_value, "dimension": {"scope": scope}}
            )
        status = "completed" if errors == 0 else "partial"
        if checked and errors / checked > failure_threshold:
            status = "failed"
        summary = {
            "checked_count": checked,
            "error_count": errors,
            "timeout_count": timeouts,
            "live_success_count": live_success_count,
            "live_partial_count": live_partial_count,
            "live_failed_count": live_failed_count,
            "p0_count": p0_count,
            "p1_count": p1_count,
            "p2_count": p2_count,
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
            evidence = self._collect_table_evidence(table, table.get("instance_date", ""))
            result = self._normalize_table_result(table, evidence)
            last_result = result
            if not result.get("errors"):
                return result
            retryable = any(error.get("retryable") for error in result.get("errors", []))
            if not retryable or attempts == retry:
                return result
            attempts += 1
            if retry_backoff_seconds:
                time.sleep(retry_backoff_seconds * attempts)
        return last_result or self._exception_result(table, RuntimeError("patrol check failed"))

    def _collect_table_evidence(self, table, instance_date):
        table_name = table["name"]
        errors = []
        with self._store_lock:
            detail = self.store.get_table_detail(table_name=table_name)
            profile = self.store.get_table_profile(table_name)
            lineage = self.store.get_table_lineage(table_name)
            columns = detail.get("columns", []) if not detail.get("error") else []
            table_detail = detail.get("table", {}) if not detail.get("error") else {}
            upstream = lineage.get("upstream", []) if not lineage.get("error") else []
            downstream = lineage.get("downstream", []) if not lineage.get("error") else []

            live_tasks = self._safe_live_call("tasks", "get_table_tasks", lambda: self._live_table_tasks(table_name), errors)
            live_quality = self._safe_live_call("quality", "get_quality_status", lambda: self._live_quality_status(table_name), errors)
            live_runs = self._safe_live_call("runs", "get_table_production_status", lambda: self._live_production_status(table_name, instance_date), errors)
            if hasattr(self.live, "sync_table_partitions"):
                self._safe_live_call("partition", "DescribeTablePartitions", lambda: self.live.sync_table_partitions(table_name), errors)

        return {
            "source_policy": {
                "metadata": "cache",
                "columns": "cache",
                "lineage": "cache",
                "tasks": "live_only",
                "quality": "live_only",
                "runs": "live_only",
            },
            "cached": {
                "metadata": {
                    "status": "missing" if detail.get("error") else "complete",
                    "table": table_detail,
                    "core_level": (profile.get("core") or {}).get("core_level", "") if not profile.get("error") else "",
                    "owner_resolution": profile.get("owner_resolution", {}) if not profile.get("error") else {},
                },
                "columns": {"status": "missing" if not columns else "complete", "count": len(columns)},
                "lineage": {
                    "status": "missing" if not upstream and not downstream else "complete",
                    "upstream_count": len(upstream),
                    "downstream_count": len(downstream),
                },
            },
            "live": {
                "tasks": self._normalize_live_tasks(live_tasks),
                "quality": self._normalize_live_quality(live_quality),
                "runs": self._normalize_live_runs(live_runs),
            },
            "errors": errors,
        }

    def _live_table_tasks(self, table_name):
        if hasattr(self.live, "get_table_tasks_live"):
            return self.live.get_table_tasks_live(table_name)
        return self.store.get_table_tasks(table_name)

    def _live_quality_status(self, table_name):
        if hasattr(self.live, "get_quality_status_live"):
            return self.live.get_quality_status_live(table_name)
        return self.store.get_quality_status(table_name)

    def _live_production_status(self, table_name, instance_date):
        if hasattr(self.live, "get_table_production_status_live"):
            return self.live.get_table_production_status_live(table_name, instance_date)
        return self.store.get_table_production_status(table_name, instance_date)

    def _safe_live_call(self, module, tool, fn, errors):
        try:
            value = fn()
            return value if value is not None else {}
        except Exception as exc:
            errors.append(
                {
                    "module": module,
                    "status": "check_failed",
                    "api_action": tool,
                    "error_code": exc.__class__.__name__,
                    "error_message": str(exc),
                    "retryable": "InternalError" in str(exc) or "timeout" in str(exc).lower(),
                }
            )
            return {"error": "live_failed", "message": str(exc)}

    def _normalize_live_tasks(self, data):
        if data.get("error") == "live_failed":
            return {"status": "live_failed", "producer_count": 0, "consumer_count": 0, "raw": data}
        tasks = data.get("tasks") or data.get("results") or []
        producer_count = len([item for item in tasks if item.get("direction") in {"output", "producer", "produces"}])
        consumer_count = len([item for item in tasks if item.get("direction") in {"input", "consumer", "consumes"}])
        return {"status": "complete" if tasks else "missing", "producer_count": producer_count, "consumer_count": consumer_count, "count": len(tasks), "raw": data}

    def _normalize_live_quality(self, data):
        if data.get("error") == "live_failed":
            return {"status": "live_failed", "rule_count": 0, "raw": data}
        rule_count = int(data.get("rule_count") or len(data.get("rules") or []))
        return {"status": "complete" if rule_count else "missing", "rule_count": rule_count, "raw": data}

    def _normalize_live_runs(self, data):
        if data.get("error") == "live_failed":
            return {"status": "live_failed", "run_count": 0, "raw": data}
        runs = data.get("runs") or data.get("instances") or data.get("tasks") or []
        summary_status = data.get("summary_status") or data.get("status") or ""
        if summary_status in {"failed", "timeout"}:
            status = summary_status
        elif runs:
            status = "complete"
        else:
            status = "missing"
        return {"status": status, "run_count": len(runs), "summary_status": summary_status, "raw": data}

    def _producer_diagnosis(self, table, cached, live_tasks):
        lineage = cached.get("lineage", {})
        context = {
            "name": table.get("name", ""),
            "layer": table.get("layer", ""),
            "task_count": live_tasks.get("count", 0),
            "producer_task_count": live_tasks.get("producer_count", 0),
            "consumer_task_count": live_tasks.get("consumer_count", 0),
            "upstream_count": lineage.get("upstream_count", 0),
            "downstream_count": lineage.get("downstream_count", 0),
            "run_count": 0,
        }
        if live_tasks.get("status") == "live_failed":
            raw = live_tasks.get("raw") or {}
            return diagnose_producer_mapping_gap(
                context,
                live_error=raw.get("message") or raw.get("error") or "live task evidence unavailable",
                evidence_source="patrol_live_context",
            )
        return diagnose_producer_mapping_gap(context, live_tasks=live_tasks.get("raw", {}), evidence_source="patrol_live_context")

    def _finding(self, issue_type, severity, source, evidence, owner_bucket="warehouse_owner", suggested_action=""):
        return {"issue_type": issue_type, "severity": severity, "source": source, "evidence": evidence, "owner_bucket": owner_bucket, "suggested_action": suggested_action}

    def _normalize_table_result(self, table, evidence):
        findings = []
        cached = evidence.get("cached", {})
        live = evidence.get("live", {})
        if cached.get("metadata", {}).get("status") == "missing":
            findings.append(self._finding("missing_table_metadata", "P0", "cache", cached.get("metadata", {}), suggested_action="Refresh table metadata cache."))
        if cached.get("columns", {}).get("status") == "missing":
            findings.append(self._finding("missing_columns", "P0", "cache", cached.get("columns", {}), suggested_action="Refresh table columns cache."))
        if cached.get("lineage", {}).get("status") == "missing":
            findings.append(self._finding("missing_lineage", "P1", "cache", cached.get("lineage", {}), suggested_action="Refresh table lineage cache."))
        if live.get("tasks", {}).get("status") in {"missing", "live_failed"}:
            task_evidence = dict(live.get("tasks", {}))
            diagnosis = self._producer_diagnosis(table, cached, task_evidence)
            task_evidence["producer_diagnosis"] = diagnosis
            findings.append(self._finding("missing_producer_task", "P1", "live", task_evidence, suggested_action=diagnosis["next_check"]))
        if live.get("quality", {}).get("status") == "missing":
            findings.append(self._finding("missing_quality_rules", "P1", "live", live.get("quality", {}), suggested_action="Confirm or add minimum quality rules for this core table."))
        run_status = live.get("runs", {}).get("status")
        if run_status == "missing":
            findings.append(self._finding("missing_task_runs", "P1", "live", live.get("runs", {}), suggested_action="Check producer task mapping before validating run instances."))
        if run_status in {"failed", "timeout"}:
            findings.append(self._finding("task_run_failed", "P0", "live", live.get("runs", {}), suggested_action="Inspect failed producer task run."))
        if evidence.get("errors"):
            status = "live_failed"
        elif any(item["severity"] == "P0" for item in findings):
            status = "p0"
        elif findings:
            status = "p1"
        else:
            status = "healthy"
        return {"asset_name": table["name"], "table": table, "status": status, "snapshot": {"source_policy": evidence.get("source_policy", {}), "cached": cached, "live": live, "coverage_status": status}, "findings": findings, "errors": evidence.get("errors", []), "timed_out": False}

    def _timeout_result(self, table, table_timeout_seconds):
        return {
            "asset_name": table["name"],
            "table": table,
            "status": "check_failed",
            "snapshot": {"status": "unknown", "source": Source.PARTIAL_LIVE},
            "errors": [{"module": "table_check", "status": "check_failed", "api_action": "patrol_table_check", "error_code": "Timeout", "error_message": f"table check exceeded {table_timeout_seconds} seconds", "retryable": True}],
            "timed_out": True,
        }

    def _exception_result(self, table, exc):
        return {
            "asset_name": table["name"],
            "table": table,
            "status": "check_failed",
            "snapshot": {"status": "unknown", "source": Source.PARTIAL_LIVE},
            "errors": [{"module": "table_check", "status": "check_failed", "api_action": "patrol_table_check", "error_code": exc.__class__.__name__, "error_message": str(exc), "retryable": False}],
            "timed_out": False,
        }

    def _persist_table_result(self, run_id, item):
        table = item["table"]
        with self._store_lock:
            for error in item.get("errors", []):
                self.store.insert_patrol_error({"run_id": run_id, "asset_name": table["name"], "module": error.get("module", ""), "api_action": error.get("api_action", ""), "error_code": error.get("error_code", ""), "error_message": error.get("error_message", ""), "retryable": error.get("retryable", False)})
            for finding in item.get("findings", []):
                self.store.insert_patrol_finding({"run_id": run_id, "asset_name": table["name"], "issue_type": finding.get("issue_type", ""), "severity": finding.get("severity", ""), "evidence": {"source": finding.get("source", ""), **(finding.get("evidence") or {})}, "owner_bucket": finding.get("owner_bucket", ""), "suggested_action": finding.get("suggested_action", "")})
            self.store.upsert_patrol_asset_snapshot({"run_id": run_id, "asset_name": table["name"], "asset_type": "table", "layer": table.get("layer", ""), "owner": table.get("owner", ""), "core_level": (item.get("snapshot", {}).get("cached", {}).get("metadata", {}) or {}).get("core_level", ""), "status": item.get("status", "unknown"), "snapshot": item.get("snapshot") or {}})

    def _scope_candidates(self, scope, limit=50, offset=0, table="", layer="", owner="", core_level=""):
        if scope == "daily_p0":
            return self._daily_p0_candidates(limit)
        if scope == "daily_core":
            return self._daily_core_candidates(limit, offset=offset, layer=layer, owner=owner, core_level=core_level)
        if scope == "monthly_full":
            return self._monthly_full_candidates(limit, offset=offset, layer=layer, owner=owner)
        if scope == "manual":
            return self._manual_candidates(limit, offset=offset, table=table, layer=layer, owner=owner, core_level=core_level)
        raise ValueError(f"unsupported scope: {scope}")

    def _monthly_full_candidates(self, limit, offset=0, layer="", owner=""):
        where = []
        params = []
        if layer:
            where.append("layer = ?")
            params.append(layer)
        if owner:
            where.append("owner = ?")
            params.append(owner)
        sql = "select name, layer, owner, database_name from tables"
        if where:
            sql += " where " + " and ".join(where)
        sql += " order by layer, name limit ? offset ?"
        params.extend([int(limit or 100), int(offset or 0)])
        return [dict(row) for row in self.store._all(sql, tuple(params))]

    def _manual_candidates(self, limit, offset=0, table="", layer="", owner="", core_level=""):
        where = []
        params = []
        if table:
            where.append("name = ?")
            params.append(table)
        if layer:
            where.append("layer = ?")
            params.append(layer)
        if owner:
            where.append("owner = ?")
            params.append(owner)
        sql = "select name, layer, owner, database_name from tables"
        if where:
            sql += " where " + " and ".join(where)
        sql += " order by layer, name limit ? offset ?"
        params.extend([int(limit or 50), int(offset or 0)])
        return [dict(row) for row in self.store._all(sql, tuple(params))]

    def _daily_core_candidates(self, limit, offset=0, layer="", owner="", core_level=""):
        where = ["layer in ('ods', 'dim', 'dwd', 'dws', 'mid', 'ads')", "not (" + _temporary_table_predicate("name") + ")"]
        params = []
        if layer:
            where.append("layer = ?")
            params.append(layer)
        if owner:
            where.append("owner = ?")
            params.append(owner)
        sql = """
            select name, layer, owner, database_name
            from tables
            where {where_clause}
            order by case when layer in ('ads', 'dws', 'dwd') then 0 else 1 end, name
            limit ? offset ?
        """.format(where_clause=" and ".join(where))
        params.extend([int(limit or 50), int(offset or 0)])
        return [dict(row) for row in self.store._all(sql, tuple(params))]

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


def _temporary_table_predicate(column):
    return " or ".join(
        f"lower({column}) like '{pattern}' escape '\\'"
        for pattern in (
            'tmp\\_%',
            '%\\_tmp',
            '%\\_tmp\\_%',
            '%\\_bak',
            '%\\_bak%',
            '%\\_copy',
            '%\\_copy%',
        )
    )
