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
    parser.add_argument(
        "--scope",
        default="daily_p0",
        choices=["daily_p0", "daily_core", "monthly_full", "manual"],
        help="Patrol scope to run",
    )
    parser.add_argument("--instance-date", default=_default_instance_date(), help="Instance date in YYYY-MM-DD format")
    parser.add_argument("--limit", type=int, default=50, help="Maximum assets to check")
    parser.add_argument("--batch-size", type=int, default=0, help="Maximum assets per batch for full patrols")
    parser.add_argument("--offset", type=int, default=0, help="Offset into the selected patrol scope")
    parser.add_argument("--table", default="", help="Single table name for manual patrol")
    parser.add_argument("--layer", default="", help="Layer filter for manual or full patrol")
    parser.add_argument("--owner", default="", help="Owner filter for manual or full patrol")
    parser.add_argument("--core-level", default="", help="Core level filter for core/manual patrol")
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
    result = service.run(
        args.scope,
        args.instance_date,
        limit=args.limit,
        batch_size=args.batch_size,
        offset=args.offset,
        table=args.table,
        layer=args.layer,
        owner=args.owner,
        core_level=args.core_level,
        concurrency=args.concurrency,
        table_timeout_seconds=args.table_timeout_seconds,
        retry=args.retry,
        retry_backoff_seconds=args.retry_backoff_seconds,
        api_delay_seconds=args.api_delay_seconds,
        failure_threshold=args.failure_threshold,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _default_instance_date():
    return (date.today() - timedelta(days=1)).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
