import json
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

from .assets import AssetStore
from .tencentcloud import TencentCloudClient
from .wedata import _dedupe_table_names, _items, _normalize_table_name, _task_table_names, import_wedata_snapshot, snapshot_from_api_dump


def main():
    project_id = os.environ["WEDATA_PROJECT_ID"]
    db_path = os.environ.get("DLC_MCP_DB", "/data/dlc-mcp/assets.db")
    work_dir = os.environ.get("DLC_MCP_SYNC_DIR", "/data/dlc-mcp/sync")
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
    catalog_tables = {}

    if os.environ.get("WEDATA_SYNC_TABLE_CATALOG", "1") == "1":
        tables_response = _list_all(client, "ListTable", {}, page_size)
        tables_path = os.path.join(work_dir, "wedata_tables.json")
        with open(tables_path, "w", encoding="utf-8") as f:
            json.dump(tables_response, f, ensure_ascii=False, indent=2)
        dump["tables"] = tables_response
        catalog_tables = _catalog_tables_by_name(tables_response)
        table_names = sorted(set(table_names) | set(catalog_tables))
        print(f"saved raw table catalog dump to {tables_path}", flush=True)

    if os.environ.get("WEDATA_SYNC_METADATA") == "1":
        if os.environ.get("WEDATA_NEW_ASSET_START") and os.environ.get("WEDATA_NEW_ASSET_END"):
            table_names = _filter_new_asset_tables(table_names, catalog_tables, os.environ["WEDATA_NEW_ASSET_START"], os.environ["WEDATA_NEW_ASSET_END"])
        metadata_dump = _sync_metadata(client, project_id, table_names, page_size, work_dir, catalog_tables)
        dump.update(_merge_metadata_dump(dump, metadata_dump))

    if os.environ.get("WEDATA_SYNC_PARTITIONS") == "1":
        partitions_response = _sync_partitions(client, project_id, table_names, page_size, catalog_tables=catalog_tables)
        partitions_path = os.path.join(work_dir, "wedata_table_partitions.json")
        with open(partitions_path, "w", encoding="utf-8") as f:
            json.dump(partitions_response, f, ensure_ascii=False, indent=2)
        dump["table_partitions"] = partitions_response
        print(f"saved raw table partitions dump to {partitions_path}", flush=True)

    if os.environ.get("WEDATA_SYNC_DATA_SOURCES") == "1":
        data_sources_response = _list_all(client, "ListDataSources", {"ProjectId": project_id}, page_size)
        data_sources_path = os.path.join(work_dir, "wedata_data_sources.json")
        with open(data_sources_path, "w", encoding="utf-8") as f:
            json.dump(data_sources_response, f, ensure_ascii=False, indent=2)
        dump["data_sources"] = data_sources_response
        related_tasks = _sync_data_source_tasks(client, data_sources_response)
        related_tasks_path = os.path.join(work_dir, "wedata_data_source_tasks.json")
        with open(related_tasks_path, "w", encoding="utf-8") as f:
            json.dump(related_tasks, f, ensure_ascii=False, indent=2)
        dump["data_source_tasks"] = related_tasks
        related_task_definitions = _sync_related_task_definitions(client, project_id, related_tasks, page_size)
        if _response_item_count(related_task_definitions):
            related_task_definitions_path = os.path.join(work_dir, "wedata_data_source_task_definitions.json")
            with open(related_task_definitions_path, "w", encoding="utf-8") as f:
                json.dump(related_task_definitions, f, ensure_ascii=False, indent=2)
            dump["tasks"] = _merge_task_responses(dump.get("tasks", {}), related_task_definitions)

    if os.environ.get("WEDATA_SYNC_INSTANCES") == "1":
        instance_payload = {"ProjectId": project_id}
        start_time, end_time = _instance_window()
        instance_payload["ScheduleTimeFrom"] = start_time
        instance_payload["ScheduleTimeTo"] = end_time
        instance_payload["TimeZone"] = os.environ.get("WEDATA_INSTANCE_TIMEZONE", "UTC+8")
        if os.environ.get("WEDATA_INSTANCE_KEYWORDS"):
            instance_payload["Keyword"] = os.environ["WEDATA_INSTANCE_KEYWORDS"]
        max_pages = int(os.environ.get("WEDATA_INSTANCE_MAX_PAGES", "50"))
        instances_response = _list_all(client, "ListTaskInstances", instance_payload, page_size, max_pages=max_pages)
        instances_path = os.path.join(work_dir, "wedata_task_instances.json")
        with open(instances_path, "w", encoding="utf-8") as f:
            json.dump(instances_response, f, ensure_ascii=False, indent=2)
        dump["task_instances"] = instances_response

    store = AssetStore(sqlite3.connect(db_path))
    store.init_schema()
    import_wedata_snapshot(store, snapshot_from_api_dump(dump))
    retention = store.prune_task_runs(int(os.environ.get("DLC_MCP_TASK_RUN_RETENTION_DAYS", "7")))

    total = len(tasks_response["Response"]["Data"]["Items"])
    print(f"synced {total} WeData tasks into {db_path}", flush=True)
    print(f"saved raw task dump to {tasks_path}", flush=True)
    if "task_instances" in dump:
        run_total = len(dump["task_instances"]["Response"]["Data"]["Items"])
        print(f"synced {run_total} WeData task instances", flush=True)
        print(f"pruned {retention['deleted_count']} task instances older than {retention['cutoff_date']}", flush=True)
    if "tables" in dump:
        print(f"synced table catalog for {_response_item_count(dump['tables'])} tables", flush=True)
    if os.environ.get("WEDATA_SYNC_METADATA") == "1":
        print(f"synced metadata details for {_metadata_table_count(metadata_dump)} tables", flush=True)
    if "data_sources" in dump:
        print(f"synced {len(dump['data_sources']['Response']['Data']['Items'])} WeData data sources", flush=True)
    if "table_partitions" in dump:
        print(f"synced partitions for {_response_item_count(dump['table_partitions'])} table partitions", flush=True)


