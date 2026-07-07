import sqlite3
import json
import os


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
            insert into tasks (id, name, task_type, cycle, owner, status)
            values (?, ?, ?, ?, ?, ?)
            on conflict(id) do update set
                name = excluded.name,
                task_type = excluded.task_type,
                cycle = excluded.cycle,
                owner = excluded.owner,
                status = excluded.status
            """,
            (
                item["id"],
                item.get("name", ""),
                item.get("task_type", ""),
                item.get("cycle", ""),
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
            select t.id, t.name, t.task_type, t.cycle, t.owner, t.status, tt.direction
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
            select id, name, task_type, cycle, owner, status
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

    def get_asset_value_profile(self, table_name):
        table = self._one("select * from tables where name = ?", (table_name,))
        if not table:
            return {"error": "table_not_found", "table_name": table_name}
        label = self._label_or_none("table", table_name)
        downstream_count = self._one("select count(*) as n from lineage where upstream = ?", (table_name,))["n"]
        rule_count = self._one("select count(*) as n from quality_rules where table_name = ?", (table_name,))["n"]
        latest_runs = self._latest_output_task_runs(table_name)
        failed_runs = [run for run in latest_runs if _is_bad_run_status(run.get("status", ""))]

        if label and (label.get("value_tier") or label.get("core_level")):
            value_tier = label.get("value_tier") or _value_tier_from_core_level(label.get("core_level", ""))
            core_level = label.get("core_level") or _core_level_from_value_tier(value_tier)
            return {
                "table_name": table_name,
                "value_tier": value_tier,
                "core_level": core_level,
                "is_core": core_level in {"P0", "P1", "核心"},
                "score": 100,
                "source": "expert",
                "dimensions": {"expert_override": 100},
                "evidence": [f"expert label: {core_level or value_tier}", label.get("reason", "")],
                "expert_label": label,
            }

        dimensions = _asset_value_dimensions(dict(table), downstream_count, rule_count, failed_runs)
        score = sum(dimensions.values())
        value_tier = _value_tier_from_score(score)
        core_level = _core_level_from_score(score)
        return {
            "table_name": table_name,
            "value_tier": value_tier,
            "core_level": core_level,
            "is_core": core_level in {"P0", "P1"},
            "score": score,
            "source": "model",
            "dimensions": dimensions,
            "evidence": _asset_value_evidence(dict(table), downstream_count, rule_count, failed_runs),
            "expert_label": None,
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
        return {"table_name": table_name, "is_core": value["is_core"], "score": value["score"], "reasons": value["evidence"], "core_level": value["core_level"], "value_tier": value["value_tier"]}

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


def _asset_value_dimensions(table, downstream_count, rule_count, failed_runs):
    name = table["name"].lower()
    domain = (table["domain"] or "").lower()
    layer = (table["layer"] or "").lower()
    business_value = 0
    if domain in {"finance", "revenue", "business", "customer", "order"} or _has_business_keyword(name):
        business_value = 30
    elif domain:
        business_value = 15

    lineage_impact = 0
    if downstream_count >= 10:
        lineage_impact = 25
    elif downstream_count >= 5:
        lineage_impact = 15
    elif downstream_count > 0:
        lineage_impact = 8

    layer_position = {"dwd": 15, "dws": 15, "ads": 15, "dim": 10, "ods": 5}.get(layer, 0)
    governance = 10 if rule_count else 0
    stability = 0 if failed_runs else 5
    if name.startswith("tmp_") or name.endswith(("_tmp", "_test", "_bak", "_back")):
        business_value -= 30
        lineage_impact = min(lineage_impact, 5)
    return {
        "business_value": max(0, business_value),
        "lineage_impact": lineage_impact,
        "layer_position": layer_position,
        "governance_readiness": governance,
        "run_stability": stability,
        "usage_heat": 0,
    }


def _asset_value_evidence(table, downstream_count, rule_count, failed_runs):
    evidence = []
    name = table["name"].lower()
    if table["domain"]:
        evidence.append(f"{table['domain']} domain")
    if _has_business_keyword(name):
        evidence.append("business-critical keywords in table name")
    if downstream_count:
        evidence.append(f"{downstream_count} downstream assets")
    if table["layer"]:
        evidence.append(f"{table['layer']} layer")
    evidence.append(f"{rule_count} quality rules")
    if failed_runs:
        evidence.append(f"{len(failed_runs)} latest task runs abnormal")
    return evidence


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
