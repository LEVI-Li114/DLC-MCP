import argparse
import json
import os
import sqlite3
from datetime import date, timedelta

from .assets import AssetStore
from .live import LiveWeData
from .patrol import PatrolService


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Run DLC MCP asset patrol")
    parser.add_argument("--scope", default="daily_p0", choices=["daily_p0"], help="Patrol scope to run")
    parser.add_argument("--instance-date", default=_default_instance_date(), help="Instance date in YYYY-MM-DD format")
    parser.add_argument("--limit", type=int, default=50, help="Maximum assets to check")
    parser.add_argument("--db", default=os.environ.get("DLC_MCP_DB", "/data/dlc-mcp/assets.db"), help="SQLite asset DB path")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    conn = sqlite3.connect(args.db)
    store = AssetStore(conn)
    store.init_schema()
    live = LiveWeData(store)
    service = PatrolService(store, live)
    if args.scope == "daily_p0":
        result = service.run_daily_p0(args.instance_date, limit=args.limit)
    else:
        raise SystemExit(f"unsupported scope: {args.scope}")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _default_instance_date():
    return (date.today() - timedelta(days=1)).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