def _list_all(client, action, payload, page_size, max_pages=None):
    first = client.call(action, {**payload, "PageNumber": 1, "PageSize": page_size})
    if "Error" in first.get("Response", {}):
        error = first["Response"]["Error"]
        raise RuntimeError(f"{action} failed: {error.get('Code')} {error.get('Message')}")
    data = first.get("Response", {}).get("Data", {})
    total_pages = int(data.get("TotalPageNumber") or data.get("PageCount") or _pages_from_total(data, page_size) or 1)
    items = list(data.get("Items") or [])

    stop_page = min(total_pages, max_pages or total_pages)
    for page in range(2, stop_page + 1):
        response = client.call(action, {**payload, "PageNumber": page, "PageSize": page_size})
        if "Error" in response.get("Response", {}):
            error = response["Response"]["Error"]
            raise RuntimeError(f"{action} failed: {error.get('Code')} {error.get('Message')}")
        items.extend(response.get("Response", {}).get("Data", {}).get("Items") or [])

    first["Response"]["Data"]["Items"] = items
    first["Response"]["Data"]["PageNumber"] = 1
    first["Response"]["Data"]["PageSize"] = page_size
    first["Response"]["Data"]["TotalPageNumber"] = total_pages
    first["Response"]["Data"]["SyncedPageNumber"] = stop_page
    return first


def _pages_from_total(data, page_size):
    total = int(data.get("TotalCount") or 0)
    return (total + page_size - 1) // page_size if total else 0


def _merge_metadata_dump(dump, metadata_dump):
    if "tables" not in dump:
        return metadata_dump
    catalog_items = dump["tables"]["Response"]["Data"].get("Items") or []
    detail_items = metadata_dump.get("tables", {}).get("Response", {}).get("Data", {}).get("Items") or []
    by_name = {item.get("Name") or item.get("TableName"): item for item in catalog_items}
    for item in detail_items:
        name = item.get("Name") or item.get("TableName")
        if name:
            by_name[name] = {**by_name.get(name, {}), **item}
    metadata_dump["tables"]["Response"]["Data"]["Items"] = list(by_name.values())
    return metadata_dump


