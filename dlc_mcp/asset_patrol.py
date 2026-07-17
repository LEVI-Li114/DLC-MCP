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
    parser.add_argument("--concurrency", type=int, default=3, help="Number of tables to check concurrently")
    parser.add_argument("--table-timeout-seconds", type=float, default=120, help="Maximum seconds for one table check")
    parser.add_argument("--retry", type=int, default=2, help="Retry attempts for retryable table checks")
    parser.add_argument("--retry-backoff-seconds", type=float, default=2, help="Base retry backoff in seconds")
    parser.add_argument("--api-delay-seconds", type=float, default=0.2, help="Delay before each live table check")
    parser.add_argument("--failure-threshold", type=float, default=0.3, help="Failure ratio above which the run is failed")
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
        result = service.run_daily_p0(
            args.instance_date,
            limit=args.limit,
            concurrency=args.concurrency,
            table_timeout_seconds=args.table_timeout_seconds,
            retry=args.retry,
            retry_backoff_seconds=args.retry_backoff_seconds,
            api_delay_seconds=args.api_delay_seconds,
            failure_threshold=args.failure_threshold,
        )
    else:
        raise SystemExit(f"unsupported scope: {args.scope}")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _default_instance_date():
    return (date.today() - timedelta(days=1)).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
