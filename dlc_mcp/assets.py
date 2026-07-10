import sqlite3
import json
import os


GOVERNANCE_ISSUE_TYPES = [
    "unknown_layer",
    "missing_quality_rules",
    "missing_task_mapping",
    "missing_task_runs",
    "missing_data_source",
    "missing_owner",
    "partition_unsupported",
    "profile_incomplete",
]


class AssetStore:
    def __init__(self, conn):
        self.conn = conn
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("pragma busy_timeout = 30000")

    def init_schema(self):
        self.conn.executescript(
            """
            create table if not exists tables (
                name text primary key,
                source_guid text not null default '',
                data_source_id text not null default '',
                database_name text not null default '',
                layer text not null default '',
                domain text not null default '',
                owner text not null default '',
                description text not null default '',
                manual_core_level text
            );
            create table if not exists columns (
                table_name text not null,
                name text not null,
                type text not null default '',
                description text not null default '',
                ordinal integer not null default 0,
                primary key (table_name, name)
            );
            create table if not exists lineage (
                upstream text not null,
                downstream text not null,
                via text not null default '',
                primary key (upstream, downstream, via)
            );
            create table if not exists quality_rules (
                table_name text not null,
                rule_name text not null,
                rule_type text not null default '',
                target text not null default '',
                enabled integer not null default 1,
                last_status text not null default '',
                last_checked_at text not null default '',
                primary key (table_name, rule_name)
            );
            create table if not exists tasks (
                id text primary key,
                name text not null default '',
                task_type text not null default '',
                cycle text not null default '',
                schedule_time text not null default '',
                schedule_desc text not null default '',
                owner text not null default '',
                status text not null default ''
            );
            create table if not exists task_tables (
                task_id text not null,
                table_name text not null,
                direction text not null,
                primary key (task_id, table_name, direction)
            );
            create table if not exists task_runs (
                task_id text not null,
                instance_id text not null,
                instance_date text not null default '',
                start_time text not null default '',
                end_time text not null default '',
                duration_seconds integer not null default 0,
                status text not null default '',
                primary key (task_id, instance_id)
            );
            create table if not exists data_sources (
                id text primary key,
                name text not null default '',
                type text not null default '',
                owner text not null default '',
                description text not null default '',
                config_json text not null default '{}'
            );
            create table if not exists data_source_tasks (
                data_source_id text not null,
                task_id text not null,
                task_name text not null default '',
                task_type text not null default '',
                project_id text not null default '',
                project_name text not null default '',
                create_time text not null default '',
                owner text not null default '',
                primary key (data_source_id, task_id)
            );
            create table if not exists table_partitions (
                table_name text not null,
                partition_name text not null,
                partition_date text not null default '',
                row_count integer not null default 0,
                storage_bytes integer not null default 0,
                file_count integer not null default 0,
                updated_at text not null default '',
                collected_at text not null default '',
                primary key (table_name, partition_name)
            );
            create table if not exists expert_labels (
                asset_type text not null,
                asset_name text not null,
                core_level text not null default '',
                value_tier text not null default '',
                domain text not null default '',
                use_case text not null default '',
                metric_definition text not null default '',
                owner text not null default '',
                reviewer text not null default '',
                reason text not null default '',
                updated_at text not null default '',
                primary key (asset_type, asset_name)
            );
            """
        )
        self._add_column_if_missing("tables", "source_guid", "text not null default ''")
        self._add_column_if_missing("tables", "data_source_id", "text not null default ''")
        self._add_column_if_missing("tasks", "schedule_time", "text not null default ''")
        self._add_column_if_missing("tasks", "schedule_desc", "text not null default ''")
        self.conn.commit()

    def upsert_table(self, item):
        self.conn.execute(
            """
            insert into tables (name, source_guid, data_source_id, database_name, layer, domain, owner, description, manual_core_level)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(name) do update set
                source_guid = coalesce(nullif(excluded.source_guid, ''), tables.source_guid),
                data_source_id = coalesce(nullif(excluded.data_source_id, ''), tables.data_source_id),
                database_name = coalesce(nullif(excluded.database_name, ''), tables.database_name),
                layer = coalesce(nullif(excluded.layer, ''), tables.layer),
                domain = coalesce(nullif(excluded.domain, ''), tables.domain),
                owner = coalesce(nullif(excluded.owner, ''), tables.owner),
                description = coalesce(nullif(excluded.description, ''), tables.description),
                manual_core_level = coalesce(excluded.manual_core_level, tables.manual_core_level)
            """,
            (
                item["name"],
                item.get("guid", ""),
                item.get("data_source_id", ""),
                item.get("database", ""),
                item.get("layer", ""),
                item.get("domain", ""),
                item.get("owner", ""),
                item.get("description", ""),
                item.get("manual_core_level"),
            ),
        )
        self.conn.commit()

    def upsert_column(self, table_name, name, column_type="", description="", ordinal=0):
        self.conn.execute(
            """
            insert into columns (table_name, name, type, description, ordinal)
            values (?, ?, ?, ?, ?)
            on conflict(table_name, name) do update set
                type = excluded.type,
                description = excluded.description,
                ordinal = excluded.ordinal
            """,
            (table_name, name, column_type, description, ordinal),
        )
        self.conn.commit()

    def upsert_lineage(self, upstream, downstream, via=""):
        self.conn.execute(
            "insert or replace into lineage (upstream, downstream, via) values (?, ?, ?)",
            (upstream, downstream, via),
        )
        self.conn.commit()

    def upsert_quality_rule(self, item):
        self.conn.execute(
            """
            insert into quality_rules (table_name, rule_name, rule_type, target, enabled, last_status, last_checked_at)
            values (?, ?, ?, ?, ?, ?, ?)
            on conflict(table_name, rule_name) do update set
                rule_type = excluded.rule_type,
                target = excluded.target,
                enabled = excluded.enabled,
                last_status = excluded.last_status,
                last_checked_at = excluded.last_checked_at
            """,
            (
                item["table_name"],
                item["rule_name"],
                item.get("rule_type", ""),
                item.get("target", ""),
                1 if item.get("enabled", True) else 0,
                item.get("last_status", ""),
                item.get("last_checked_at", ""),
            ),
        )
        self.conn.commit()

    def upsert_task(self, item):
        self.conn.execute(
            """
            insert into tasks (id, name, task_type, cycle, schedule_time, schedule_desc, owner, status)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(id) do update set
                name = excluded.name,
                task_type = excluded.task_type,
                cycle = excluded.cycle,
                schedule_time = excluded.schedule_time,
                schedule_desc = excluded.schedule_desc,
                owner = excluded.owner,
                status = excluded.status
            """,
            (
                item["id"],
                item.get("name", ""),
                item.get("task_type", ""),
                item.get("cycle", ""),
                item.get("schedule_time", ""),
                item.get("schedule_desc", ""),
                item.get("owner", ""),
                item.get("status", ""),
            ),
        )
        self.conn.execute("delete from task_tables where task_id = ?", (item["id"],))
        for table_name in item.get("inputs", []):
            self.conn.execute("insert into task_tables (task_id, table_name, direction) values (?, ?, 'input')", (item["id"], table_name))
        for table_name in item.get("outputs", []):
            self.conn.execute("insert into task_tables (task_id, table_name, direction) values (?, ?, 'output')", (item["id"], table_name))
        self.conn.commit()

    def upsert_data_source(self, item):
        self.conn.execute(
            """
            insert into data_sources (id, name, type, owner, description, config_json)
            values (?, ?, ?, ?, ?, ?)
            on conflict(id) do update set
                name = excluded.name,
                type = excluded.type,
                owner = excluded.owner,
                description = excluded.description,
                config_json = excluded.config_json
            """,
            (
                item["id"],
                item.get("name", ""),
                item.get("type", ""),
                item.get("owner", ""),
                item.get("description", ""),
                json.dumps(item.get("config", {}), ensure_ascii=False, sort_keys=True),
            ),
        )
        self.conn.commit()

    def replace_data_source_tasks(self, data_source_id, tasks):
        self.conn.execute("delete from data_source_tasks where data_source_id = ?", (data_source_id,))
        for item in tasks:
            self.conn.execute(
                """
                insert or replace into data_source_tasks
                    (data_source_id, task_id, task_name, task_type, project_id, project_name, create_time, owner)
                values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data_source_id,
                    item["task_id"],
                    item.get("task_name", ""),
                    item.get("task_type", ""),
                    item.get("project_id", ""),
                    item.get("project_name", ""),
                    item.get("create_time", ""),
                    item.get("owner", ""),
                ),
            )
        self.conn.commit()

    def upsert_table_partition(self, item):
        self.conn.execute(
            """
            insert into table_partitions (table_name, partition_name, partition_date, row_count, storage_bytes, file_count, updated_at, collected_at)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(table_name, partition_name) do update set
                partition_date = excluded.partition_date,
                row_count = excluded.row_count,
                storage_bytes = excluded.storage_bytes,
                file_count = excluded.file_count,
                updated_at = excluded.updated_at,
                collected_at = excluded.collected_at
            """,
            (
                item["table_name"],
                item["partition_name"],
                item.get("partition_date", ""),
                int(item.get("row_count") or 0),
                int(item.get("storage_bytes") or 0),
                int(item.get("file_count") or 0),
                item.get("updated_at", ""),
                item.get("collected_at", ""),
            ),
        )
        self.conn.commit()

    def list_data_sources(self, query=""):
        like = f"%{query}%"
        rows = self._all(
            """
            select id, name, type, owner, description, config_json
            from data_sources
            where ? = '' or id like ? or name like ? or type like ? or owner like ?
            order by name
            limit 200
            """,
            (query, like, like, like, like),
        )
        return {"query": query, "results": [self._data_source_dict(row) for row in rows]}

    def get_data_source(self, data_source_id):
        row = self._one("select id, name, type, owner, description, config_json from data_sources where id = ?", (data_source_id,))
        if not row:
            return {"error": "data_source_not_found", "data_source_id": data_source_id}
        return self._data_source_dict(row)

    def list_data_source_tasks(self, data_source_id):
        if not self._one("select 1 from data_sources where id = ?", (data_source_id,)):
            return {"error": "data_source_not_found", "data_source_id": data_source_id}
        rows = self._all(
            """
            select task_id, task_name, task_type, project_id, project_name, create_time, owner
            from data_source_tasks
            where data_source_id = ?
            order by task_name
            """,
            (data_source_id,),
        )
        return {"data_source_id": data_source_id, "tasks": [dict(row) for row in rows]}

    def list_metadata(self):
        databases = [row["database_name"] for row in self._all("select distinct database_name from tables where database_name != '' order by database_name")]
        tables = [self._table_dict(row) for row in self._all("select name, source_guid, data_source_id, database_name, layer, domain, owner, description, manual_core_level from tables order by database_name, name limit 100")]
        return {"databases": databases, "tables": tables}

    def get_sync_health(self):
        counts = {
            "tables": self._count("tables"),
            "columns": self._count("columns"),
            "tasks": self._count("tasks"),
            "task_table_mappings": self._count("task_tables"),
            "task_runs": self._count("task_runs"),
            "data_sources": self._count("data_sources"),
            "data_source_tasks": self._count("data_source_tasks"),
            "lineage_edges": self._count("lineage"),
            "quality_rules": self._count("quality_rules"),
            "expert_labels": self._count("expert_labels"),
        }
        signals = {
            "latest_task_run_start": self._max_text("task_runs", "start_time"),
            "latest_task_run_end": self._max_text("task_runs", "end_time"),
            "latest_quality_check": self._max_text("quality_rules", "last_checked_at"),
            "latest_data_source_task_create": self._max_text("data_source_tasks", "create_time"),
        }
        gaps = []
        if counts["tasks"] == 0:
            gaps.append("未同步 WeData 任务列表")
        if counts["tables"] == 0:
            gaps.append("未同步表资产")
        if counts["columns"] == 0:
            gaps.append("未同步字段")
        if counts["lineage_edges"] == 0:
            gaps.append("未同步血缘")
        if counts["quality_rules"] == 0:
            gaps.append("未同步质量规则")
        if counts["task_runs"] == 0:
            gaps.append("未同步任务运行实例")
        if counts["data_sources"] == 0:
            gaps.append("未同步数据源")
        return {
            "status": "ok" if counts["tasks"] and not gaps else "partial",
            "counts": counts,
            "latest_signals": signals,
            "gaps": gaps,
            "notes": [
                "当前版本根据资产库已有事实表聚合健康状态。",
                "如果某类数量为 0，通常表示对应 WeData 同步开关未开启、接口未接入或本轮同步未覆盖。",
            ],
        }

    def get_asset_coverage(self):
        totals = self.get_sync_health()["counts"]
        layer_rows = self._all(
            """
            select
                coalesce(nullif(layer, ''), 'unknown') as layer,
                count(*) as table_count,
                sum(case when c.column_count > 0 then 1 else 0 end) as tables_with_columns,
                sum(case when q.rule_count > 0 then 1 else 0 end) as tables_with_quality_rules,
                sum(case when d.downstream_count > 0 then 1 else 0 end) as tables_with_downstream,
                sum(case when u.upstream_count > 0 then 1 else 0 end) as tables_with_upstream,
                sum(case when tt.task_count > 0 then 1 else 0 end) as tables_with_tasks,
                sum(case when data_source_id != '' then 1 else 0 end) as tables_with_data_source
            from tables t
            left join (select table_name, count(*) as column_count from columns group by table_name) c on c.table_name = t.name
            left join (select table_name, count(*) as rule_count from quality_rules group by table_name) q on q.table_name = t.name
            left join (select upstream, count(*) as downstream_count from lineage group by upstream) d on d.upstream = t.name
            left join (select downstream, count(*) as upstream_count from lineage group by downstream) u on u.downstream = t.name
            left join (select table_name, count(distinct task_id) as task_count from task_tables group by table_name) tt on tt.table_name = t.name
            group by coalesce(nullif(layer, ''), 'unknown')
            order by layer
            """
        )
        return {
            "totals": totals,
            "layers": [dict(row) for row in layer_rows],
            "coverage_notes": [
                "字段、质量、血缘、任务、数据源覆盖率都按已同步表资产计算。",
                "覆盖为 0 不等于业务不存在，优先检查同步开关、API 权限和同步范围。",
            ],
        }

    def list_asset_coverage_gaps(self, gap_type="", layer="", limit=50):
        args = []
        layer_filter = ""
        if layer:
            layer_filter = "where t.layer = ?"
            args.append(layer)
        rows = self._all(
            f"""
            select
                t.name, t.layer, t.domain, t.owner, t.data_source_id,
                coalesce(c.column_count, 0) as column_count,
                coalesce(q.rule_count, 0) as quality_rule_count,
                coalesce(d.downstream_count, 0) as downstream_count,
                coalesce(u.upstream_count, 0) as upstream_count,
                coalesce(tt.task_count, 0) as task_count,
                coalesce(r.run_count, 0) as run_count
            from tables t
            left join (select table_name, count(*) as column_count from columns group by table_name) c on c.table_name = t.name
            left join (select table_name, count(*) as rule_count from quality_rules group by table_name) q on q.table_name = t.name
            left join (select upstream, count(*) as downstream_count from lineage group by upstream) d on d.upstream = t.name
            left join (select downstream, count(*) as upstream_count from lineage group by downstream) u on u.downstream = t.name
            left join (select table_name, count(distinct task_id) as task_count from task_tables group by table_name) tt on tt.table_name = t.name
            left join (
                select tt.table_name, count(distinct r.instance_id) as run_count
                from task_tables tt
                join task_runs r on r.task_id = tt.task_id
                where tt.direction = 'output'
                group by tt.table_name
            ) r on r.table_name = t.name
            {layer_filter}
            order by
                case t.layer when 'ads' then 1 when 'dws' then 2 when 'dwd' then 3 when 'dim' then 4 when 'ods' then 5 else 9 end,
                downstream_count desc,
                task_count desc,
                t.name
            """,
            tuple(args),
        )
        results = []
        wanted = _normalize_gap_type(gap_type)
        for row in rows:
            item = dict(row)
            gaps = _coverage_gaps(item)
            if not gaps:
                continue
            if wanted and wanted not in gaps:
                continue
            item["gaps"] = [_gap_label(gap) for gap in gaps]
            item["gap_keys"] = gaps
            results.append(item)
            if len(results) >= limit:
                break
        return {
            "gap_type": gap_type,
            "layer": layer,
            "limit": limit,
            "results": results,
            "supported_gap_types": ["fields", "quality", "lineage", "upstream", "downstream", "tasks", "runs", "data_source"],
        }

    def get_asset_governance_issue_inventory(self, layer="", core_level="", issue_type="", limit=100):
        wanted = issue_type or ""
        if wanted and wanted not in GOVERNANCE_ISSUE_TYPES:
            return {
                "issue_type": issue_type,
                "layer": layer,
                "core_level": core_level,
                "limit": limit,
                "supported_issue_types": GOVERNANCE_ISSUE_TYPES,
                "results": [],
                "notes": ["unsupported issue_type; use one of supported_issue_types"],
            }
        issues = []
        candidates = self._governance_issue_candidates(layer, core_level)
        for table in candidates:
            table_issues = _governance_issues_for_table(table)
            if wanted:
                table_issues = [issue for issue in table_issues if issue["issue_type"] == wanted]
            issues.extend(table_issues)
            if len(issues) >= limit:
                break
        partition_issues = self._partition_unsupported_issues()
        if wanted:
            partition_issues = [issue for issue in partition_issues if issue["issue_type"] == wanted]
        issues.extend(partition_issues)
        issues = issues[:limit]
        return {
            "issue_type": issue_type,
            "layer": layer,
            "core_level": core_level,
            "limit": limit,
            "supported_issue_types": GOVERNANCE_ISSUE_TYPES,
            "results": issues,
            "notes": [
                "Issue inventory is derived from current SQLite facts and does not call external APIs.",
                "Missing facts are reported as governance gaps, not hidden as healthy states.",
            ],
        }

    def _governance_issue_candidates(self, layer="", core_level=""):
        filters = []
        args = []
        if layer:
            filters.append("coalesce(nullif(t.layer, ''), 'unknown') = ?")
            args.append(layer)
        if core_level:
            filters.append("coalesce(el.core_level, '') = ?")
            args.append(core_level)
        where = "where " + " and ".join(filters) if filters else ""
        return [
            dict(row)
            for row in self._all(
                f"""
                select
                    t.name,
                    coalesce(nullif(t.layer, ''), 'unknown') as layer,
                    t.owner,
                    t.data_source_id,
                    coalesce(el.core_level, '') as core_level,
                    coalesce(c.column_count, 0) as column_count,
                    coalesce(q.rule_count, 0) as quality_rule_count,
                    coalesce(d.downstream_count, 0) as downstream_count,
                    coalesce(tt.task_count, 0) as task_count,
                    coalesce(r.run_count, 0) as run_count
                from tables t
                left join expert_labels el on el.asset_type = 'table' and el.asset_name = t.name
                left join (select table_name, count(*) as column_count from columns group by table_name) c on c.table_name = t.name
                left join (select table_name, count(*) as rule_count from quality_rules group by table_name) q on q.table_name = t.name
                left join (select upstream, count(*) as downstream_count from lineage group by upstream) d on d.upstream = t.name
                left join (select table_name, count(distinct task_id) as task_count from task_tables group by table_name) tt on tt.table_name = t.name
                left join (
                    select tt.table_name, count(distinct r.instance_id) as run_count
                    from task_tables tt
                    join task_runs r on r.task_id = tt.task_id
                    where tt.direction = 'output'
                    group by tt.table_name
                ) r on r.table_name = t.name
                {where}
                order by
                    case coalesce(el.core_level, '') when 'P0' then 1 when 'P1' then 2 when 'P2' then 3 else 9 end,
                    downstream_count desc,
                    t.name
                """,
                tuple(args),
            )
        ]

    def _partition_unsupported_issues(self):
        return []

    def get_asset_governance_daily_report(self, instance_date="", layer="", core_level=""):
        sync_health = self.get_sync_health()
        production_risks = self.list_table_production_risks(layer, core_level, instance_date, "", 20)["results"]
        status_counts = _governance_status_counts(production_risks)
        coverage_gaps = self.list_asset_coverage_gaps("", layer, 20)["results"]
        quality_gaps = self.list_quality_gaps(layer, "", 20)["results"]
        expert_queue = self.list_expert_review_queue(layer, 20)["results"]
        owner_gaps = []
        lifecycle_watch = []
        for table in self._governance_report_candidates(layer, 100):
            core = self.is_core_table(table["name"])
            if core_level and core.get("core_level") != core_level:
                continue
            owner = self.get_asset_owner_profile(table["name"])
            if owner.get("gaps"):
                owner_gaps.append(_governance_owner_gap_item(table, owner))
            lifecycle = self.get_asset_lifecycle_profile(table["name"])
            if lifecycle.get("lifecycle_status") in {"新建/待补齐", "疑似废弃", "待治理"}:
                lifecycle_watch.append(_governance_lifecycle_watch_item(table, lifecycle))
            if len(owner_gaps) >= 20 and len(lifecycle_watch) >= 20:
                break
        owner_gaps = owner_gaps[:20]
        lifecycle_watch = lifecycle_watch[:20]
        issue_inventory = self.get_asset_governance_issue_inventory(layer, core_level, "", 100)
        governance_issues = issue_inventory["results"]
        issue_summary_by_type = _governance_issue_counts(governance_issues, "issue_type")
        issue_summary_by_severity = _governance_issue_counts(governance_issues, "severity")
        issue_summary_by_owner = _governance_issue_counts(governance_issues, "owner")
        responsibility_buckets = _governance_responsibility_buckets(governance_issues)
        summary = {
            "sync_status": sync_health.get("status", ""),
            "production_risk_count": len(production_risks),
            "failed_count": status_counts.get("failed", 0),
            "not_run_count": status_counts.get("not_run", 0),
            "running_count": status_counts.get("running", 0),
            "unknown_count": status_counts.get("unknown", 0),
            "coverage_gap_count": len(coverage_gaps),
            "quality_gap_count": len(quality_gaps),
            "expert_review_count": len(expert_queue),
            "owner_gap_count": len(owner_gaps),
            "lifecycle_watch_count": len(lifecycle_watch),
            "governance_issue_count": len(governance_issues),
        }
        return {
            "instance_date": instance_date,
            "layer": layer,
            "core_level": core_level,
            "summary": summary,
            "production_risks": production_risks,
            "coverage_gaps": coverage_gaps,
            "quality_gaps": quality_gaps,
            "expert_review_queue": expert_queue,
            "owner_gaps": owner_gaps,
            "lifecycle_watch": lifecycle_watch,
            "issue_summary_by_type": issue_summary_by_type,
            "issue_summary_by_severity": issue_summary_by_severity,
            "issue_summary_by_owner": issue_summary_by_owner,
            "top_governance_issues": governance_issues[:20],
            "responsibility_buckets": responsibility_buckets,
            "top_actions": _governance_top_actions(summary, production_risks, quality_gaps, owner_gaps, lifecycle_watch, expert_queue),
            "notes": [
                "巡检日报基于当前本地资产库已同步事实生成，不会触发批量实时同步。",
                "如果某类清单为空，可能表示暂无风险，也可能表示对应同步开关或数据源尚未覆盖。",
            ],
        }

    def upsert_expert_label(self, item):
        self.conn.execute(
            """
            insert into expert_labels
                (asset_type, asset_name, core_level, value_tier, domain, use_case, metric_definition, owner, reviewer, reason, updated_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(asset_type, asset_name) do update set
                core_level = excluded.core_level,
                value_tier = excluded.value_tier,
                domain = excluded.domain,
                use_case = excluded.use_case,
                metric_definition = excluded.metric_definition,
                owner = excluded.owner,
                reviewer = excluded.reviewer,
                reason = excluded.reason,
                updated_at = excluded.updated_at
            """,
            (
                item.get("asset_type", "table"),
                item["asset_name"],
                item.get("core_level", ""),
                item.get("value_tier", ""),
                item.get("domain", ""),
                item.get("use_case", ""),
                item.get("metric_definition", ""),
                item.get("owner", ""),
                item.get("reviewer", ""),
                item.get("reason", ""),
                item.get("updated_at", ""),
            ),
        )
        self.conn.commit()

    def get_expert_label(self, asset_type, asset_name):
        row = self._one(
            """
            select asset_type, asset_name, core_level, value_tier, domain, use_case, metric_definition, owner, reviewer, reason, updated_at
            from expert_labels
            where asset_type = ? and asset_name = ?
            """,
            (asset_type, asset_name),
        )
        if not row:
            return {"error": "expert_label_not_found", "asset_type": asset_type, "asset_name": asset_name}
        return dict(row)

    def list_core_candidates(self, layer="", limit=100):
        args = []
        filters = ["el.asset_type = 'table'"]
        if layer:
            filters.append("(coalesce(nullif(t.layer, ''), el.domain) = ? or t.layer = ?)")
            args.extend([layer, layer])
        args.append(limit)
        rows = self._all(
            f"""
            select
                el.asset_name as name,
                coalesce(nullif(t.layer, ''), '') as layer,
                coalesce(nullif(t.domain, ''), el.domain) as domain,
                coalesce(nullif(t.owner, ''), el.owner) as owner,
                el.core_level,
                el.value_tier,
                el.use_case,
                el.reviewer,
                el.reason,
                case when t.name is null then 0 else 1 end as table_synced,
                coalesce(c.column_count, 0) as column_count,
                coalesce(q.rule_count, 0) as quality_rule_count,
                coalesce(d.downstream_count, 0) as downstream_count,
                coalesce(u.upstream_count, 0) as upstream_count,
                coalesce(tt.task_count, 0) as task_count,
                coalesce(r.run_count, 0) as run_count,
                coalesce(nullif(t.data_source_id, ''), '') as data_source_id
            from expert_labels el
            left join tables t on t.name = el.asset_name
            left join (select table_name, count(*) as column_count from columns group by table_name) c on c.table_name = el.asset_name
            left join (select table_name, count(*) as rule_count from quality_rules group by table_name) q on q.table_name = el.asset_name
            left join (select upstream, count(*) as downstream_count from lineage group by upstream) d on d.upstream = el.asset_name
            left join (select downstream, count(*) as upstream_count from lineage group by downstream) u on u.downstream = el.asset_name
            left join (select table_name, count(distinct task_id) as task_count from task_tables group by table_name) tt on tt.table_name = el.asset_name
            left join (
                select tt.table_name, count(distinct r.instance_id) as run_count
                from task_tables tt
                join task_runs r on r.task_id = tt.task_id
                where tt.direction = 'output'
                group by tt.table_name
            ) r on r.table_name = el.asset_name
            where {" and ".join(filters)}
            order by
                case el.core_level when 'P0' then 1 when 'P1' then 2 when 'P2' then 3 else 9 end,
                el.asset_name
            limit ?
            """,
            tuple(args),
        )
        results = []
        for row in rows:
            item = dict(row)
            gaps = []
            if not item["table_synced"]:
                gaps.append("表未同步")
            if item["column_count"] == 0:
                gaps.append("缺字段信息")
            if item["upstream_count"] == 0 and item["downstream_count"] == 0:
                gaps.append("缺血缘信息")
            if item["quality_rule_count"] == 0:
                gaps.append("缺质量规则")
            if item["task_count"] == 0:
                gaps.append("缺相关任务")
            if item["run_count"] == 0:
                gaps.append("缺最近运行实例")
            if not item["data_source_id"]:
                gaps.append("缺数据源关联")
            item["gaps"] = gaps
            results.append(item)
        return {"layer": layer, "limit": limit, "results": results}

    def list_expert_review_queue(self, layer="", limit=50):
        args = []
        filters = ["el.asset_name is null", "coalesce(q.rule_count, 0) = 0", "coalesce(l.downstream_count, 0) > 0"]
        if layer:
            filters.append("t.layer = ?")
            args.append(layer)
        args.append(limit)
        rows = self._all(
            f"""
            select
                t.name, t.layer, t.domain, t.owner,
                coalesce(l.downstream_count, 0) as downstream_count,
                coalesce(q.rule_count, 0) as quality_rule_count
            from tables t
            left join expert_labels el on el.asset_type = 'table' and el.asset_name = t.name
            left join (select upstream, count(*) as downstream_count from lineage group by upstream) l on l.upstream = t.name
            left join (select table_name, count(*) as rule_count from quality_rules group by table_name) q on q.table_name = t.name
            where {" and ".join(filters)}
            order by downstream_count desc, t.layer, t.name
            limit ?
            """,
            tuple(args),
        )
        return {"layer": layer, "results": [dict(row) for row in rows]}

    def upsert_task_run(self, item):
        self.conn.execute(
            """
            insert into task_runs (task_id, instance_id, instance_date, start_time, end_time, duration_seconds, status)
            values (?, ?, ?, ?, ?, ?, ?)
            on conflict(task_id, instance_id) do update set
                instance_date = excluded.instance_date,
                start_time = excluded.start_time,
                end_time = excluded.end_time,
                duration_seconds = excluded.duration_seconds,
                status = excluded.status
            """,
            (
                item["task_id"],
                item["instance_id"],
                item.get("instance_date", ""),
                item.get("start_time", ""),
                item.get("end_time", ""),
                int(item.get("duration_seconds") or 0),
                item.get("status", ""),
            ),
        )
        self.conn.commit()

    def get_task(self, task_id):
        task = self._one("select * from tasks where id = ?", (task_id,))
        if not task:
            return {"error": "task_not_found", "task_id": task_id}
        data = dict(task)
        data["inputs"] = [row["table_name"] for row in self._all("select table_name from task_tables where task_id = ? and direction = 'input' order by table_name", (task_id,))]
        data["outputs"] = [row["table_name"] for row in self._all("select table_name from task_tables where task_id = ? and direction = 'output' order by table_name", (task_id,))]
        return data

    def get_task_runs(self, task_id, limit=10, instance_date=""):
        date_filter = "and instance_date like ?" if instance_date else ""
        args = [task_id]
        if instance_date:
            args.append(f"{instance_date}%")
        args.append(limit)
        rows = self._all(
            f"""
            select task_id, instance_id, instance_date, start_time, end_time, duration_seconds, status
            from task_runs
            where task_id = ?
            {date_filter}
            order by instance_date desc, start_time desc
            limit ?
            """,
            tuple(args),
        )
        return {"task_id": task_id, "runs": [dict(row) for row in rows]}

    def get_task_runs_by_name(self, task_name, limit=10, instance_date=""):
        task = self._one("select id, name from tasks where name = ? order by id limit 1", (task_name,))
        if not task:
            return {"error": "task_not_found", "task_name": task_name}
        data = self.get_task_runs(task["id"], limit, instance_date)
        data["task_name"] = task["name"]
        return data

    def get_table_tasks(self, table_name):
        rows = self._all(
            """
            select t.id, t.name, t.task_type, t.cycle, t.schedule_time, t.schedule_desc, t.owner, t.status, tt.direction
            from task_tables tt
            join tasks t on t.id = tt.task_id
            where tt.table_name = ?
            order by tt.direction, t.name
            """,
            (table_name,),
        )
        return {"table_name": table_name, "tasks": [dict(row) for row in rows]}

    def search_tasks(self, query):
        like = f"%{query}%"
        rows = self._all(
            """
            select id, name, task_type, cycle, schedule_time, schedule_desc, owner, status
            from tasks
            where id like ? or name like ? or owner like ? or status like ?
            order by name
            limit 20
            """,
            (like, like, like, like),
        )
        return {"query": query, "results": [self.get_task(row["id"]) for row in rows]}

    def get_table_profile(self, table_name):
        table = self._one("select * from tables where name = ?", (table_name,))
        if not table:
            return {"error": "table_not_found", "table_name": table_name}
        table_data = self._table_dict(table)
        rules = self._all("select * from quality_rules where table_name = ? order by rule_name", (table_name,))
        data_source = self.get_data_source(table_data["data_source_id"]) if table_data.get("data_source_id") else None
        return {
            "table": table_data,
            "data_source": None if data_source and data_source.get("error") else data_source,
            "expert_label": self._label_or_none("table", table_name),
            "columns": [dict(row) for row in self._all("select name, type, description from columns where table_name = ? order by ordinal, name", (table_name,))],
            "lineage": self.get_table_lineage(table_name),
            "quality": {
                "rule_count": len(rules),
                "latest_status": self._latest_status(rules),
                "rules": [dict(row) for row in rules],
            },
            "tasks": self.get_table_tasks(table_name)["tasks"],
            "core": self.is_core_table(table_name),
            "latest_runs": self._latest_output_task_runs(table_name),
            "gaps": self._table_profile_gaps(table_name, table_data, rules),
        }

    def get_table_partition_profile(self, table_name, partition_date=""):
        if not self._one("select 1 from tables where name = ?", (table_name,)):
            return {"error": "table_not_found", "table_name": table_name}
        all_rows = [dict(row) for row in self._all("select * from table_partitions where table_name = ? order by partition_date desc, partition_name desc", (table_name,))]
        recent = all_rows[:30]
        target = None
        if partition_date:
            target = next((row for row in all_rows if row.get("partition_date") == partition_date or partition_date in row.get("partition_name", "")), None)
        elif all_rows:
            target = all_rows[0]
        status = _partition_health_status(target, recent, partition_date)
        return {
            "table_name": table_name,
            "partition_date": partition_date,
            "is_partitioned": bool(all_rows),
            "partition_count": len(all_rows),
            "latest_partition": all_rows[0] if all_rows else None,
            "earliest_partition": all_rows[-1] if all_rows else None,
            "target_partition": target,
            "recent_partitions": recent,
            "total_rows": sum(row.get("row_count") or 0 for row in all_rows),
            "total_storage_bytes": sum(row.get("storage_bytes") or 0 for row in all_rows),
            "health_status": status,
            "health_label": _partition_health_label(status),
            "reasons": _partition_health_reasons(status, target, recent, partition_date),
            "suggestions": _partition_health_suggestions(status),
        }

    def get_table_readiness(self, table_name):
        profile = self.get_table_profile(table_name)
        if profile.get("error"):
            return profile
        checks = _table_readiness_checks(profile)
        scored = [check for check in checks if check.get("scored", True)]
        points = sum(_readiness_points(check["status"]) for check in scored)
        score = round(points / len(scored) * 100) if scored else 0
        status = "通过" if score >= 80 else "部分通过" if score >= 50 else "未通过"
        return {
            "table_name": table_name,
            "status": status,
            "score": score,
            "summary": {
                "layer": profile["table"].get("layer", ""),
                "domain": profile["table"].get("domain", ""),
                "owner": profile["table"].get("owner", ""),
                "core_level": profile["core"].get("core_level", ""),
                "value_tier": profile["core"].get("value_tier", ""),
                "confidence": profile["core"].get("confidence", ""),
            },
            "checks": checks,
            "related_tasks": _table_readiness_tasks(profile.get("tasks", [])),
            "task_runs": self._table_task_run_summaries(table_name),
            "gaps": profile.get("gaps", []),
            "next_actions": _table_readiness_actions(profile.get("gaps", [])),
            "profile": profile,
        }

    def get_table_production_status(self, table_name, instance_date=""):
        if not self._one("select 1 from tables where name = ?", (table_name,)):
            return {"error": "table_not_found", "table_name": table_name}
        tasks = self._all(
            """
            select t.id, t.name, t.task_type, t.cycle, t.schedule_time, t.schedule_desc, t.owner, t.status
            from task_tables tt
            join tasks t on t.id = tt.task_id
            where tt.table_name = ? and tt.direction = 'output'
            order by t.name
            """,
            (table_name,),
        )
        task_items = [_production_task_status(dict(task), instance_date, self._task_runs_for_status(task["id"], instance_date)) for task in tasks]
        status = _production_overall_status(task_items)
        return {
            "table_name": table_name,
            "instance_date": instance_date,
            "status": status,
            "status_label": _production_status_label(status),
            "producer_task_count": len(task_items),
            "tasks": task_items,
            "reasons": _production_reasons(task_items, status),
            "suggestions": _production_suggestions(task_items, status),
        }

    def get_table_production_risk_detail(self, table_name, instance_date=""):
        profile = self.get_table_profile(table_name)
        if profile.get("error"):
            return profile
        production = self.get_table_production_status(table_name, instance_date)
        lineage = profile.get("lineage") or {}
        impact = {
            "upstream_count": len(lineage.get("upstream") or []),
            "downstream_count": len(lineage.get("downstream") or []),
            "downstream": (lineage.get("downstream") or [])[:10],
        }
        return {
            "table_name": table_name,
            "instance_date": instance_date,
            "table": profile.get("table") or {},
            "core": profile.get("core") or {},
            "quality": profile.get("quality") or {},
            "production": production,
            "status": production.get("status", "unknown"),
            "status_label": production.get("status_label") or _production_status_label(production.get("status", "unknown")),
            "impact": impact,
            "reasons": production.get("reasons", []),
            "suggestions": _production_risk_detail_suggestions(profile, production),
            "diagnosis": _production_risk_diagnosis(profile, production),
        }

    def get_asset_owner_profile(self, table_name):
        profile = self.get_table_profile(table_name)
        if profile.get("error"):
            return profile
        table = profile.get("table") or {}
        data_source = profile.get("data_source") or {}
        expert = profile.get("expert_label") or {}
        tasks = profile.get("tasks") or []
        producer_task_owners = _dedupe(task.get("owner") for task in tasks if task.get("direction") == "output")
        consumer_task_owners = _dedupe(task.get("owner") for task in tasks if task.get("direction") == "input")
        downstream_names = [row.get("downstream") for row in (profile.get("lineage") or {}).get("downstream", []) if row.get("downstream")]
        downstream_owners = self._table_owner_rows(downstream_names)
        owners = {
            "table_owner": table.get("owner", ""),
            "expert_owner": expert.get("owner", ""),
            "expert_reviewer": expert.get("reviewer", ""),
            "data_source_owner": data_source.get("owner", ""),
            "producer_task_owners": producer_task_owners,
            "consumer_task_owners": consumer_task_owners,
            "downstream_owners": downstream_owners,
        }
        owner_candidates = _dedupe([owners["expert_owner"], owners["table_owner"], *producer_task_owners, owners["data_source_owner"]])
        gaps = _owner_profile_gaps(owners)
        return {
            "table_name": table_name,
            **owners,
            "owner_candidates": owner_candidates,
            "gaps": gaps,
            "suggestions": _owner_profile_suggestions(gaps, owner_candidates),
        }

    def get_asset_usage_profile(self, table_name):
        profile = self.get_table_profile(table_name)
        if profile.get("error"):
            return profile
        lineage = profile.get("lineage") or {}
        quality = profile.get("quality") or {}
        task_counts = self._task_dependency_counts(table_name)
        latest_run_count = len(profile.get("latest_runs") or [])
        expert = profile.get("expert_label") or {}
        counts = {
            "downstream_count": len(lineage.get("downstream") or []),
            "consumer_task_count": task_counts.get("consumer_task_count", 0),
            "producer_task_count": task_counts.get("producer_task_count", 0),
            "quality_rule_count": quality.get("rule_count", 0),
            "latest_run_count": latest_run_count,
        }
        signals = _usage_signals(counts, expert)
        gaps = ["缺真实查询日志"]
        if not signals:
            gaps.append("缺使用证据")
        usage_level = _usage_level(counts, expert)
        return {
            "table_name": table_name,
            "usage_source": "metadata_proxy",
            **counts,
            "expert_use_case": expert.get("use_case", ""),
            "usage_level": usage_level,
            "signals": signals,
            "gaps": gaps,
            "suggestions": _usage_profile_suggestions(usage_level, gaps),
        }

    def get_asset_lifecycle_profile(self, table_name):
        profile = self.get_table_profile(table_name)
        if profile.get("error"):
            return profile
        lineage = profile.get("lineage") or {}
        quality = profile.get("quality") or {}
        latest_runs = profile.get("latest_runs") or []
        task_counts = self._task_dependency_counts(table_name)
        data_source_id = (profile.get("table") or {}).get("data_source_id", "")
        data_source_task_create_time = self._max_data_source_task_create_time(data_source_id) if data_source_id else ""
        latest_quality_check = _max_non_empty(rule.get("last_checked_at") for rule in quality.get("rules", []))
        latest_run_time = _max_non_empty([run.get("end_time") or run.get("start_time") or run.get("instance_date") for run in latest_runs])
        expert = profile.get("expert_label") or {}
        context = {
            "latest_run_time": latest_run_time,
            "latest_quality_check": latest_quality_check,
            "expert_updated_at": expert.get("updated_at", ""),
            "data_source_task_create_time": data_source_task_create_time,
            "producer_task_count": task_counts.get("producer_task_count", 0),
            "consumer_task_count": task_counts.get("consumer_task_count", 0),
            "downstream_count": len(lineage.get("downstream") or []),
            "gaps": profile.get("gaps") or [],
        }
        status = _lifecycle_status(context)
        return {
            "table_name": table_name,
            "lifecycle_status": status,
            **context,
            "evidence": _lifecycle_evidence(context),
            "suggestions": _lifecycle_suggestions(status, context["gaps"]),
        }

    def get_asset_change_impact(self, table_name, change_type="logic_change"):
        profile = self.get_table_profile(table_name)
        if profile.get("error"):
            return profile
        lineage = profile.get("lineage") or {}
        direct_downstream = lineage.get("downstream") or []
        direct_names = [row.get("downstream") for row in direct_downstream if row.get("downstream")]
        indirect_downstream = []
        if direct_names:
            rows = self._all(
                f"""
                select upstream, downstream, via
                from lineage
                where upstream in ({','.join(['?'] * len(direct_names))})
                  and downstream != ?
                order by upstream, downstream
                limit 20
                """,
                tuple([*direct_names, table_name]),
            )
            indirect_downstream = [dict(row) for row in rows]
        affected_tasks = self.get_table_tasks(table_name).get("tasks", [])
        affected_core_assets = []
        for name in direct_names[:20]:
            core = self.is_core_table(name)
            if not core.get("error") and core.get("core_level") in {"P0", "P1"}:
                affected_core_assets.append({"name": name, "core_level": core.get("core_level"), "value_tier": core.get("value_tier")})
        core = profile.get("core") or {}
        risk_level = _change_risk_level(change_type, core, len(direct_downstream), len(indirect_downstream), len(affected_tasks))
        return {
            "table_name": table_name,
            "change_type": change_type or "logic_change",
            "risk_level": risk_level,
            "direct_downstream": direct_downstream,
            "indirect_downstream": indirect_downstream,
            "affected_tasks": affected_tasks,
            "affected_core_assets": affected_core_assets,
            "checks": _change_checks(change_type),
            "suggestions": _change_suggestions(change_type, risk_level),
        }

    def list_table_production_risks(self, layer="", core_level="", instance_date="", status="", limit=50):
        candidates = self._production_risk_candidates(layer, max(limit * 4, 200))
        results = []
        for table in candidates:
            core = self.is_core_table(table["name"])
            if core_level and core.get("core_level") != core_level:
                continue
            production = self.get_table_production_status(table["name"], instance_date)
            production_status = production.get("status", "unknown")
            if status and production_status != status:
                continue
            if production_status == "success":
                continue
            item = _production_risk_item(table, core, production)
            results.append(item)
            if len(results) >= limit:
                break
        return {
            "layer": layer,
            "core_level": core_level,
            "instance_date": instance_date,
            "status": status,
            "limit": limit,
            "results": results,
        }

    def _production_risk_candidates(self, layer="", limit=200):
        args = []
        layer_filter = ""
        if layer:
            layer_filter = "where t.layer = ?"
            args.append(layer)
        args.append(limit)
        rows = self._all(
            f"""
            select
                t.name, t.layer, t.domain, t.owner,
                coalesce(d.downstream_count, 0) as downstream_count,
                coalesce(u.upstream_count, 0) as upstream_count,
                coalesce(q.rule_count, 0) as quality_rule_count,
                coalesce(tt.task_count, 0) as task_count,
                coalesce(pt.producer_task_count, 0) as producer_task_count
            from tables t
            left join (select upstream, count(*) as downstream_count from lineage group by upstream) d on d.upstream = t.name
            left join (select downstream, count(*) as upstream_count from lineage group by downstream) u on u.downstream = t.name
            left join (select table_name, count(*) as rule_count from quality_rules group by table_name) q on q.table_name = t.name
            left join (select table_name, count(distinct task_id) as task_count from task_tables group by table_name) tt on tt.table_name = t.name
            left join (select table_name, count(distinct task_id) as producer_task_count from task_tables where direction = 'output' group by table_name) pt on pt.table_name = t.name
            {layer_filter}
            order by
                case t.layer when 'ads' then 1 when 'dws' then 2 when 'dwd' then 3 when 'dim' then 4 when 'ods' then 5 else 9 end,
                producer_task_count desc,
                downstream_count desc,
                t.name
            limit ?
            """,
            tuple(args),
        )
        return [dict(row) for row in rows]

    def _governance_report_candidates(self, layer="", limit=100):
        args = []
        layer_filter = ""
        if layer:
            layer_filter = "where t.layer = ?"
            args.append(layer)
        args.append(limit)
        rows = self._all(
            f"""
            select
                t.name, t.layer, t.domain, t.owner,
                coalesce(d.downstream_count, 0) as downstream_count,
                coalesce(tt.task_count, 0) as task_count,
                coalesce(pt.producer_task_count, 0) as producer_task_count
            from tables t
            left join (select upstream, count(*) as downstream_count from lineage group by upstream) d on d.upstream = t.name
            left join (select table_name, count(distinct task_id) as task_count from task_tables group by table_name) tt on tt.table_name = t.name
            left join (select table_name, count(distinct task_id) as producer_task_count from task_tables where direction = 'output' group by table_name) pt on pt.table_name = t.name
            {layer_filter}
            order by
                case t.layer when 'ads' then 1 when 'dws' then 2 when 'dwd' then 3 when 'dim' then 4 when 'ods' then 5 else 9 end,
                downstream_count desc,
                task_count desc,
                producer_task_count desc,
                t.name
            limit ?
            """,
            tuple(args),
        )
        return [dict(row) for row in rows]

    def get_asset_value_profile(self, table_name):
        table = self._one("select * from tables where name = ?", (table_name,))
        if not table:
            return {"error": "table_not_found", "table_name": table_name}
        table = dict(table)
        label = self._label_or_none("table", table_name)
        downstream_count = self._one("select count(*) as n from lineage where upstream = ?", (table_name,))["n"]
        upstream_count = self._one("select count(*) as n from lineage where downstream = ?", (table_name,))["n"]
        rule_count = self._one("select count(*) as n from quality_rules where table_name = ?", (table_name,))["n"]
        latest_runs = self._latest_output_task_runs(table_name)
        failed_runs = [run for run in latest_runs if _is_bad_run_status(run.get("status", ""))]
        task_counts = self._task_dependency_counts(table_name)
        gaps = self._table_profile_gaps(table_name, self._table_dict(self._one("select * from tables where name = ?", (table_name,))), self._all("select * from quality_rules where table_name = ?", (table_name,)))

        machine_dimensions = _asset_value_dimensions(table, downstream_count, rule_count, failed_runs, task_counts, latest_runs)
        machine_score = sum(machine_dimensions.values())
        machine_core_level = _core_level_from_score(machine_score)
        machine_value_tier = _value_tier_from_score(machine_score)
        machine = {
            "score": machine_score,
            "core_level": machine_core_level,
            "value_tier": machine_value_tier,
            "is_core": machine_core_level in {"P0", "P1"},
            "dimensions": machine_dimensions,
            "evidence": _asset_value_evidence(table, downstream_count, upstream_count, rule_count, failed_runs, task_counts, latest_runs),
            "task_dependency": task_counts,
        }
        manual = _manual_decision(label)
        final = _final_asset_decision(machine, manual)
        confidence = _asset_decision_confidence(gaps, label, machine_score)
        review_suggestion = _asset_review_suggestion(machine, manual, gaps)

        return {
            "table_name": table_name,
            "value_tier": final["value_tier"],
            "core_level": final["core_level"],
            "is_core": final["is_core"],
            "score": final["score"],
            "source": final["source"],
            "dimensions": machine_dimensions,
            "evidence": machine["evidence"],
            "expert_label": label,
            "machine": machine,
            "manual": manual,
            "final": final,
            "confidence": confidence,
            "gaps": gaps,
            "review_suggestion": review_suggestion,
        }

    def get_metric_definition(self, table_name):
        table = self._one("select * from tables where name = ?", (table_name,))
        if not table:
            return {"error": "table_not_found", "table_name": table_name}
        table = self._table_dict(table)
        columns = [dict(row) for row in self._all("select name, type, description from columns where table_name = ? order by ordinal, name", (table_name,))]
        lineage = self.get_table_lineage(table_name)
        role = _metric_role(table)
        fields = _metric_fields(columns)
        grain = fields["time_fields"] + fields["dimension_fields"]
        return {
            "table": table,
            "role": role,
            "subject": _metric_subject(table_name),
            "time_grain": _metric_time_grain(table_name),
            "summary": _metric_summary(table, fields["metric_fields"]),
            "statistical_grain": grain,
            **fields,
            "upstream_dws": [row for row in lineage["upstream"] if self._is_layer_table(row["upstream"], "dws")],
            "upstream_sources": [row for row in lineage["upstream"] if not self._is_layer_table(row["upstream"], "dws")],
            "downstream_ads": [row for row in lineage["downstream"] if self._is_layer_table(row["downstream"], "ads")],
            "tasks": self.get_table_tasks(table_name)["tasks"],
            "explanation": _metric_explanation(role),
            "expert_label": self._label_or_none("table", table_name),
        }

    def get_table_risk_profile(self, table_name):
        profile = self.get_table_profile(table_name)
        if profile.get("error"):
            return profile
        table = profile["table"]
        downstream_count = len(profile["lineage"]["downstream"])
        rule_count = profile["quality"]["rule_count"]
        latest_runs = self._latest_output_task_runs(table_name)
        failed_runs = [run for run in latest_runs if _is_bad_run_status(run.get("status", ""))]
        reasons = []
        if table["layer"].lower() in {"ods", "dwd", "dws", "ads"}:
            reasons.append(f"{table['layer']} layer")
        if downstream_count >= 5:
            reasons.append(f"{downstream_count} downstream assets")
        if rule_count == 0:
            reasons.append("missing quality rules")
        if failed_runs:
            reasons.append(f"{len(failed_runs)} latest task runs abnormal")

        level = "低"
        if failed_runs or (rule_count == 0 and downstream_count >= 5 and table["layer"].lower() in {"dwd", "dws", "ads"}):
            level = "高"
        elif rule_count == 0 or downstream_count:
            level = "中"
        return {
            "table_name": table_name,
            "risk_level": level,
            "layer": table["layer"],
            "downstream_count": downstream_count,
            "quality_rule_count": rule_count,
            "latest_runs": latest_runs,
            "reasons": reasons,
            "suggestions": _risk_suggestions(rule_count, downstream_count, failed_runs),
            "expert_label": self._label_or_none("table", table_name),
        }

    def list_quality_gaps(self, layer="", domain="", limit=50):
        args = []
        filters = ["coalesce(q.rule_count, 0) = 0", "coalesce(l.downstream_count, 0) > 0"]
        if layer:
            filters.append("t.layer = ?")
            args.append(layer)
        if domain:
            filters.append("t.domain = ?")
            args.append(domain)
        args.append(limit)
        rows = self._all(
            f"""
            select
                t.name, t.layer, t.domain, t.owner,
                coalesce(l.downstream_count, 0) as downstream_count,
                coalesce(q.rule_count, 0) as quality_rule_count
            from tables t
            left join (select upstream, count(*) as downstream_count from lineage group by upstream) l on l.upstream = t.name
            left join (select table_name, count(*) as rule_count from quality_rules group by table_name) q on q.table_name = t.name
            where {" and ".join(filters)}
            order by downstream_count desc, t.layer, t.name
            limit ?
            """,
            tuple(args),
        )
        return {"layer": layer, "domain": domain, "results": [dict(row) for row in rows]}

    def list_table_columns(self, table_name):
        if not self._one("select 1 from tables where name = ?", (table_name,)):
            return {"error": "table_not_found", "table_name": table_name}
        return {"table_name": table_name, "columns": [dict(row) for row in self._all("select name, type, description from columns where table_name = ? order by ordinal, name", (table_name,))]}

    def get_quality_status(self, table_name):
        rules = self._all("select * from quality_rules where table_name = ? order by rule_name", (table_name,))
        return {
            "table_name": table_name,
            "has_quality_monitoring": bool(rules),
            "rule_count": len(rules),
            "latest_status": self._latest_status(rules),
            "rules": [dict(row) for row in rules],
        }

    def get_table_lineage(self, table_name):
        upstream = self._all("select upstream, via from lineage where downstream = ? order by upstream", (table_name,))
        downstream = self._all("select downstream, via from lineage where upstream = ? order by downstream", (table_name,))
        return {
            "upstream": [dict(row) for row in upstream],
            "downstream": [dict(row) for row in downstream],
        }

    def search_assets(self, query):
        like = f"%{query}%"
        rows = self._all(
            """
            select name, source_guid, data_source_id, database_name, layer, domain, owner, description
            from tables
            where name like ? or description like ? or domain like ?
            order by name
            limit 20
            """,
            (like, like, like),
        )
        return {"query": query, "results": [self._table_dict(row) for row in rows]}

    def is_core_table(self, table_name):
        value = self.get_asset_value_profile(table_name)
        if value.get("error"):
            return value
        return {
            "table_name": table_name,
            "is_core": value["is_core"],
            "score": value["score"],
            "reasons": value["evidence"],
            "core_level": value["core_level"],
            "value_tier": value["value_tier"],
            "source": value["source"],
            "machine": value.get("machine"),
            "manual": value.get("manual"),
            "final": value.get("final"),
            "confidence": value.get("confidence"),
            "gaps": value.get("gaps", []),
            "review_suggestion": value.get("review_suggestion", ""),
        }

    def _one(self, sql, args=()):
        return self.conn.execute(sql, args).fetchone()

    def _all(self, sql, args=()):
        return self.conn.execute(sql, args).fetchall()

    def _count(self, table_name):
        return self._one(f"select count(*) as n from {table_name}")["n"]

    def _max_text(self, table_name, column_name):
        return self._one(f"select max(nullif({column_name}, '')) as value from {table_name}")["value"] or ""

    def _add_column_if_missing(self, table_name, column_name, definition):
        columns = {row["name"] for row in self.conn.execute(f"pragma table_info({table_name})")}
        if column_name not in columns:
            self.conn.execute(f"alter table {table_name} add column {column_name} {definition}")

    def _table_dict(self, row):
        data = dict(row)
        data["database"] = data.pop("database_name")
        return data

    def _data_source_dict(self, row):
        data = dict(row)
        data["config"] = json.loads(data.pop("config_json") or "{}")
        data["owner_name"] = _owner_name(data["owner"])
        data["task_count"] = self._data_source_task_count(data["id"])
        return data

    def _data_source_task_count(self, data_source_id):
        direct = self._one("select count(distinct task_id) as n from data_source_tasks where data_source_id = ?", (data_source_id,))
        if direct and direct["n"]:
            return direct["n"]
        row = self._one(
            """
            select count(distinct tt.task_id) as n
            from task_tables tt
            join tables t on t.name = tt.table_name
            where t.data_source_id = ?
            """,
            (data_source_id,),
        )
        return row["n"] if row else 0

    def _max_data_source_task_create_time(self, data_source_id):
        row = self._one("select max(nullif(create_time, '')) as value from data_source_tasks where data_source_id = ?", (data_source_id,))
        return row["value"] if row and row["value"] else ""

    def _table_owner_rows(self, table_names):
        if not table_names:
            return []
        placeholders = ",".join(["?"] * len(table_names))
        return [dict(row) for row in self._all(f"select name, owner from tables where name in ({placeholders}) order by name", tuple(table_names))]

    def _latest_output_task_runs(self, table_name):
        rows = self._all(
            """
            select t.id as task_id, t.name as task_name, r.instance_date, r.start_time, r.end_time, r.duration_seconds, r.status
            from task_tables tt
            join tasks t on t.id = tt.task_id
            left join task_runs r on r.task_id = t.id
            where tt.table_name = ? and tt.direction = 'output'
            order by r.instance_date desc, r.start_time desc
            limit 5
            """,
            (table_name,),
        )
        return [dict(row) for row in rows if row["instance_date"]]

    def _table_task_run_summaries(self, table_name):
        rows = self._all(
            """
            select
                t.id as task_id,
                t.name as task_name,
                t.owner,
                t.cycle,
                t.schedule_time,
                t.schedule_desc,
                tt.direction,
                r.instance_id,
                r.instance_date,
                r.start_time,
                r.end_time,
                r.duration_seconds,
                r.status
            from task_tables tt
            join tasks t on t.id = tt.task_id
            left join task_runs r on r.task_id = t.id
            where tt.table_name = ?
              and (r.instance_id is null or r.instance_id = (
                  select r2.instance_id
                  from task_runs r2
                  where r2.task_id = t.id
                  order by r2.instance_date desc, r2.start_time desc
                  limit 1
              ))
            order by tt.direction, t.name
            """,
            (table_name,),
        )
        return [_task_run_summary(dict(row)) for row in rows]

    def _task_runs_for_status(self, task_id, instance_date=""):
        date_filter = "and instance_date like ?" if instance_date else ""
        args = [task_id]
        if instance_date:
            args.append(f"{instance_date}%")
        rows = self._all(
            f"""
            select task_id, instance_id, instance_date, start_time, end_time, duration_seconds, status
            from task_runs
            where task_id = ?
            {date_filter}
            order by instance_date desc, start_time desc
            limit 1
            """,
            tuple(args),
        )
        return [dict(row) for row in rows]

    def _task_dependency_counts(self, table_name):
        producer = self._one("select count(distinct task_id) as n from task_tables where table_name = ? and direction = 'output'", (table_name,))["n"]
        consumer = self._one("select count(distinct task_id) as n from task_tables where table_name = ? and direction = 'input'", (table_name,))["n"]
        total = self._one("select count(distinct task_id) as n from task_tables where table_name = ?", (table_name,))["n"]
        return {"producer_task_count": producer, "consumer_task_count": consumer, "total_task_count": total}

    def _label_or_none(self, asset_type, asset_name):
        label = self.get_expert_label(asset_type, asset_name)
        return None if label.get("error") else label

    def _is_layer_table(self, table_name, layer):
        if table_name.lower().startswith(f"{layer}_"):
            return True
        row = self._one("select layer from tables where name = ?", (table_name,))
        return bool(row and (row["layer"] or "").lower() == layer)

    def _latest_status(self, rules):
        failed = [rule for rule in rules if rule["last_status"] == "failed"]
        if failed:
            return "failed"
        return rules[0]["last_status"] if rules else "missing"

    def _table_profile_gaps(self, table_name, table, rules):
        gaps = []
        if not self._one("select 1 from columns where table_name = ? limit 1", (table_name,)):
            gaps.append("缺字段信息")
        if not self._one("select 1 from lineage where upstream = ? or downstream = ? limit 1", (table_name, table_name)):
            gaps.append("缺血缘信息")
        if not rules:
            gaps.append("缺质量规则")
        if not self._one("select 1 from task_tables where table_name = ? limit 1", (table_name,)):
            gaps.append("缺相关任务")
        if not self._latest_output_task_runs(table_name):
            gaps.append("缺最近运行实例")
        if not table.get("data_source_id"):
            gaps.append("缺数据源关联")
        return gaps


def _readiness_points(status):
    return {"通过": 1, "部分通过": 0.5, "缺失": 0}.get(status, 0)


def _table_readiness_tasks(tasks):
    return [
        {
            "task_id": task.get("id", ""),
            "task_name": task.get("name", ""),
            "direction": task.get("direction", ""),
            "owner": task.get("owner", ""),
            "cycle": task.get("cycle", ""),
            "schedule_time": task.get("schedule_time") or task.get("cycle", ""),
            "schedule_desc": task.get("schedule_desc", ""),
            "status": task.get("status", ""),
        }
        for task in tasks
    ]


def _task_run_summary(row):
    return {
        "task_id": row.get("task_id", ""),
        "task_name": row.get("task_name", ""),
        "direction": row.get("direction", ""),
        "owner": row.get("owner", ""),
        "cycle": row.get("cycle", ""),
        "schedule_time": row.get("schedule_time") or row.get("cycle", ""),
        "schedule_desc": row.get("schedule_desc", ""),
        "instance_id": row.get("instance_id", ""),
        "instance_date": row.get("instance_date", ""),
        "execution_status": row.get("status") or "未执行",
        "start_time": row.get("start_time", ""),
        "end_time": row.get("end_time", ""),
        "duration_seconds": row.get("duration_seconds") or 0,
    }


def _production_task_status(task, instance_date, runs):
    latest_run = runs[0] if runs else None
    raw_status = latest_run.get("status", "") if latest_run else ""
    return {
        "task_id": task.get("id", ""),
        "task_name": task.get("name", ""),
        "owner": task.get("owner", ""),
        "cycle": task.get("cycle", ""),
        "schedule_time": task.get("schedule_time") or task.get("cycle", ""),
        "schedule_desc": task.get("schedule_desc", ""),
        "task_status": task.get("status", ""),
        "latest_run": {
            "instance_id": latest_run.get("instance_id", "") if latest_run else "",
            "instance_date": latest_run.get("instance_date", instance_date) if latest_run else instance_date,
            "raw_status": raw_status,
            "status": _normalize_run_status(raw_status) if latest_run else "not_run",
            "status_label": _production_status_label(_normalize_run_status(raw_status) if latest_run else "not_run"),
            "start_time": latest_run.get("start_time", "") if latest_run else "",
            "end_time": latest_run.get("end_time", "") if latest_run else "",
            "duration_seconds": latest_run.get("duration_seconds", 0) if latest_run else 0,
        },
    }


def _partition_health_status(target, recent, requested_date):
    if not recent:
        return "unknown"
    if requested_date and not target:
        return "missing_partition"
    if not target:
        return "unknown"
    if int(target.get("row_count") or 0) == 0:
        return "empty_partition"
    average = _partition_recent_average(target, recent)
    if average and target.get("row_count", 0) < average * 0.5:
        return "row_count_drop"
    if average and target.get("row_count", 0) > average * 2:
        return "row_count_spike"
    return "normal"


def _partition_recent_average(target, recent):
    values = [int(row.get("row_count") or 0) for row in recent if row.get("partition_name") != (target or {}).get("partition_name") and int(row.get("row_count") or 0) > 0]
    return sum(values) / len(values) if values else 0


def _partition_health_label(status):
    return {
        "normal": "正常",
        "missing_partition": "缺目标分区",
        "empty_partition": "空分区",
        "row_count_drop": "行数突降",
        "row_count_spike": "行数暴涨",
        "unknown": "未知",
    }.get(status, status or "未知")


def _partition_health_reasons(status, target, recent, requested_date):
    if status == "unknown":
        return ["未找到分区统计事实，无法判断分区健康。"]
    if status == "missing_partition":
        return [f"未找到目标分区：{requested_date}。"]
    reasons = [f"目标分区：{target.get('partition_name')}，行数：{target.get('row_count', 0)}。"]
    average = _partition_recent_average(target, recent)
    if average:
        reasons.append(f"最近非目标分区平均行数：{average:.0f}。")
    if status == "empty_partition":
        reasons.append("目标分区行数为 0。")
    elif status == "row_count_drop":
        reasons.append("目标分区行数低于近期平均的 50%。")
    elif status == "row_count_spike":
        reasons.append("目标分区行数高于近期平均的 200%。")
    else:
        reasons.append("目标分区存在且行数在近期范围内。")
    return reasons


def _partition_health_suggestions(status):
    return {
        "normal": ["分区数据量正常，可结合产出状态和质量规则继续观察。"],
        "missing_partition": ["检查产出任务是否写入目标分区，并确认调度日期参数是否正确。"],
        "empty_partition": ["检查上游是否为空、过滤条件是否异常，或产出任务是否只创建了空分区。"],
        "row_count_drop": ["对比近 7 天输入数据和 SQL 条件，确认是否存在上游缺数或过滤条件异常。"],
        "row_count_spike": ["检查是否重复写入、笛卡尔积、去重失效或上游数据异常放大。"],
        "unknown": ["同步分区统计元数据后再判断，避免直接对大表执行实时 count(*)。"],
    }.get(status, ["补充分区统计事实后复核。"])


def _normalize_run_status(status):
    value = (status or "").lower()
    if value in {"", "none"}:
        return "not_run"
    if value in {"success", "succeed", "succeeded", "passed", "completed", "complete", "y", "y11", "ok"}:
        return "success"
    if value in {"fail", "failed", "failure", "error", "exception", "terminated", "timeout"}:
        return "failed"
    if value in {"running", "executing", "waiting", "queued", "pending", "created", "ready"}:
        return "running"
    return "unknown"


def _production_overall_status(tasks):
    if not tasks:
        return "not_run"
    statuses = [task.get("latest_run", {}).get("status", "not_run") for task in tasks]
    if any(status == "failed" for status in statuses):
        return "failed"
    if any(status == "running" for status in statuses):
        return "running"
    if statuses and all(status == "success" for status in statuses):
        return "success"
    if any(status == "success" for status in statuses):
        return "partial_success"
    if all(status == "not_run" for status in statuses):
        return "not_run"
    return "unknown"


def _production_status_label(status):
    return {
        "success": "成功",
        "failed": "失败",
        "running": "执行中",
        "not_run": "未执行",
        "partial_success": "部分成功",
        "unknown": "未知",
    }.get(status, status or "未知")


def _production_reasons(tasks, status):
    if not tasks:
        return ["未找到产出任务"]
    reasons = [f"{len(tasks)} 个产出任务", f"汇总状态：{_production_status_label(status)}"]
    for task in tasks:
        run = task.get("latest_run", {})
        if run.get("raw_status"):
            reasons.append(f"任务 {task.get('task_name')} 最近实例状态 {run.get('raw_status')}")
        else:
            reasons.append(f"任务 {task.get('task_name')} 没有匹配的运行实例")
        if task.get("owner"):
            reasons.append(f"任务负责人 {task.get('owner')}")
    return reasons


def _production_suggestions(tasks, status):
    if not tasks:
        return ["检查 `ListTasks` inputs/outputs 或 SQL 解析是否识别该表的产出任务。"]
    suggestions = []
    if status == "failed":
        suggestions.append("优先联系产出任务负责人排查失败实例，并确认下游影响范围。")
    if status == "running":
        suggestions.append("任务仍在执行中，关注是否超过预期调度耗时。")
    if status == "not_run":
        suggestions.append("找到产出任务但没有匹配运行实例，扩大实例同步窗口或确认 `WEDATA_INSTANCE_KEYWORDS` 命中任务。")
    if status == "unknown":
        suggestions.append("存在未知 WeData 实例状态，保留原始状态并补充状态映射。")
    return suggestions


def _production_risk_item(table, core, production):
    status = production.get("status", "unknown")
    return {
        "name": table.get("name", ""),
        "layer": table.get("layer", ""),
        "domain": table.get("domain", ""),
        "owner": table.get("owner", ""),
        "core_level": core.get("core_level", ""),
        "value_tier": core.get("value_tier", ""),
        "is_core": core.get("is_core", False),
        "score": core.get("score", 0),
        "status": status,
        "status_label": production.get("status_label") or _production_status_label(status),
        "producer_task_count": production.get("producer_task_count", 0),
        "downstream_count": table.get("downstream_count", 0),
        "quality_rule_count": table.get("quality_rule_count", 0),
        "reasons": production.get("reasons", []),
        "suggestions": production.get("suggestions", []),
        "tasks": production.get("tasks", []),
    }


def _production_risk_diagnosis(profile, production):
    table = profile.get("table") or {}
    core = profile.get("core") or {}
    lineage = profile.get("lineage") or {}
    tasks = production.get("tasks") or []
    status = production.get("status", "unknown")
    diagnosis = []
    if not tasks:
        diagnosis.append("未找到产出任务，无法确认该表由哪个 WeData 任务产出。")
    elif status == "not_run":
        diagnosis.append("找到产出任务但没有匹配运行实例。")
    elif status == "failed":
        diagnosis.append("存在失败实例，优先联系产出任务负责人。")
    elif status == "running":
        diagnosis.append("产出任务仍在执行中，需关注是否超过预期调度耗时。")
    elif status == "partial_success":
        diagnosis.append("部分产出任务成功，仍需确认未成功任务是否影响最终表产出。")
    elif status == "unknown":
        diagnosis.append("存在未知实例状态，需补充 WeData 状态映射后再判断。")
    else:
        diagnosis.append("产出状态正常，可结合下游影响继续观察。")
    if lineage.get("downstream"):
        diagnosis.append("该表存在下游依赖，需评估影响范围。")
    if core.get("core_level") in {"P0", "P1"} or (table.get("layer") or "").lower() in {"ads", "dws"}:
        diagnosis.append("该表为核心等级或 ADS/DWS 关键层资产，建议提升处理优先级。")
    return diagnosis


def _production_risk_detail_suggestions(profile, production):
    table = profile.get("table") or {}
    core = profile.get("core") or {}
    lineage = profile.get("lineage") or {}
    tasks = production.get("tasks") or []
    suggestions = list(production.get("suggestions") or [])
    if tasks:
        suggestions.append("先查看产出任务实例，确认失败原因或实例是否漏同步。")
    else:
        suggestions.append("如无产出任务，补齐 task_tables 产出关系或检查 ListTasks inputs/outputs 解析。")
    if lineage.get("downstream"):
        suggestions.append("同步/核对下游依赖 Owner，避免风险传递到看板或应用层。")
    if core.get("core_level") in {"P0", "P1"} or (table.get("layer") or "").lower() in {"ads", "dws"}:
        suggestions.append("优先纳入当天监控跟进清单，并确认告警接收人与 SLA。")
    return list(dict.fromkeys(suggestions))


def _dedupe(values):
    result = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _max_non_empty(values):
    values = [value for value in values if value]
    return max(values) if values else ""


def _owner_profile_gaps(owners):
    gaps = []
    if not owners.get("table_owner"):
        gaps.append("缺表Owner")
    if not owners.get("producer_task_owners"):
        gaps.append("缺产出任务Owner")
    if not owners.get("data_source_owner"):
        gaps.append("缺数据源Owner")
    primary = _dedupe([owners.get("table_owner"), *owners.get("producer_task_owners", []), owners.get("data_source_owner")])
    if len(primary) > 1:
        gaps.append("Owner不一致")
    return gaps


def _owner_profile_suggestions(gaps, owner_candidates):
    suggestions = []
    if "缺表Owner" in gaps:
        suggestions.append("补齐表资产 Owner，作为治理责任主入口。")
    if "缺产出任务Owner" in gaps:
        suggestions.append("补齐产出任务 Owner，确保产出问题可定位到处理人。")
    if "缺数据源Owner" in gaps:
        suggestions.append("补齐数据源 Owner，便于源端变更或同步异常时协同排查。")
    if "Owner不一致" in gaps:
        suggestions.append("核对表、产出任务和数据源 Owner 是否需要统一或明确分工。")
    if owner_candidates:
        suggestions.append(f"建议优先联系：{owner_candidates[0]}。")
    return suggestions or ["责任链路较完整，可进入 SLA、质量和变更流程治理。"]


def _usage_signals(counts, expert):
    signals = []
    if counts.get("downstream_count", 0):
        signals.append(f"存在 {counts.get('downstream_count')} 个下游血缘依赖。")
    if counts.get("consumer_task_count", 0):
        signals.append(f"存在 {counts.get('consumer_task_count')} 个消费任务。")
    if counts.get("producer_task_count", 0):
        signals.append(f"存在 {counts.get('producer_task_count')} 个产出任务。")
    if counts.get("quality_rule_count", 0):
        signals.append(f"配置了 {counts.get('quality_rule_count')} 条质量规则。")
    if counts.get("latest_run_count", 0):
        signals.append(f"最近有 {counts.get('latest_run_count')} 条产出运行实例。")
    if expert.get("use_case"):
        signals.append(f"专家标注使用场景：{expert.get('use_case')}。")
    return signals


def _usage_level(counts, expert):
    if counts.get("downstream_count", 0) >= 5 or counts.get("consumer_task_count", 0) >= 5 or expert.get("use_case"):
        return "高"
    if counts.get("downstream_count", 0) or counts.get("consumer_task_count", 0) or counts.get("latest_run_count", 0):
        return "中"
    if counts.get("producer_task_count", 0) or counts.get("quality_rule_count", 0):
        return "低"
    return "未知"


def _usage_profile_suggestions(usage_level, gaps):
    suggestions = ["接入 BI、网关或查询日志后，可将当前 metadata_proxy 升级为真实使用热度。"]
    if usage_level == "高":
        suggestions.append("将该资产纳入重点保障清单，优先补齐 SLA、质量规则和 Owner。")
    elif usage_level in {"低", "未知"}:
        suggestions.append("结合业务 Owner 复核使用价值，判断是否需要沉淀场景或进入下线观察。")
    if "缺真实查询日志" in gaps:
        suggestions.append("当前使用画像不包含真实查询次数、访问用户数和最近访问时间。")
    return suggestions


def _lifecycle_status(context):
    gaps = set(context.get("gaps") or [])
    if {"缺字段信息", "缺相关任务"} & gaps:
        return "新建/待补齐"
    if context.get("latest_run_time") or context.get("downstream_count", 0) or context.get("consumer_task_count", 0):
        return "活跃"
    if not context.get("downstream_count", 0) and not context.get("consumer_task_count", 0) and not context.get("latest_run_time"):
        return "疑似废弃"
    if gaps:
        return "待治理"
    return "稳定"


def _lifecycle_evidence(context):
    evidence = []
    if context.get("latest_run_time"):
        evidence.append(f"最近产出时间：{context.get('latest_run_time')}。")
    if context.get("latest_quality_check"):
        evidence.append(f"最近质量检查：{context.get('latest_quality_check')}。")
    if context.get("expert_updated_at"):
        evidence.append(f"专家标注更新时间：{context.get('expert_updated_at')}。")
    if context.get("data_source_task_create_time"):
        evidence.append(f"数据源关联任务创建时间：{context.get('data_source_task_create_time')}。")
    evidence.append(f"产出任务 {context.get('producer_task_count', 0)} 个，消费任务 {context.get('consumer_task_count', 0)} 个，下游 {context.get('downstream_count', 0)} 个。")
    return evidence


def _lifecycle_suggestions(status, gaps):
    suggestions = []
    if status == "新建/待补齐":
        suggestions.append("优先补齐字段、任务、血缘、质量规则等基础画像。")
    if status == "疑似废弃":
        suggestions.append("与 Owner 确认是否仍有业务使用，必要时进入下线观察。")
    if status == "活跃":
        suggestions.append("保持产出、质量和 Owner 监控，纳入日常资产巡检。")
    if gaps:
        suggestions.append("按当前缺口逐项补齐治理证据：" + "、".join(gaps))
    return suggestions or ["生命周期状态稳定，建议定期复核使用场景和下游依赖。"]


def _change_risk_level(change_type, core, direct_count, indirect_count, affected_task_count):
    if core.get("core_level") in {"P0", "P1"} or (change_type in {"offline", "schema_change"} and direct_count):
        return "高"
    if direct_count >= 5 or indirect_count >= 10 or affected_task_count >= 5:
        return "高"
    if direct_count or indirect_count or affected_task_count:
        return "中"
    return "低"


def _change_checks(change_type):
    checks = ["确认变更窗口、回滚方案和通知范围。", "核对直接下游和关键任务依赖。"]
    if change_type == "schema_change":
        checks.append("逐字段确认新增、删除、改名、类型变更对下游 SQL 的影响。")
    elif change_type == "delay":
        checks.append("确认 SLA 延迟是否影响下游报表或应用刷新。")
    elif change_type == "offline":
        checks.append("确认所有下游已迁移或停止使用，并保留下线审批记录。")
    else:
        checks.append("确认口径逻辑变更是否影响指标解释和历史对比。")
    return checks


def _change_suggestions(change_type, risk_level):
    suggestions = []
    if risk_level == "高":
        suggestions.append("建议发起正式变更评审，并要求核心下游 Owner 确认。")
    elif risk_level == "中":
        suggestions.append("建议通知直接下游 Owner，并在变更后观察产出与质量结果。")
    else:
        suggestions.append("影响面较小，仍建议记录变更原因和回滚方式。")
    if change_type == "schema_change":
        suggestions.append("变更前后对比字段清单，并补充兼容期或别名字段。")
    elif change_type == "offline":
        suggestions.append("下线前保留只读观察期，确认无新增访问或任务依赖。")
    elif change_type == "delay":
        suggestions.append("同步调整 SLA 告警阈值，并通知依赖方刷新时间变化。")
    return suggestions


def _governance_status_counts(production_risks):
    counts = {"failed": 0, "not_run": 0, "running": 0, "unknown": 0, "partial_success": 0}
    for item in production_risks:
        status = item.get("status", "unknown")
        counts[status] = counts.get(status, 0) + 1
    return counts


def _governance_issues_for_table(table):
    issues = []
    if table.get("layer") in ("", "unknown"):
        issues.append(_governance_issue(table, "unknown_layer", "manual_mapping_needed", "Inspect raw ListTable fields and table naming rules for layer inference."))
    if int(table.get("quality_rule_count") or 0) == 0:
        issues.append(_governance_issue(table, "missing_quality_rules", "source_governance_gap", "Compare raw quality rules with DB rules for this table."))
    if int(table.get("task_count") or 0) == 0:
        issues.append(_governance_issue(table, "missing_task_mapping", "parser_gap", "Check raw task inputs/outputs and SQL table-name normalization."))
    elif int(table.get("run_count") or 0) == 0:
        issues.append(_governance_issue(table, "missing_task_runs", "instance_window_gap", "Check ListTaskInstances time window, max pages, and task_id alignment."))
    if not table.get("data_source_id"):
        issues.append(_governance_issue(table, "missing_data_source", "source_metadata_gap", "Check ListTable data source fields and data source sync coverage."))
    if not table.get("owner"):
        issues.append(_governance_issue(table, "missing_owner", "owner_governance_gap", "Ask table owner or warehouse owner to confirm responsibility."))
    if _profile_incomplete(table):
        issues.append(_governance_issue(table, "profile_incomplete", "profile_coverage_gap", "Prioritize missing profile facts by issue inventory entries."))
    return issues


def _governance_issue_counts(issues, key):
    counts = {}
    for issue in issues:
        value = issue.get(key) or "unknown"
        counts[value] = counts.get(value, 0) + 1
    return counts


def _governance_responsibility_buckets(issues):
    buckets = {
        "data_platform": [],
        "warehouse_owner": [],
        "bi_owner": [],
        "business_owner": [],
        "unknown_owner": [],
    }
    for issue in issues:
        bucket = _governance_responsibility_bucket(issue)
        if len(buckets[bucket]) < 20:
            buckets[bucket].append(issue)
    return buckets


def _governance_responsibility_bucket(issue):
    if issue.get("owner") == "unknown owner":
        return "unknown_owner"
    if issue.get("issue_type") in {"partition_unsupported", "missing_task_runs"}:
        return "data_platform"
    if issue.get("issue_type") in {"missing_quality_rules", "missing_task_mapping", "unknown_layer", "missing_owner"}:
        return "warehouse_owner"
    if issue.get("issue_type") == "missing_data_source":
        return "data_platform"
    return "business_owner"


def _governance_issue(table, issue_type, root_cause, next_check):
    evidence = {
        "layer": table.get("layer", ""),
        "core_level": table.get("core_level", ""),
        "column_count": int(table.get("column_count") or 0),
        "quality_rule_count": int(table.get("quality_rule_count") or 0),
        "downstream_count": int(table.get("downstream_count") or 0),
        "task_count": int(table.get("task_count") or 0),
        "run_count": int(table.get("run_count") or 0),
        "data_source_id": table.get("data_source_id", ""),
    }
    return {
        "issue_type": issue_type,
        "asset_type": "table",
        "asset_name": table.get("name", ""),
        "layer": table.get("layer", ""),
        "owner": table.get("owner") or "unknown owner",
        "severity": _governance_issue_severity(table, issue_type),
        "evidence": evidence,
        "suspected_root_cause": root_cause,
        "recommended_next_check": next_check,
    }


def _governance_issue_severity(table, issue_type):
    if table.get("core_level") in {"P0", "P1"}:
        return "P0"
    if issue_type in {"missing_task_runs", "missing_task_mapping"} and table.get("layer") in {"ads", "dws", "dwd"}:
        return "P1"
    if int(table.get("downstream_count") or 0) >= 1:
        return "P1"
    return "P2"


def _profile_incomplete(table):
    return any(
        int(table.get(key) or 0) == 0
        for key in ("column_count", "quality_rule_count", "task_count")
    ) or not table.get("data_source_id") or not table.get("owner") or table.get("layer") in {"", "unknown"}


def _governance_owner_gap_item(table, owner_profile):
    return {
        "name": table.get("name", ""),
        "layer": table.get("layer", ""),
        "owner": table.get("owner", ""),
        "owner_candidates": owner_profile.get("owner_candidates", []),
        "gaps": owner_profile.get("gaps", []),
    }


def _governance_lifecycle_watch_item(table, lifecycle_profile):
    return {
        "name": table.get("name", ""),
        "layer": table.get("layer", ""),
        "owner": table.get("owner", ""),
        "lifecycle_status": lifecycle_profile.get("lifecycle_status", ""),
        "latest_run_time": lifecycle_profile.get("latest_run_time", ""),
        "gaps": lifecycle_profile.get("gaps", []),
    }


def _governance_top_actions(summary, production_risks, quality_gaps, owner_gaps, lifecycle_watch, expert_queue):
    actions = []
    failed = [item for item in production_risks if item.get("status") == "failed"]
    not_run = [item for item in production_risks if item.get("status") == "not_run"]
    if failed:
        actions.append(f"优先处理 {len(failed)} 张失败产出表：{failed[0].get('name')}。")
    if not_run:
        actions.append(f"排查 {len(not_run)} 张未执行产出表，先确认任务实例是否漏同步：{not_run[0].get('name')}。")
    if quality_gaps:
        actions.append(f"补齐 {len(quality_gaps)} 张质量规则缺口表，优先从 {quality_gaps[0].get('name')} 开始。")
    if owner_gaps:
        actions.append(f"明确 {len(owner_gaps)} 张 Owner 缺口表责任人，优先处理 {owner_gaps[0].get('name')}。")
    if lifecycle_watch:
        actions.append(f"复核 {len(lifecycle_watch)} 张生命周期关注表，确认是否待补齐或疑似废弃。")
    if expert_queue:
        actions.append(f"推进 {len(expert_queue)} 张高影响资产专家评审，优先处理 {expert_queue[0].get('name')}。")
    if not actions:
        actions.append("暂无高优先级治理动作，建议保持同步健康检查和核心资产抽检。")
    return actions


def _table_readiness_checks(profile):
    table = profile.get("table", {})
    lineage = profile.get("lineage", {})
    quality = profile.get("quality", {})
    core = profile.get("core", {})
    checks = []
    basics = [table.get("layer"), table.get("domain"), table.get("owner"), table.get("description")]
    checks.append(_readiness_check("基础信息", "通过" if sum(1 for item in basics if item) >= 3 else "部分通过" if any(basics) else "缺失", f"层级={table.get('layer', '')}, 领域={table.get('domain', '')}, Owner={table.get('owner', '')}"))
    checks.append(_readiness_check("字段", "通过" if profile.get("columns") else "缺失", f"字段数={len(profile.get('columns', []))}"))
    upstream_count = len(lineage.get("upstream", []))
    downstream_count = len(lineage.get("downstream", []))
    checks.append(_readiness_check("血缘", "通过" if upstream_count and downstream_count else "部分通过" if upstream_count or downstream_count else "缺失", f"上游={upstream_count}, 下游={downstream_count}"))
    checks.append(_readiness_check("质量规则", "通过" if quality.get("rule_count", 0) else "缺失", f"规则数={quality.get('rule_count', 0)}, 最新状态={quality.get('latest_status', '')}"))
    checks.append(_readiness_check("任务", "通过" if profile.get("tasks") else "缺失", f"任务数={len(profile.get('tasks', []))}"))
    checks.append(_readiness_check("运行实例", "通过" if profile.get("latest_runs") else "缺失", f"最近实例数={len(profile.get('latest_runs', []))}"))
    source = profile.get("data_source") or {}
    checks.append(_readiness_check("数据源", "通过" if source else "缺失", f"数据源={source.get('name') or table.get('data_source_id') or ''}"))
    checks.append(_readiness_check("核心/价值判断", "通过" if core.get("final") or core.get("machine") else "部分通过" if core else "缺失", f"等级={core.get('core_level', '')}, 分层={core.get('value_tier', '')}, 置信度={core.get('confidence', '')}"))
    expert = profile.get("expert_label") or {}
    checks.append(_readiness_check("人工标注", "通过" if expert and not expert.get("error") else "缺失", f"Reviewer={expert.get('reviewer', '')}, 原因={expert.get('reason', '')}", scored=False))
    return checks


def _readiness_check(name, status, evidence, scored=True):
    return {"name": name, "status": status, "evidence": evidence, "scored": scored}


def _table_readiness_actions(gaps):
    actions = {
        "缺字段信息": "开启 `WEDATA_SYNC_METADATA=1`，检查 `ListTable` 是否返回 GUID 以及 `GetTableColumns` 权限。",
        "缺血缘信息": "检查 `ListLineage` 权限和表 GUID，必要时确认 WeData 是否维护血缘。",
        "缺质量规则": "与数仓/治理 Owner 确认是否需要补充分区产出、主键/非空、金额/数量合理性等质量规则。",
        "缺相关任务": "检查 `ListTasks` 返回的 inputs/outputs 是否包含该表，并核对任务表解析映射。",
        "缺最近运行实例": "扩大 `WEDATA_INSTANCE_LOOKBACK_DAYS` 或设置 `WEDATA_INSTANCE_KEYWORDS` 命中相关任务。",
        "缺数据源关联": "检查 `ListTable` 是否返回 data_source_id，并开启 `WEDATA_SYNC_DATA_SOURCES=1`。",
    }
    return [actions.get(gap, f"补齐：{gap}") for gap in gaps] or ["画像信息较完整，可进入 Owner 核对、质量规则复核和使用场景沉淀。"]



def _is_bad_run_status(status):
    value = (status or "").lower()
    return value not in {"", "success", "succeed", "passed", "y", "y11", "completed"}


def _risk_suggestions(rule_count, downstream_count, failed_runs):
    suggestions = []
    if rule_count == 0:
        suggestions.append("补充分区产出、主键/非空、金额/数量合理性等质量规则")
    if downstream_count >= 5:
        suggestions.append("优先保障下游核心链路，确认依赖表 Owner 和告警接收人")
    if failed_runs:
        suggestions.append("检查最近产出任务失败或异常状态，并补充产出时效监控")
    return suggestions


def _asset_value_dimensions(table, downstream_count, rule_count, failed_runs, task_counts=None, latest_runs=None):
    task_counts = task_counts or {}
    latest_runs = latest_runs or []
    name = table["name"].lower()
    domain = (table["domain"] or "").lower()
    layer = (table["layer"] or "").lower()

    business_signal = 0
    if domain in {"finance", "revenue", "business", "customer", "order"} or _has_business_keyword(name):
        business_signal = 20
    elif domain:
        business_signal = 10

    downstream_lineage = 0
    if downstream_count >= 20:
        downstream_lineage = 30
    elif downstream_count >= 10:
        downstream_lineage = 22
    elif downstream_count >= 5:
        downstream_lineage = 20
    elif downstream_count > 0:
        downstream_lineage = 8

    consumer_count = int(task_counts.get("consumer_task_count") or 0)
    producer_count = int(task_counts.get("producer_task_count") or 0)
    task_dependency = 0
    if consumer_count >= 20:
        task_dependency += 20
    elif consumer_count >= 10:
        task_dependency += 15
    elif consumer_count >= 5:
        task_dependency += 10
    elif consumer_count > 0:
        task_dependency += 5
    if producer_count >= 2:
        task_dependency += 5
    elif producer_count >= 1:
        task_dependency += 3

    layer_position = {"ads": 15, "dws": 15, "dwd": 12, "dim": 10, "ods": 5}.get(layer, 0)
    quality_governance = 10 if rule_count >= 5 else 6 if rule_count else 0
    run_stability = 0
    if latest_runs and not failed_runs:
        run_stability = 10
    elif latest_runs:
        run_stability = 3
    if name.startswith("tmp_") or name.endswith(("_tmp", "_test", "_bak", "_back")):
        business_signal = max(0, business_signal - 10)
        downstream_lineage = min(downstream_lineage, 5)
        layer_position = max(0, layer_position - 10)
    return {
        "downstream_lineage": downstream_lineage,
        "task_dependency": task_dependency,
        "layer_position": layer_position,
        "quality_governance": quality_governance,
        "run_stability": run_stability,
        "business_signal": business_signal,
        "usage_heat": 0,
    }


def _asset_value_evidence(table, downstream_count, upstream_count, rule_count, failed_runs, task_counts=None, latest_runs=None):
    task_counts = task_counts or {}
    latest_runs = latest_runs or []
    evidence = []
    name = table["name"].lower()
    if table["domain"]:
        evidence.append(f"{table['domain']} domain")
    if _has_business_keyword(name):
        evidence.append("business-critical keywords in table name")
    if downstream_count:
        evidence.append(f"{downstream_count} downstream assets")
    if upstream_count:
        evidence.append(f"{upstream_count} upstream assets")
    if task_counts.get("consumer_task_count"):
        evidence.append(f"{task_counts['consumer_task_count']} consuming tasks")
    if task_counts.get("producer_task_count"):
        evidence.append(f"{task_counts['producer_task_count']} producing tasks")
    if table["layer"]:
        evidence.append(f"{table['layer']} layer")
    evidence.append(f"{rule_count} quality rules")
    if latest_runs and not failed_runs:
        evidence.append("latest output task runs succeeded")
    if failed_runs:
        evidence.append(f"{len(failed_runs)} latest task runs abnormal")
    return evidence


def _manual_decision(label):
    if not label:
        return None
    core_level = label.get("core_level") or _core_level_from_value_tier(label.get("value_tier", ""))
    value_tier = label.get("value_tier") or _value_tier_from_core_level(core_level)
    score_adjustment = 0
    if not label.get("core_level") and value_tier:
        if "核心" in value_tier:
            score_adjustment = 20
        elif "重要" in value_tier:
            score_adjustment = 10
        elif "非核心" in value_tier or "普通" in value_tier:
            score_adjustment = -30 if "非核心" in value_tier else 0
    return {
        "core_level": core_level,
        "value_tier": value_tier,
        "is_core": core_level in {"P0", "P1", "核心"} or "核心" in value_tier,
        "score_adjustment": score_adjustment,
        "reviewer": label.get("reviewer", ""),
        "reason": label.get("reason", ""),
        "source": "expert_label",
    }


def _final_asset_decision(machine, manual):
    if manual and (manual.get("core_level") or manual.get("value_tier")):
        if manual.get("core_level"):
            core_level = manual["core_level"]
            value_tier = manual.get("value_tier") or _value_tier_from_core_level(core_level)
            score = max(machine["score"], 100 if core_level in {"P0", "P1"} else machine["score"])
            return {"core_level": core_level, "value_tier": value_tier, "is_core": core_level in {"P0", "P1", "核心"}, "score": score, "source": "manual_override"}
        score = max(0, machine["score"] + manual.get("score_adjustment", 0))
        return {
            "core_level": _core_level_from_score(score),
            "value_tier": manual.get("value_tier") or _value_tier_from_score(score),
            "is_core": score >= 70 or manual.get("is_core", False),
            "score": score,
            "source": "manual_adjusted",
        }
    return {"core_level": machine["core_level"], "value_tier": machine["value_tier"], "is_core": machine["is_core"], "score": machine["score"], "source": "model"}


def _asset_decision_confidence(gaps, label, machine_score):
    critical_gaps = {"缺血缘信息", "缺相关任务", "缺最近运行实例"}
    missing_critical = len(critical_gaps & set(gaps or []))
    if label and label.get("core_level"):
        return "high" if missing_critical <= 1 else "medium"
    if missing_critical >= 2:
        return "low"
    if gaps:
        return "medium"
    return "high" if machine_score >= 50 else "medium"


def _asset_review_suggestion(machine, manual, gaps):
    suggestions = []
    if manual and manual.get("core_level") and abs(_core_rank(manual.get("core_level")) - _core_rank(machine.get("core_level"))) >= 2:
        suggestions.append("人工标注与机器评分差异较大，建议复核血缘、任务依赖和业务使用场景。")
    if not manual and machine.get("score", 0) >= 70:
        suggestions.append("机器判断为核心候选，建议补充人工标注确认 Owner、场景和核心等级。")
    if gaps:
        suggestions.append("当前判断受数据缺口影响：" + "、".join(gaps))
    return " ".join(suggestions) or "当前证据较完整，可按现有判断进入后续资产治理。"


def _core_rank(level):
    return {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "核心": 1}.get(level or "", 4)


def _has_business_keyword(name):
    keywords = {"bill", "cost", "amount", "consume", "revenue", "pay", "refund", "income", "order", "customer", "company"}
    return bool(keywords & set(name.split("_")))


def _metric_role(table):
    name = table["name"].lower()
    layer = (table["layer"] or "").lower()
    if layer == "dws" or name.startswith("dws_"):
        return {"name": "指标统计口径层", "primary_definition": True}
    if layer == "ads" or name.startswith("ads_"):
        return {"name": "指标应用结果层", "primary_definition": False}
    return {"name": "指标上游来源/非指标主表", "primary_definition": False}


def _metric_subject(table_name):
    tokens = [token for token in table_name.split("_") if token not in {"ads", "dws", "di", "df", "1d", "7d", "30d"}]
    return "_".join(tokens) or table_name


def _metric_time_grain(table_name):
    tokens = set(table_name.lower().split("_"))
    for grain in ("1h", "1d", "7d", "30d"):
        if grain in tokens:
            return grain
    return "unknown"


def _metric_fields(columns):
    result = {"time_fields": [], "dimension_fields": [], "metric_fields": [], "description_fields": []}
    for column in columns:
        role = _column_role(column["name"])
        if role == "metric":
            result["metric_fields"].append({**column, "metric_type": _metric_field_type(column["name"])})
        elif role == "time":
            result["time_fields"].append(column)
        elif role == "dimension":
            result["dimension_fields"].append(column)
        elif role == "description":
            result["description_fields"].append(column)
    return result


def _column_role(name):
    name = name.lower()
    if name in {"dt", "date", "stat_date", "bill_date"} or name.endswith(("_date", "_time")):
        return "time"
    if _metric_field_type(name):
        return "metric"
    if name.endswith("_id") or name.endswith("_no") or name in {"id"}:
        return "dimension"
    if name.endswith("_name") or name.endswith("_type") or name.endswith("_mode") or name.endswith("_unit"):
        return "description"
    return ""


def _metric_field_type(name):
    name = name.lower()
    checks = [
        ("数量类", ("num", "cnt", "count", "total", "times", "qty")),
        ("金额类", ("amount", "amt", "cost", "fee", "price", "income", "revenue")),
        ("比率类", ("rate", "ratio", "percent", "pct")),
        ("时长/均值类", ("duration", "seconds", "minutes", "avg")),
        ("状态/结果类", ("success", "fail", "status")),
    ]
    for label, keywords in checks:
        if any(keyword in name for keyword in keywords):
            return label
    return ""


def _metric_explanation(role):
    if role["name"] == "指标统计口径层":
        return "dws 表作为指标统计口径层，字段、上游来源和产出任务共同构成当前可解释口径。"
    if role["name"] == "指标应用结果层":
        return "ads 表作为业务使用的指标结果层，口径优先追溯上游 dws 表；本表更适合解释指标产出结果。"
    return "该表不是 ads/dws 主指标表，可作为指标口径的上游来源参与解释。"


def _metric_summary(table, metric_fields):
    if not metric_fields:
        return "当前已同步字段中未识别到指标字段。"
    metric_types = "、".join(dict.fromkeys(field["metric_type"] for field in metric_fields))
    subject = _metric_subject(table["name"]).replace("_", " ")
    return f"该表按已同步字段推导，主要统计 {subject} 相关的{metric_types}指标。"


def _value_tier_from_score(score):
    if score >= 85:
        return "L0 战略核心资产"
    if score >= 70:
        return "L1 业务核心资产"
    if score >= 50:
        return "L2 重要公共资产"
    if score >= 25:
        return "L3 普通业务资产"
    return "L4 低价值/待治理资产"


def _core_level_from_score(score):
    if score >= 85:
        return "P0"
    if score >= 70:
        return "P1"
    if score >= 50:
        return "P2"
    return "非核心"


def _value_tier_from_core_level(core_level):
    return {"P0": "L0 战略核心资产", "P1": "L1 业务核心资产", "P2": "L2 重要公共资产", "核心": "L0 战略核心资产"}.get(core_level, "")


def _core_level_from_value_tier(value_tier):
    if value_tier.startswith("L0"):
        return "P0"
    if value_tier.startswith("L1"):
        return "P1"
    if value_tier.startswith("L2"):
        return "P2"
    return "非核心"


def _owner_name(owner_id):
    aliases = {"100043939904": "luyuan"}
    for item in os.environ.get("DLC_MCP_USER_ALIASES", "").split(","):
        if ":" in item:
            key, value = item.split(":", 1)
            aliases[key.strip()] = value.strip()
    return aliases.get(str(owner_id), str(owner_id))


def _normalize_gap_type(gap_type):
    aliases = {
        "field": "fields",
        "fields": "fields",
        "column": "fields",
        "columns": "fields",
        "quality": "quality",
        "rule": "quality",
        "rules": "quality",
        "lineage": "lineage",
        "upstream": "upstream",
        "downstream": "downstream",
        "task": "tasks",
        "tasks": "tasks",
        "run": "runs",
        "runs": "runs",
        "instance": "runs",
        "instances": "runs",
        "data_source": "data_source",
        "datasource": "data_source",
        "source": "data_source",
    }
    return aliases.get((gap_type or "").strip().lower(), "")


def _coverage_gaps(row):
    gaps = []
    if int(row.get("column_count") or 0) == 0:
        gaps.append("fields")
    if int(row.get("quality_rule_count") or 0) == 0:
        gaps.append("quality")
    upstream = int(row.get("upstream_count") or 0)
    downstream = int(row.get("downstream_count") or 0)
    if upstream == 0:
        gaps.append("upstream")
    if downstream == 0:
        gaps.append("downstream")
    if upstream + downstream == 0:
        gaps.append("lineage")
    if int(row.get("task_count") or 0) == 0:
        gaps.append("tasks")
    if int(row.get("run_count") or 0) == 0:
        gaps.append("runs")
    if not row.get("data_source_id"):
        gaps.append("data_source")
    return gaps


def _gap_label(gap):
    labels = {
        "fields": "缺字段信息",
        "quality": "缺质量规则",
        "upstream": "缺上游血缘",
        "downstream": "缺下游血缘",
        "lineage": "缺完整血缘",
        "tasks": "缺相关任务",
        "runs": "缺运行实例",
        "data_source": "缺数据源关联",
    }
    return labels.get(gap, gap)
