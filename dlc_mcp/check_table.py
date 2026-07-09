import argparse
import os
import sqlite3

from .assets import AssetStore
from .mcp import _format_markdown
from .server import _load_env_file


def main():
    parser = argparse.ArgumentParser(description="Print a readable table asset governance readiness report.")
    parser.add_argument("table_name")
    parser.add_argument("--db", default="", help="SQLite asset database path. Defaults to DLC_MCP_DB or data/assets.db.")
    parser.add_argument("--env-file", default=os.environ.get("DLC_MCP_ENV_FILE", "/etc/dlc-mcp/env"), help="Optional env file to load before checking.")
    args = parser.parse_args()

    if args.env_file and os.path.exists(args.env_file):
        _load_env_file(args.env_file)
    db_path = args.db or os.environ.get("DLC_MCP_DB", "data/assets.db")
    store = AssetStore(sqlite3.connect(db_path))
    store.init_schema()
    print(render_table_readiness(store, args.table_name))


def render_table_readiness(store, table_name):
    data = store.get_table_readiness(table_name)
    return _format_markdown("get_table_readiness", data)


if __name__ == "__main__":
    main()
