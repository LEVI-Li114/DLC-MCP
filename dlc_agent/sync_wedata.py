import json
import os
import sqlite3

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

    tasks_response = _list_all_tasks(TencentCloudClient.wedata_from_env(), project_id, page_size)
    tasks_path = os.path.join(work_dir, "wedata_tasks.json")
    with open(tasks_path, "w", encoding="utf-8") as f:
        json.dump(tasks_response, f, ensure_ascii=False, indent=2)

    store = AssetStore(sqlite3.connect(db_path))
    store.init_schema()
    import_wedata_snapshot(store, snapshot_from_api_dump({"tasks": tasks_response}))

    total = len(tasks_response["Response"]["Data"]["Items"])
    print(f"synced {total} WeData tasks into {db_path}")
    print(f"saved raw task dump to {tasks_path}")


def _list_all_tasks(client, project_id, page_size):
    first = client.call("ListTasks", {"ProjectId": project_id, "PageNumber": 1, "PageSize": page_size})
    data = first.get("Response", {}).get("Data", {})
    total_pages = int(data.get("TotalPageNumber") or 1)
    items = list(data.get("Items") or [])

    for page in range(2, total_pages + 1):
        response = client.call("ListTasks", {"ProjectId": project_id, "PageNumber": page, "PageSize": page_size})
        items.extend(response.get("Response", {}).get("Data", {}).get("Items") or [])

    first["Response"]["Data"]["Items"] = items
    first["Response"]["Data"]["PageNumber"] = 1
    first["Response"]["Data"]["PageSize"] = page_size
    first["Response"]["Data"]["TotalPageNumber"] = total_pages
    return first


if __name__ == "__main__":
    main()
