import argparse
import json
import os
import sqlite3



def main():
    args = _parse_args()
    if args.env_file and os.path.exists(args.env_file):
        from .server import _load_env_file

        _load_env_file(args.env_file)
    db_path = args.db or os.environ.get("DLC_MCP_DB", "data/assets.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    if args.task_name_pseudo:
        result = cleanup_task_name_pseudo_tables(conn, args.data_source_id, args.apply)
    else:
        result = cleanup_derived_tables(conn, apply=args.apply)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


def cleanup_derived_tables(conn, apply=False):
    names = [
        row["name"]
        for row in conn.execute(
            """
            select name
            from tables
            where source_guid = ''
              and database_name = ''
              and description like 'Derived from WeData task%'
            order by name
            """
        )
    ]
    return _delete_table_assets(conn, names, apply, "candidate_tables")


def cleanup_task_name_pseudo_tables(conn, data_source_id="", apply=False):
    filter_sql = "and t.data_source_id = ?" if data_source_id else ""
    params = (data_source_id,) if data_source_id else ()
    names = [
        row["name"]
        for row in conn.execute(
            f"""
            select t.name
            from tables t
            where coalesce(t.source_guid, '') = ''
              and coalesce(t.database_name, '') = ''
              {filter_sql}
              and not exists (select 1 from columns c where c.table_name = t.name)
              and not exists (select 1 from task_tables tt where tt.table_name = t.name)
              and exists (select 1 from tasks task where task.name = t.name)
            order by t.name
            """,
            params,
        )
    ]
    result = _delete_table_assets(conn, names, apply, "candidate_tables")
    result["data_source_id"] = data_source_id
    result["candidate_names"] = names[:100]
    return result


def _delete_table_assets(conn, names, apply, candidate_key):
    counts = {candidate_key: len(names), "apply": bool(apply)}
    if not names or not apply:
        return counts

    placeholders = ",".join(["?"] * len(names))
    targets = [
        ("columns", f"table_name in ({placeholders})", names),
        ("task_tables", f"table_name in ({placeholders})", names),
        ("lineage", f"upstream in ({placeholders}) or downstream in ({placeholders})", names + names),
        ("quality_rules", f"table_name in ({placeholders})", names),
        ("table_partitions", f"table_name in ({placeholders})", names),
        ("expert_labels", f"asset_type = 'table' and asset_name in ({placeholders})", names),
        ("asset_edges", f"(source_type = 'table' and source_id in ({placeholders})) or (target_type = 'table' and target_id in ({placeholders}))", names + names),
        ("tables", f"name in ({placeholders})", names),
    ]
    with conn:
        for table, where, params in targets:
            if not _table_exists(conn, table):
                counts[f"deleted_{table}"] = 0
                continue
            cur = conn.execute(f"delete from {table} where {where}", params)
            counts[f"deleted_{table}"] = cur.rowcount
    return counts


def _table_exists(conn, table_name):
    return bool(conn.execute("select 1 from sqlite_master where type = 'table' and name = ?", (table_name,)).fetchone())


def _parse_args():
    parser = argparse.ArgumentParser(description="Remove old table assets derived only from WeData task names.")
    parser.add_argument("--env-file", default=os.environ.get("DLC_MCP_ENV_FILE", "/etc/dlc-mcp/env"))
    parser.add_argument("--db", default="")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--task-name-pseudo", action="store_true", help="Clean pseudo tables whose name equals a WeData task name, optionally limited to one data source.")
    parser.add_argument("--data-source-id", default="", help="Only used with --task-name-pseudo.")
    return parser.parse_args()


if __name__ == "__main__":
    main()