def _sync_data_source_tasks(client, data_sources_response, progress_every=10):
    related = {}
    items = data_sources_response.get("Response", {}).get("Data", {}).get("Items") or []
    total = len(items)
    for index, item in enumerate(items, start=1):
        data_source_id = item.get("Id") or item.get("DataSourceId") or item.get("DatasourceId")
        if data_source_id:
            related[str(data_source_id)] = client.call("GetDataSourceRelatedTasks", {"Id": int(data_source_id)})
        if progress_every and (index == total or index % progress_every == 0):
            print(f"synced related tasks for {index}/{total} data sources", flush=True)
    return related


def _sync_related_task_definitions(client, project_id, related_tasks, page_size, progress_every=20):
    definitions = []
    seen_task_ids = set()
    tasks = _flatten_related_tasks(related_tasks)
    total = len(tasks)
    for index, task in enumerate(tasks, start=1):
        task_id = str(task.get("task_id") or "")
        task_name = task.get("task_name") or ""
        if task_id and task_id in seen_task_ids:
            continue
        response = _list_all(client, "ListTasks", {"ProjectId": project_id, "TaskName": task_name}, page_size)
        for item in response.get("Response", {}).get("Data", {}).get("Items") or []:
            if _task_matches_related_item(item, task):
                definitions.append(_enrich_related_task_definition(client, project_id, item, task, page_size))
                if task_id:
                    seen_task_ids.add(task_id)
                break
        if progress_every and (index == total or index % progress_every == 0):
            print(f"synced definitions for {index}/{total} data source related tasks", flush=True)
    return {"Response": {"Data": {"Items": definitions}}}


def _enrich_related_task_definition(client, project_id, item, related, page_size):
    enriched = dict(item)
    outputs = _task_table_names(enriched, "output")
    inputs = _task_table_names(enriched, "input")
    if not outputs:
        inputs, outputs = _task_lineage_tables(client, project_id, related, page_size)
    if not outputs:
        detail = _task_detail(client, project_id, related)
        if detail:
            enriched.update({k: v for k, v in detail.items() if v not in ("", None, [], {})})
            outputs = _task_table_names(enriched, "output")
            inputs = inputs or _task_table_names(enriched, "input")
    if inputs:
        enriched["InputTables"] = _merged_table_list(enriched.get("InputTables"), inputs)
    if outputs:
        enriched["OutputTables"] = _merged_table_list(enriched.get("OutputTables"), outputs)
    return enriched


def _merged_table_list(existing, extra):
    current = existing if isinstance(existing, list) else []
    return _dedupe_table_names([*current, *extra])


def _task_lineage_tables(client, project_id, related, page_size):
    task_id = str(related.get("task_id") or "")
    if not task_id:
        return [], []
    payload = {"ProcessId": task_id, "ProcessType": "SCHEDULE_TASK", "Platform": "WEDATA"}
    try:
        response = _list_all(client, "ListProcessLineage", payload, page_size)
    except Exception:
        return [], []
    inputs = []
    outputs = []
    for item in _items(response):
        inputs.extend(_lineage_endpoint_table_names(item.get("Source") or item.get("Sources") or item.get("source")))
        outputs.extend(_lineage_endpoint_table_names(item.get("Target") or item.get("Targets") or item.get("target")))
        resource = item.get("Resource") or {}
        if resource:
            outputs.extend(_lineage_endpoint_table_names(resource))
    return _dedupe_table_names(inputs), _dedupe_table_names(outputs)


def _lineage_endpoint_table_names(value):
    if value is None:
        return []
    if isinstance(value, list):
        names = []
        for item in value:
            names.extend(_lineage_endpoint_table_names(item))
        return names
    if isinstance(value, dict):
        names = []
        property_name = _lineage_resource_property(value, "TableName")
        if property_name:
            name = _normalize_table_name(property_name)
            if name:
                names.append(name)
        for field in ("ResourceName", "TableName", "Name", "TargetTable", "SourceTable", "DatabaseTable", "DbTableName"):
            if field == "ResourceName" and str(value.get("ResourceType") or "").upper() == "COLUMN":
                continue
            if value.get(field):
                name = _normalize_table_name(value[field])
                if name:
                    names.append(name)
        for field in ("Resource", "Resources", "Items", "List"):
            if field in value:
                names.extend(_lineage_endpoint_table_names(value[field]))
        return names
    name = _normalize_table_name(value)
    return [name] if name else []


