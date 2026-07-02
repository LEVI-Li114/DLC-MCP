import sqlite3
import json


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
            """
        )
        self._add_column_if_missing("tables", "source_guid", "text not null default ''")
        self.conn.commit()

    def upsert_table(self, item):
        self.conn.execute(
            """
            insert into tables (name, source_guid, database_name, layer, domain, owner, description, manual_core_level)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(name) do update set
                source_guid = coalesce(nullif(excluded.source_guid, ''), tables.source_guid),
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

    def list_data_sources(self, query=""):
        like = f"%{query}%"
        rows = self._all(
            """
            select id, name, type, owner, description, config_json
            from data_sources
            where ? = '' or id like ? or name like ? or type like ? or owner like ?
            order by name
            limit 50
            """,
            (query, like, like, like, like),
        )
        return {"query": query, "results": [self._data_source_dict(row) for row in rows]}

    def get_data_source(self, data_source_id):
        row = self._one("select id, name, type, owner, description, config_json from data_sources where id = ?", (data_source_id,))
        if not row:
            return {"error": "data_source_not_found", "data_source_id": data_source_id}
        return self._data_source_dict(row)

    def list_metadata(self):
        databases = [row["database_name"] for row in self._all("select distinct database_name from tables where database_name != '' order by database_name")]
        tables = [self._table_dict(row) for row in self._all("select name, source_guid, database_name, layer, domain, owner, description, manual_core_level from tables order by database_name, name limit 100")]
        return {"databases": databases, "tables": tables}

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
        rules = self._all("select * from quality_rules where table_name = ? order by rule_name", (table_name,))
        return {
            "table": self._table_dict(table),
            "columns": [dict(row) for row in self._all("select name, type, description from columns where table_name = ? order by ordinal, name", (table_name,))],
            "lineage": self.get_table_lineage(table_name),
            "quality": {
                "rule_count": len(rules),
                "latest_status": self._latest_status(rules),
                "rules": [dict(row) for row in rules],
            },
            "tasks": self.get_table_tasks(table_name)["tasks"],
            "core": self.is_core_table(table_name),
        }

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
            select name, source_guid, database_name, layer, domain, owner, description
            from tables
            where name like ? or description like ? or domain like ?
            order by name
            limit 20
            """,
            (like, like, like),
        )
        return {"query": query, "results": [self._table_dict(row) for row in rows]}

    def is_core_table(self, table_name):
        table = self._one("select * from tables where name = ?", (table_name,))
        if not table:
            return {"error": "table_not_found", "table_name": table_name}
        if table["manual_core_level"]:
            return {"table_name": table_name, "is_core": True, "score": 100, "reasons": [f"manual core level: {table['manual_core_level']}"]}

        score = 0
        reasons = []
        if table["layer"].lower() in {"dws", "ads"}:
            score += 30
            reasons.append(f"{table['layer']} layer")
        if table["domain"].lower() in {"finance", "business", "customer", "order", "revenue"}:
            score += 25
            reasons.append(f"{table['domain']} domain")
        downstream_count = self._one("select count(*) as n from lineage where upstream = ?", (table_name,))["n"]
        if downstream_count:
            score += min(25, downstream_count * 10)
            reasons.append(f"{downstream_count} downstream assets")
        rule_count = self._one("select count(*) as n from quality_rules where table_name = ?", (table_name,))["n"]
        if rule_count:
            score += 20
            reasons.append("has quality rules")
        return {"table_name": table_name, "is_core": score >= 60, "score": score, "reasons": reasons}

    def _one(self, sql, args=()):
        return self.conn.execute(sql, args).fetchone()

    def _all(self, sql, args=()):
        return self.conn.execute(sql, args).fetchall()

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
        return data

    def _latest_status(self, rules):
        failed = [rule for rule in rules if rule["last_status"] == "failed"]
        if failed:
            return "failed"
        return rules[0]["last_status"] if rules else "missing"
