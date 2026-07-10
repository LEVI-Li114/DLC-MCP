import argparse
import json
import os
import sqlite3
import time
from datetime import datetime, timedelta

from .assets import AssetStore
from .sync_table_fields import _call_with_retries
from .tencentcloud import TencentCloudClient
from .wedata import import_wedata_snapshot, snapshot_from_api_dump


def main():
    args = _parse_args()
    started = time.monotonic()
    project_id = os.environ["WEDATA_PROJECT_ID"]
    db_path = args.db or os.environ.get("DLC_MCP_DB", "/data/dlc-mcp/assets.db")
    work_dir = args.work_dir or os.environ.get("DLC_MCP_SYNC_DIR", "/data/dlc-mcp/sync")
    page_size = args.page_size or int(os.environ.get("WEDATA_PAGE_SIZE", "100"))
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    os.makedirs(work_dir, exist_ok=True)

    client = TencentCloudClient.wedata_from_env()
    store = AssetStore(sqlite3.connect(db_path))
    store.init_schema()
    catalog = _list_all_retried(client, "ListTable", {}, page_size, args)
    tables = snapshot_from_api_dump({"tables": catalog})["tables"]
    report = {"table_count": len(tables), "failures": []}
    dump = {"tables": catalog}

    if args.sync_tasks:
        tasks = _list_all_retried(client, "ListTasks", {"ProjectId": project_id}, page_size, args)
        dump["tasks"] = tasks
        report["task_count"] = len(tasks.get("Response", {}).get("Data", {}).get("Items") or [])

    if args.sync_lineage or args.sync_quality:
        metadata = _sync_lineage_quality(client, project_id, tables, page_size, args, report)
        dump.update(metadata)

    if args.sync_instances:
        start_time, end_time = _instance_window(args)
        payload = {
            "ProjectId": project_id,
            "ScheduleTimeFrom": start_time,
            "ScheduleTimeTo": end_time,
            "TimeZone": os.environ.get("WEDATA_INSTANCE_TIMEZONE", "UTC+8"),
        }
        if args.instance_keyword:
            payload["Keyword"] = args.instance_keyword
        instances = _list_all_retried(client, "ListTaskInstances", payload, page_size, args, max_pages=args.instance_max_pages)
        dump["task_instances"] = instances
        report["instance_window"] = {"start": start_time, "end": end_time}
        report["task_instance_count"] = len(instances.get("Response", {}).get("Data", {}).get("Items") or [])

    import_wedata_snapshot(store, snapshot_from_api_dump(dump))
    report.update(
        {
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "failed_count": len(report["failures"]),
        }
    )
    path = os.path.join(work_dir, "wedata_asset_facts_full_report.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps({k: v for k, v in report.items() if k != "failures"}, ensure_ascii=False), flush=True)
    print(f"saved full asset facts sync report to {path}", flush=True)
    if report["failures"] and args.fail_on_error:
        raise SystemExit(1)


def _parse_args():
    parser = argparse.ArgumentParser(description="Safely sync full WeData asset facts except table fields.")
    parser.add_argument("--db", default="")
    parser.add_argument("--work-dir", default="")
    parser.add_argument("--page-size", type=int, default=0)
    parser.add_argument("--request-interval", type=float, default=float(os.environ.get("WEDATA_FULL_FACTS_REQUEST_INTERVAL", "0.3")))
    parser.add_argument("--max-retries", type=int, default=int(os.environ.get("WEDATA_FULL_FACTS_MAX_RETRIES", "5")))
    parser.add_argument("--retry-base-sleep", type=float, default=float(os.environ.get("WEDATA_FULL_FACTS_RETRY_BASE_SLEEP", "2")))
    parser.add_argument("--progress-every", type=int, default=int(os.environ.get("WEDATA_FULL_FACTS_PROGRESS_EVERY", "50")))
    parser.add_argument("--instance-lookback-days", type=int, default=int(os.environ.get("WEDATA_FULL_FACTS_INSTANCE_LOOKBACK_DAYS", "7")))
    parser.add_argument("--instance-max-pages", type=int, default=int(os.environ.get("WEDATA_FULL_FACTS_INSTANCE_MAX_PAGES", "500")))
    parser.add_argument("--instance-keyword", default=os.environ.get("WEDATA_FULL_FACTS_INSTANCE_KEYWORD", ""))
    parser.add_argument("--sync-tasks", action="store_true", default=os.environ.get("WEDATA_FULL_FACTS_SYNC_TASKS", "1") == "1")
    parser.add_argument("--sync-lineage", action="store_true", default=os.environ.get("WEDATA_FULL_FACTS_SYNC_LINEAGE", "1") == "1")
    parser.add_argument("--sync-quality", action="store_true", default=os.environ.get("WEDATA_FULL_FACTS_SYNC_QUALITY", "1") == "1")
    parser.add_argument("--sync-instances", action="store_true", default=os.environ.get("WEDATA_FULL_FACTS_SYNC_INSTANCES", "1") == "1")
    parser.add_argument("--fail-on-error", action="store_true", default=os.environ.get("WEDATA_FULL_FACTS_FAIL_ON_ERROR", "0") == "1")
    return parser.parse_args()


def _sync_lineage_quality(client, project_id, tables, page_size, args, report):
    lineage = []
    quality_rules = []
    lineage_ok = 0
    quality_ok = 0
    for index, table in enumerate(tables, start=1):
        name = table.get("name", "")
        guid = table.get("guid", "")
        if args.sync_lineage and guid:
            try:
                response = _call_with_retries(
                    lambda: _list_all_retried(client, "ListLineage", {"ResourceUniqueId": guid, "ResourceType": "TABLE", "Direction": "OUTPUT", "Platform": "WEDATA"}, page_size, args),
                    "ListLineage",
                    args,
                )
                for item in response.get("Response", {}).get("Data", {}).get("Items") or []:
                    item["QueriedTableName"] = name
                    lineage.append(item)
                lineage_ok += 1
            except Exception as exc:
                report["failures"].append({"fact": "lineage", "table": name, "guid": guid, "error": str(exc)})
            _sleep(args)
        elif args.sync_lineage:
            report["failures"].append({"fact": "lineage", "table": name, "error": "missing_guid"})

        if args.sync_quality and name:
            try:
                response = _call_with_retries(
                    lambda: _list_all_retried(client, "ListQualityRules", {"ProjectId": project_id, "Filters": [{"Name": "TableName", "Values": [name]}]}, page_size, args),
                    "ListQualityRules",
                    args,
                )
                quality_rules.extend(response.get("Response", {}).get("Data", {}).get("Items") or [])
                quality_ok += 1
            except Exception as exc:
                report["failures"].append({"fact": "quality", "table": name, "error": str(exc)})
            _sleep(args)

        if args.progress_every and (index == len(tables) or index % args.progress_every == 0):
            print(f"progress {index}/{len(tables)} lineage_tables={lineage_ok} quality_tables={quality_ok} failed={len(report['failures'])}", flush=True)

    report["lineage_table_count"] = lineage_ok
    report["lineage_edge_count"] = len(lineage)
    report["quality_table_count"] = quality_ok
    report["quality_rule_count"] = len(quality_rules)
    return {
        "lineage": {"Response": {"Data": {"Items": lineage}}},
        "quality_rules": {"Response": {"Data": {"Items": quality_rules}}},
    }


def _list_all_retried(client, action, payload, page_size, args, max_pages=None):
    first = _call_page(client, action, payload, 1, page_size, args)
    data = first.get("Response", {}).get("Data", {})
    total_pages = int(data.get("TotalPageNumber") or data.get("PageCount") or _pages_from_total(data, page_size) or 1)
    items = list(data.get("Items") or [])
    stop_page = min(total_pages, max_pages or total_pages)

    for page in range(2, stop_page + 1):
        _sleep(args)
        response = _call_page(client, action, payload, page, page_size, args)
        items.extend(response.get("Response", {}).get("Data", {}).get("Items") or [])
        if args.progress_every and (page == stop_page or page % args.progress_every == 0):
            print(f"{action} pages {page}/{stop_page} items={len(items)}", flush=True)

    first["Response"]["Data"]["Items"] = items
    first["Response"]["Data"]["PageNumber"] = 1
    first["Response"]["Data"]["PageSize"] = page_size
    first["Response"]["Data"]["TotalPageNumber"] = total_pages
    first["Response"]["Data"]["SyncedPageNumber"] = stop_page
    return first


def _call_page(client, action, payload, page, page_size, args):
    response = _call_with_retries(
        lambda: client.call(action, {**payload, "PageNumber": page, "PageSize": page_size}),
        f"{action} page {page}",
        args,
    )
    if "Error" in response.get("Response", {}):
        error = response["Response"]["Error"]
        raise RuntimeError(f"{action} page {page} failed: {error.get('Code')} {error.get('Message')}")
    return response


def _pages_from_total(data, page_size):
    total = int(data.get("TotalCount") or 0)
    return (total + page_size - 1) // page_size if total else 0


def _instance_window(args):
    end = datetime.now()
    start = end - timedelta(days=max(args.instance_lookback_days, 1) - 1)
    return f"{start:%Y-%m-%d} 00:00:00", f"{end:%Y-%m-%d} 23:59:59"


def _sleep(args):
    if args.request_interval > 0:
        time.sleep(args.request_interval)


if __name__ == "__main__":
    main()