def _lineage_resource_property(value, name):
    for item in value.get("ResourceProperties") or []:
        if item.get("Name") == name:
            return item.get("Value") or ""
    return ""


def _task_detail(client, project_id, related):
    task_id = str(related.get("task_id") or "")
    task_name = related.get("task_name") or ""
    for action in ("GetTask", "GetTaskCode"):
        payload = {"ProjectId": project_id}
        if task_id:
            payload["TaskId"] = task_id
        elif task_name:
            payload["TaskName"] = task_name
        try:
            response = client.call(action, payload)
        except Exception:
            continue
        error = response.get("Response", {}).get("Error")
        if error:
            continue
        detail = _first_detail_item(response)
        if detail:
            return detail
    return {}


def _first_detail_item(response):
    items = _items(response)
    if items:
        return items[0]
    data = response.get("Response", response)
    if isinstance(data, dict):
        data = data.get("Data", data)
    if not isinstance(data, dict):
        return {}
    result = dict(data)
    base = result.get("TaskBaseAttribute") or {}
    if isinstance(base, dict):
        result.update({k: v for k, v in base.items() if k not in result})
    config = result.get("TaskConfiguration") or result.get("Configuration") or {}
    if isinstance(config, str):
        try:
            config = json.loads(config)
        except json.JSONDecodeError:
            config = {}
    if isinstance(config, dict):
        result.update({k: v for k, v in config.items() if k not in result})
    return result


def _flatten_related_tasks(related_tasks):
    tasks = []
    for response in related_tasks.values():
        for project in response.get("Response", {}).get("Data") or []:
            for group in project.get("TaskInfo") or []:
                for item in group.get("TaskList") or []:
                    tasks.append(
                        {
                            "task_id": str(item.get("TaskId") or item.get("Id") or item.get("id") or ""),
                            "task_name": item.get("TaskName") or item.get("Name") or item.get("name") or "",
                        }
                    )
    return tasks


def _task_matches_related_item(item, related):
    task_id = str(item.get("TaskId") or item.get("Id") or item.get("id") or "")
    task_name = item.get("TaskName") or item.get("Name") or item.get("name") or ""
    related_id = str(related.get("task_id") or "")
    related_name = related.get("task_name") or ""
    return bool((related_id and task_id == related_id) or (related_name and task_name == related_name))


def _merge_task_responses(primary, extra):
    primary_items = primary.get("Response", {}).get("Data", {}).get("Items") or []
    extra_items = extra.get("Response", {}).get("Data", {}).get("Items") or []
    by_id = {}
    for item in [*primary_items, *extra_items]:
        task_id = str(item.get("TaskId") or item.get("Id") or item.get("id") or "")
        key = task_id or item.get("TaskName") or item.get("Name") or item.get("name") or ""
        if key:
            by_id[key] = {**by_id.get(key, {}), **item}
    merged = primary or {"Response": {"Data": {}}}
    merged.setdefault("Response", {}).setdefault("Data", {})["Items"] = list(by_id.values())
    return merged


