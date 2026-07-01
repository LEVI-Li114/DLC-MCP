import json
import os
import sqlite3
from datetime import datetime, timedelta

from .assets import AssetStore
from .tencentcloud import TencentCloudClient
from .wedata import import_wedata_snapshot, snapshot_from_api_dump


def main():
    project_id = os.environ["WEDATA_PROJECT_ID"]
    db_path = os.environ.get("DLC_AGENT_DB", "/data/dlc-agent/assets.db")
    work_dir = os.environ.get("DLC_AGENT_SYNC_DIR", "/data/dlc-agent/sync")
    page_size = int(os.environ.get("WEDATA_PAGE_SIZE", "100"))

    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    os.makedirs(work_dir, exist_ok=True)

    client = TencentCloudClient.wedata_from_env()
    tasks_response = _list_all(client, "ListTasks", {"ProjectId": project_id}, page_size)
    tasks_path = os.path.join(work_dir, "wedata_tasks.json")
    with open(tasks_path, "w", encoding="utf-8") as f:
        json.dump(tasks_response, f, ensure_ascii=False, indent=2)

    dump = {"tasks": tasks_response}
    task_snapshot = snapshot_from_api_dump(dump)
    table_names = sorted({table for task in task_snapshot["tasks"] for table in task.get("outputs", [])})

    if os.environ.get("WEDATA_SYNC_METADATA") == "1":
        metadata_dump = _sync_metadata(client, project_id, table_names, page_size, work_dir)
        dump.update(metadata_dump)

    if os.environ.get("WEDATA_SYNC_INSTANCES") == "1":
        instance_payload = {"ProjectId": project_id}
        start_time, end_time = _instance_window()
        instance_payload["StartTime"] = start_time
        instance_payload["EndTime"] = end_time
        instances_response = _list_all(client, "ListTaskInstances", instance_payload, page_size)
        instances_path = os.path.join(work_dir, "wedata_task_instances.json")
        with open(instances_path, "w", encoding="utf-8") as f:
            json.dump(instances_response, f, ensure_ascii=False, indent=2)
        dump["task_instances"] = instances_response

    store = AssetStore(sqlite3.connect(db_path))
    store.init_schema()
    import_wedata_snapshot(store, snapshot_from_api_dump(dump))

    total = len(tasks_response["Response"]["Data"]["Items"])
    print(f"synced {total} WeData tasks into {db_path}")
    print(f"saved raw task dump to {tasks_path}")
    if "task_instances" in dump:
        run_total = len(dump["task_instances"]["Response"]["Data"]["Items"])
        print(f"synced {run_total} WeData task instances")
    if "tables" in dump:
        print(f"synced metadata for {len(dump['tables']['Response']['Data']['Items'])} tables")


def _list_all(client, action, payload, page_size):
    first = client.call(action, {**payload, "PageNumber": 1, "PageSize": page_size})
    data = first.get("Response", {}).get("Data", {})
    total_pages = int(data.get("TotalPageNumber") or data.get("PageCount") or 1)
    items = list(data.get("Items") or [])

    for page in range(2, total_pages + 1):
        response = client.call(action, {**payload, "PageNumber": page, "PageSize": page_size})
        items.extend(response.get("Response", {}).get("Data", {}).get("Items") or [])

    first["Response"]["Data"]["Items"] = items
    first["Response"]["Data"]["PageNumber"] = 1
    first["Response"]["Data"]["PageSize"] = page_size
    first["Response"]["Data"]["TotalPageNumber"] = total_pages
    return first


def _instance_window():
    if os.environ.get("WEDATA_INSTANCE_START") and os.environ.get("WEDATA_INSTANCE_END"):
        return os.environ["WEDATA_INSTANCE_START"], os.environ["WEDATA_INSTANCE_END"]
    days = int(os.environ.get("WEDATA_INSTANCE_LOOKBACK_DAYS", "2"))
    today = datetime.now().date()
    start = today - timedelta(days=max(days, 1) - 1)
    return f"{start:%Y-%m-%d} 00:00:00", f"{today:%Y-%m-%d} 23:59:59"


def _sync_metadata(client, project_id, table_names, page_size, work_dir):
    if os.environ.get("WEDATA_METADATA_TABLES"):
        table_names = [name.strip() for name in os.environ["WEDATA_METADATA_TABLES"].split(",") if name.strip()]
    limit = int(os.environ.get("WEDATA_METADATA_TABLE_LIMIT", "50"))
    table_names = table_names[:limit]
    tables = []
    columns = {}
    lineage = []
    quality_rules = []

    for table_name in table_names:
        table_response = client.call("ListTable", {"PageNumber": 1, "PageSize": 20, "Keyword": table_name})
        matches = [item for item in table_response.get("Response", {}).get("Data", {}).get("Items", []) if item.get("Name") == table_name]
        if not matches:
            continue
        table = matches[0]
        guid = table.get("Guid")
        if guid:
            column_response = client.call("GetTableColumns", {"TableGuid": guid})
            table["Columns"] = column_response.get("Response", {}).get("Data") or []
            columns[table_name] = column_response
            for direction in ("OUTPUT",):
                lineage_response = _list_all(
                    client,
                    "ListLineage",
                    {"ResourceUniqueId": guid, "ResourceType": "TABLE", "Direction": direction, "Platform": "WEDATA"},
                    page_size,
                )
                for item in lineage_response.get("Response", {}).get("Data", {}).get("Items", []) or []:
                    item["QueriedTableName"] = table_name
                    lineage.append(item)
        quality_response = _list_all(
            client,
            "ListQualityRules",
            {"ProjectId": project_id, "Filters": [{"Name": "TableName", "Values": [table_name]}]},
            page_size,
        )
        quality_rules.extend(quality_response.get("Response", {}).get("Data", {}).get("Items", []) or [])
        tables.append(table)

    payload = {
        "tables": {"Response": {"Data": {"Items": tables}}},
        "lineage": {"Response": {"Data": {"Items": lineage}}},
        "quality_rules": {"Response": {"Data": {"Items": quality_rules}}},
    }
    path = os.path.join(work_dir, "wedata_metadata.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"payload": payload, "columns": columns}, f, ensure_ascii=False, indent=2)
    print(f"saved raw metadata dump to {path}")
    return payload


if __name__ == "__main__":
    main()
