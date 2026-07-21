import argparse
import json
import os
import sqlite3

from .assets import AssetStore


def main():
    args = _parse_args()
    if args.env_file and os.path.exists(args.env_file):
        from .server import _load_env_file

        _load_env_file(args.env_file)
    db_path = args.db or os.environ.get("DLC_MCP_DB", "data/assets.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    store = AssetStore(conn)
    result = store.reconcile_task_tables_from_lineage(limit=args.limit, apply=args.apply, table=args.table)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


def _parse_args():
    parser = argparse.ArgumentParser(description="Derive missing task-table mappings from lineage rows whose via value is a WeData task id.")
    parser.add_argument("--env-file", default=os.environ.get("DLC_MCP_ENV_FILE", "/etc/dlc-mcp/env"))
    parser.add_argument("--db", default="")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--table", default="")
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    main()