def _sync_partitions(client, project_id, table_names, page_size, progress_every=10, catalog_tables=None):
    action = os.environ.get("WEDATA_PARTITION_ACTION", "ListTablePartitions")
    partition_date = os.environ.get("WEDATA_PARTITION_DATE", "")
    partition_client = _partition_client(client)
    items = []
    failures = []
    total = len(table_names)
    for index, table_name in enumerate(table_names, start=1):
        payload = _partition_payload(project_id, table_name, (catalog_tables or {}).get(table_name, {}))
        if not _partition_payload_ready(payload):
            failures.append({"table": table_name, "error": "missing required partition payload fields", "payload": payload})
            continue
        if partition_date and os.environ.get("WEDATA_PARTITION_SERVICE", "wedata") != "dlc":
            payload["PartitionDate"] = partition_date
        try:
            response = _list_partitions(partition_client, action, payload, page_size)
        except RuntimeError as exc:
            if "InvalidAction" not in str(exc):
                failures.append({"table": table_name, "error": str(exc), "payload": payload})
                continue
            return {
                "Response": {
                    "Error": {"Code": "InvalidAction", "Message": str(exc)},
                    "UnsupportedAction": action,
                    "Data": {"Items": []},
                }
            }
        for item in _partition_items(response):
            item["QueriedTableName"] = table_name
            if _partition_matches_date(item, partition_date):
                items.append(item)
        if progress_every and (index == total or index % progress_every == 0):
            print(f"synced partitions for {index}/{total} tables", flush=True)
    return {"Response": {"Data": {"Items": items}, "PartitionFailures": failures}}


def _partition_payload(project_id, table_name, catalog_item=None):
    item = catalog_item or {}
    if os.environ.get("WEDATA_PARTITION_SERVICE", "wedata") == "dlc":
        return _dlc_partition_payload(table_name, item)
    payload = {"ProjectId": project_id, "TableName": table_name}
    mode = os.environ.get("WEDATA_PARTITION_PAYLOAD_MODE", "table")
    if mode == "guid" and (item.get("Guid") or item.get("TableGuid")):
        payload = {"ProjectId": project_id, "TableGuid": item.get("Guid") or item.get("TableGuid")}
    elif mode == "database" and (item.get("DatabaseName") or item.get("Database") or item.get("DbName")):
        payload["DatabaseName"] = item.get("DatabaseName") or item.get("Database") or item.get("DbName")
    elif mode == "datasource_database":
        if item.get("DatasourceId") or item.get("DataSourceId"):
            payload["DataSourceId"] = item.get("DatasourceId") or item.get("DataSourceId")
        if item.get("DatabaseName") or item.get("Database") or item.get("DbName"):
            payload["DatabaseName"] = item.get("DatabaseName") or item.get("Database") or item.get("DbName")
    return payload


def _partition_client(default_client):
    if os.environ.get("WEDATA_PARTITION_SERVICE", "wedata") != "dlc":
        return default_client
    return TencentCloudClient(
        os.environ["TENCENTCLOUD_SECRET_ID"],
        os.environ["TENCENTCLOUD_SECRET_KEY"],
        "dlc",
        os.environ.get("DLC_API_VERSION", "2021-01-25"),
        os.environ.get("TENCENTCLOUD_REGION", "ap-guangzhou"),
        endpoint=os.environ.get("DLC_ENDPOINT"),
    )


def _dlc_partition_payload(table_name, item):
    payload = {
        "Catalog": os.environ.get("DLC_CATALOG", "DataLakeCatalog"),
        "Database": item.get("DatabaseName") or item.get("Database") or item.get("DbName"),
        "Table": table_name,
    }
    return {key: value for key, value in payload.items() if value}


def _partition_payload_ready(payload):
    if os.environ.get("WEDATA_PARTITION_SERVICE", "wedata") != "dlc":
        return bool(payload.get("ProjectId") and payload.get("TableName"))
    return bool(payload.get("Catalog") and payload.get("Database") and payload.get("Table"))


def _list_partitions(client, action, payload, page_size):
    if os.environ.get("WEDATA_PARTITION_SERVICE", "wedata") != "dlc":
        return _list_all(client, action, payload, page_size)
    first = client.call(action, {**payload, "Limit": page_size, "Offset": 0})
    if "Error" in first.get("Response", {}):
        error = first["Response"]["Error"]
        raise RuntimeError(f"{action} failed: {error.get('Code')} {error.get('Message')}")
    mixed = first.get("Response", {}).get("MixedPartitions") or {}
    total = int(mixed.get("TotalSize") or 0)
    items = _partition_items(first)
    offset = page_size
    while offset < total:
        response = client.call(action, {**payload, "Limit": page_size, "Offset": offset})
        if "Error" in response.get("Response", {}):
            error = response["Response"]["Error"]
            raise RuntimeError(f"{action} failed: {error.get('Code')} {error.get('Message')}")
        items.extend(_partition_items(response))
        offset += page_size
    first.setdefault("Response", {}).setdefault("MixedPartitions", {})["IcebergPartitions"] = items
    return first


