import argparse
import json
import os
import sqlite3
import time
from datetime import datetime

from .assets import AssetStore
from .sync_wedata import _dlc_catalog_response
from .tencentcloud import TencentCloudClient
from .wedata import snapshot_from_api_dump


def main():
    args = _parse_args()
    start = time.monotonic()
    db_path = args.db or os.environ.get("DLC_MCP_DB", "/data/dlc-mcp/assets.db")
    work_dir = args.work_dir or os.environ.get("DLC_MCP_SYNC_DIR", "/data/dlc-mcp/sync")
    page_size = args.page_size or int(os.environ.get("WEDATA_PAGE_SIZE", "100"))
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    os.makedirs(work_dir, exist_ok=True)

    dlc_client = TencentCloudClient.dlc_from_env()
    datasource = os.environ.get("DLC_CATALOG", "DataLakeCatalog")
    store = AssetStore(sqlite3.connect(db_path))
    store.init_schema()
    catalog = _call_with_retries(lambda: _dlc_catalog_response(dlc_client, page_size), "DLC catalog", args)
    tables = snapshot_from_api_dump({"tables": catalog})["tables"]
    synced_names = _synced_column_tables(store) if not args.force else set()
    failures = []
    synced = 0
    skipped = 0

    print(f"table catalog count: {len(tables)}", flush=True)
    for index, table in enumerate(tables, start=1):
        name = table.get("name", "")
        database = table.get("database", "")
        if not name:
            continue
        if name in synced_names:
            skipped += 1
            continue
        if not database:
            failures.append({"table": name, "error": "missing_database"})
            continue
        try:
            response = _call_with_retries(
                lambda: dlc_client.call("DescribeTable", {"DatasourceConnectionName": datasource, "DatabaseName": database, "TableName": name}),
                "DescribeTable",
                args,
            )
            detail = response.get("Response", {}).get("Table") or {}
            table["columns"] = snapshot_from_api_dump(
                {"tables": {"Response": {"Data": {"Items": [{**detail, "TableName": name, "DatabaseName": database}]}}}}
            )["tables"][0]["columns"]
            store.upsert_table(table)
            for ordinal, column in enumerate(table["columns"], start=1):
                store.upsert_column(name, column["name"], column.get("type", ""), column.get("description", ""), column.get("ordinal") or ordinal)
            synced += 1
        except Exception as exc:
            failures.append({"table": name, "database": database, "error": str(exc)})
        if args.progress_every and (index == len(tables) or index % args.progress_every == 0):
            print(f"progress {index}/{len(tables)} synced={synced} skipped={skipped} failed={len(failures)}", flush=True)
        if args.request_interval > 0:
            time.sleep(args.request_interval)

    elapsed = time.monotonic() - start
    report = {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "elapsed_seconds": round(elapsed, 3),
        "table_count": len(tables),
        "synced_table_count": synced,
        "skipped_table_count": skipped,
        "failed_table_count": len(failures),
        "failures": failures,
    }
    report_path = os.path.join(work_dir, "wedata_table_fields_full_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps({k: v for k, v in report.items() if k != "failures"}, ensure_ascii=False), flush=True)
    print(f"saved full field sync report to {report_path}", flush=True)
    if failures and args.fail_on_error:
        raise SystemExit(1)


def _parse_args():
    parser = argparse.ArgumentParser(description="Safely sync all WeData table fields into the local asset DB.")
    parser.add_argument("--db", default="")
    parser.add_argument("--work-dir", default="")
    parser.add_argument("--page-size", type=int, default=0)
    parser.add_argument("--request-interval", type=float, default=float(os.environ.get("WEDATA_FULL_FIELDS_REQUEST_INTERVAL", "0.3")))
    parser.add_argument("--max-retries", type=int, default=int(os.environ.get("WEDATA_FULL_FIELDS_MAX_RETRIES", "5")))
    parser.add_argument("--retry-base-sleep", type=float, default=float(os.environ.get("WEDATA_FULL_FIELDS_RETRY_BASE_SLEEP", "2")))
    parser.add_argument("--progress-every", type=int, default=int(os.environ.get("WEDATA_FULL_FIELDS_PROGRESS_EVERY", "50")))
    parser.add_argument("--force", action="store_true", default=os.environ.get("WEDATA_FULL_FIELDS_FORCE", "0") == "1")
    parser.add_argument("--fail-on-error", action="store_true", default=os.environ.get("WEDATA_FULL_FIELDS_FAIL_ON_ERROR", "0") == "1")
    return parser.parse_args()


def _synced_column_tables(store):
    return {row["table_name"] for row in store._all("select table_name from columns group by table_name")}


def _call_with_retries(call, action, args):
    for attempt in range(args.max_retries + 1):
        try:
            response = call()
            error = response.get("Response", {}).get("Error")
            if error:
                raise RuntimeError(f"{error.get('Code')} {error.get('Message')}")
            return response
        except Exception:
            if attempt >= args.max_retries:
                raise
            time.sleep(args.retry_base_sleep * (2 ** attempt))


if __name__ == "__main__":
    main()