def _partition_items(response):
    data = response.get("Response", {}).get("Data", {})
    if isinstance(data, dict):
        for key in ("Items", "Rows", "List", "Records"):
            if isinstance(data.get(key), list):
                return data[key]
    mixed = response.get("Response", {}).get("MixedPartitions") or {}
    for key in ("IcebergPartitions", "HivePartitions", "Partitions"):
        if isinstance(mixed.get(key), list):
            return mixed[key]
    return []


def _partition_matches_date(item, partition_date):
    if not partition_date:
        return True
    expected = {partition_date, partition_date.replace("-", "")}
    for field in ("PartitionName", "Partition", "PartitionSpec", "Name"):
        value = str(item.get(field) or "")
        if any(f"dt={candidate}" in value or value == candidate for candidate in expected):
            return True
    return False


def partition_payload_candidates(project_id, table):
    name = table.get("Name") or table.get("TableName") or table.get("name") or table.get("tableName") or ""
    guid = table.get("Guid") or table.get("TableGuid") or table.get("TableId") or ""
    database = table.get("DatabaseName") or table.get("Database") or table.get("DbName") or table.get("SchemaName") or ""
    data_source_id = table.get("DatasourceId") or table.get("DataSourceId") or table.get("DatasourceID") or table.get("DataSourceID") or ""
    base = {"ProjectId": project_id}
    payloads = []
    if name:
        payloads.append({**base, "TableName": name})
    if guid:
        payloads.append({**base, "TableGuid": guid})
    if database and name:
        payloads.append({**base, "DatabaseName": database, "TableName": name})
    if data_source_id and database and name:
        payloads.append({**base, "DataSourceId": str(data_source_id), "DatabaseName": database, "TableName": name})
    return payloads


def _response_item_count(response):
    return len(response.get("Response", {}).get("Data", {}).get("Items") or [])


def _catalog_table_names(response):
    return sorted(_catalog_tables_by_name(response))


def _catalog_tables_by_name(response):
    return {
        name: item
        for item in response.get("Response", {}).get("Data", {}).get("Items") or []
        for name in [item.get("Name") or item.get("TableName")]
        if name
    }


def _metadata_table_count(metadata_dump):
    return _response_item_count(metadata_dump.get("tables", {}))


def _filter_new_asset_tables(table_names, catalog_tables, start, end):
    if not catalog_tables:
        if os.environ.get("WEDATA_NEW_ASSET_STRICT", "1") == "1":
            raise RuntimeError("WEDATA_NEW_ASSET_START requires WEDATA_SYNC_TABLE_CATALOG=1")
        return []
    window_start = _parse_date(start)
    window_end = _parse_date(end)
    if not any(_item_dates(item) for item in catalog_tables.values()) and os.environ.get("WEDATA_NEW_ASSET_STRICT", "1") == "1":
        raise RuntimeError("ListTable response has no recognized create/update time fields for new asset sync")
    names = set(table_names)
    return sorted(
        name
        for name, item in catalog_tables.items()
        if name in names and any(_date_in_window(value, window_start, window_end) for value in _item_dates(item))
    )


def _item_dates(item):
    dates = []
    date_groups = {part.strip().lower() for part in os.environ.get("WEDATA_NEW_ASSET_DATE_FIELDS", "create").split(",") if part.strip()}
    fields = []
    if "create" in date_groups:
        fields.extend(("CreateTime", "CreateDate", "CreatedAt", "CreateAt", "GmtCreate"))
    if "update" in date_groups:
        fields.extend(("UpdateTime", "ModifyTime", "ModifiedAt", "LastModifyTime"))
    if "structure_update" in date_groups:
        fields.extend(("StructUpdateTime",))
    for field in fields:
        if item.get(field):
            value = _parse_date(str(item[field]))
            if value:
                dates.append(value)
    return dates


def _parse_date(value):
    text = str(value or "").strip()
    if not text:
        return None
    if text.isdigit() and len(text) >= 10:
        return datetime.fromtimestamp(int(text[:10])).date()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:19] if "T" in fmt else text[:10 if fmt == "%Y-%m-%d" else 19], fmt).date()
        except ValueError:
            pass
    return None


def _date_in_window(value, start, end):
    return bool(value and start and end and start <= value <= end)


def _instance_window():
    if os.environ.get("WEDATA_INSTANCE_START") and os.environ.get("WEDATA_INSTANCE_END"):
        return os.environ["WEDATA_INSTANCE_START"], os.environ["WEDATA_INSTANCE_END"]
    days = int(os.environ.get("WEDATA_INSTANCE_LOOKBACK_DAYS", "2"))
    today = datetime.now().date()
    start = today - timedelta(days=max(days, 1) - 1)
    return f"{start:%Y-%m-%d} 00:00:00", f"{today:%Y-%m-%d} 23:59:59"


def _sync_metadata(client, project_id, table_names, page_size, work_dir, catalog_tables=None):
    if os.environ.get("WEDATA_METADATA_TABLES"):
        table_names = [name.strip() for name in os.environ["WEDATA_METADATA_TABLES"].split(",") if name.strip()]
    limit = int(os.environ.get("WEDATA_METADATA_TABLE_LIMIT", "50"))
    table_names = table_names[:limit]
    # ponytail: bounded threads; lower WEDATA_METADATA_WORKERS if Tencent throttles.
    workers = max(1, int(os.environ.get("WEDATA_METADATA_WORKERS", "4")))
    tables = []
    columns = {}
    lineage = []
    quality_rules = []

    total = len(table_names)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(_sync_one_metadata_table, client, project_id, table_name, page_size, (catalog_tables or {}).get(table_name))
            for table_name in table_names
        ]
        for index, future in enumerate(as_completed(futures), start=1):
            table_name, table, column_response, table_lineage, table_quality_rules = future.result()
            if table:
                tables.append(table)
            if column_response:
                columns[table_name] = column_response
            lineage.extend(table_lineage)
            quality_rules.extend(table_quality_rules)
            if index == total or index % 10 == 0:
                print(f"synced metadata for {index}/{total} tables", flush=True)

    payload = {
        "tables": {"Response": {"Data": {"Items": tables}}},
        "lineage": {"Response": {"Data": {"Items": lineage}}},
        "quality_rules": {"Response": {"Data": {"Items": quality_rules}}},
    }
    path = os.path.join(work_dir, "wedata_metadata.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"payload": payload, "columns": columns}, f, ensure_ascii=False, indent=2)
    print(f"saved raw metadata dump to {path}", flush=True)
    return payload


def _sync_one_metadata_table(client, project_id, table_name, page_size, catalog_table=None):
    table = dict(catalog_table or {})
    if not table:
        table_response = client.call("ListTable", {"PageNumber": 1, "PageSize": 20, "Keyword": table_name})
        matches = [item for item in table_response.get("Response", {}).get("Data", {}).get("Items", []) if item.get("Name") == table_name]
        if not matches:
            return table_name, None, None, [], []
        table = matches[0]

    column_response = None
    table_lineage = []
    guid = table.get("Guid")
    if guid:
        column_response = client.call("GetTableColumns", {"TableGuid": guid})
        table["Columns"] = column_response.get("Response", {}).get("Data") or []
        lineage_response = _list_all(
            client,
            "ListLineage",
            {"ResourceUniqueId": guid, "ResourceType": "TABLE", "Direction": "OUTPUT", "Platform": "WEDATA"},
            page_size,
        )
        for item in lineage_response.get("Response", {}).get("Data", {}).get("Items", []) or []:
            item["QueriedTableName"] = table_name
            table_lineage.append(item)

    quality_response = _list_all(
        client,
        "ListQualityRules",
        {"ProjectId": project_id, "Filters": [{"Name": "TableName", "Values": [table_name]}]},
        page_size,
    )
    return table_name, table, column_response, table_lineage, quality_response.get("Response", {}).get("Data", {}).get("Items", []) or []


if __name__ == "__main__":
    main()
