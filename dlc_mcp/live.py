import os
from datetime import datetime, timedelta

from .assets import AssetStore, decode_task_code_info
from .sync_wedata import _list_partitions, _merge_task_responses, _partition_client, _partition_items, _partition_payload, _partition_payload_ready, _sync_related_task_definitions
from .tencentcloud import TencentCloudClient
from .wedata import import_wedata_snapshot, snapshot_from_api_dump


class LiveWeData:
    def __init__(self, store, client=None):
        self.store = store
        self.client = client or TencentCloudClient.wedata_from_env()
        self.project_id = os.environ["WEDATA_PROJECT_ID"]
        self.page_size = max(10, int(os.environ.get("WEDATA_LIVE_PAGE_SIZE", "20")))

    def sync_tasks(self, query):
        data = self._list_all("ListTasks", {"ProjectId": self.project_id, "TaskName": query})
        self._import({"tasks": data})

    def sync_table(self, table_name):
        table_response = self.client.call("ListTable", {"PageNumber": 1, "PageSize": 20, "Keyword": table_name})
        tables = [item for item in table_response.get("Response", {}).get("Data", {}).get("Items", []) if item.get("Name") == table_name]
        if not tables:
            return
        table = tables[0]
        guid = table.get("Guid")
        lineage = []
        if guid:
            table["Columns"] = self.client.call("GetTableColumns", {"TableGuid": guid}).get("Response", {}).get("Data") or []
            lineage_response = self._list_all("ListLineage", {"ResourceUniqueId": guid, "ResourceType": "TABLE", "Direction": "OUTPUT", "Platform": "WEDATA"})
            for item in lineage_response.get("Response", {}).get("Data", {}).get("Items", []) or []:
                item["QueriedTableName"] = table_name
                lineage.append(item)
        quality = self._list_all("ListQualityRules", {"ProjectId": self.project_id, "Filters": [{"Name": "TableName", "Values": [table_name]}]})
        self._import(
            {
                "tables": {"Response": {"Data": {"Items": tables}}},
                "lineage": {"Response": {"Data": {"Items": lineage}}},
                "quality_rules": quality,
            }
        )

    def sync_table_partitions(self, table_name):
        table = self.store._one("select * from tables where name = ?", (table_name,))
        if not table:
            self.sync_table(table_name)
            table = self.store._one("select * from tables where name = ?", (table_name,))
        if not table:
            raise RuntimeError("table_not_found")
        table_data = self.store._table_dict(table)
        catalog_item = {**(table_data.get("raw") or {})}
        if table_data.get("database") and not catalog_item.get("DatabaseName"):
            catalog_item["DatabaseName"] = table_data.get("database")
        payload = _partition_payload(self.project_id, table_name, catalog_item)
        if not _partition_payload_ready(payload):
            raise RuntimeError("missing required partition payload fields")
        action = os.environ.get("WEDATA_PARTITION_ACTION", "ListTablePartitions")
        response = _list_partitions(_partition_client(self.client), action, payload, self.page_size)
        items = _partition_items(response)
        for item in items:
            item["QueriedTableName"] = table_name
        normalized = {"Response": {"Data": {"Items": items}, "PartitionFailures": []}}
        self._import({"table_partitions": normalized})

    def sync_task_runs(self, task_name="", task_id="", instance_date=""):
        start, end = _day_window(instance_date)
        payload = {
            "ProjectId": self.project_id,
            "ScheduleTimeFrom": start,
            "ScheduleTimeTo": end,
            "TimeZone": os.environ.get("WEDATA_INSTANCE_TIMEZONE", "UTC+8"),
        }
        if task_name or task_id:
            payload["Keyword"] = task_name or task_id
        data = self._list_all("ListTaskInstances", payload, max_pages=int(os.environ.get("WEDATA_LIVE_INSTANCE_MAX_PAGES", "5")))
        self._import({"task_instances": data})

    def sync_task_code(self, task_id="", task_name="", project_id=""):
        resolved_project_id = self.project_id_or_default(project_id)
        task = self.store.resolve_task(task_id, task_name)
        if not task and task_name:
            self.sync_tasks(task_name)
            task = self.store.resolve_task("", task_name)
        if not task:
            raise RuntimeError("task_not_found")
        response = self.client.call("GetTaskCode", {"ProjectId": resolved_project_id, "TaskId": task["id"]})
        if "Error" in response.get("Response", {}):
            error = response["Response"]["Error"]
            raise RuntimeError(f"GetTaskCode failed: {error.get('Code')} {error.get('Message')}")
        data = response.get("Response", {}).get("Data", {}) or {}
        code_info = data.get("CodeInfo", "")
        code_text, encoding = decode_task_code_info(code_info)
        self.store.upsert_task_code(
            resolved_project_id,
            task["id"],
            task.get("name") or task_name,
            code_info,
            code_text,
            int(data.get("CodeFileSize") or 0),
            encoding,
            data,
        )

    def sync_data_sources(self, query=""):
        payload = {"ProjectId": self.project_id}
        if query:
            payload["Name"] = query
        data = self._list_all("ListDataSources", payload)
        related = {}
        for item in data.get("Response", {}).get("Data", {}).get("Items") or []:
            data_source_id = item.get("Id") or item.get("DataSourceId") or item.get("DatasourceId")
            if data_source_id:
                related[str(data_source_id)] = self.client.call("GetDataSourceRelatedTasks", {"Id": int(data_source_id)})
        task_definitions = _sync_related_task_definitions(self.client, self.project_id, related, self.page_size)
        payload = {"data_sources": data, "data_source_tasks": related}
        if task_definitions.get("Response", {}).get("Data", {}).get("Items"):
            payload["tasks"] = _merge_task_responses({}, task_definitions)
        self._import(payload)

    def project_id_or_default(self, project_id=""):
        value = project_id or self.project_id
        if not value:
            raise RuntimeError("missing_project_id")
        return value

    def sync_projects(self, query=""):
        payload = {}
        if query:
            payload["Keyword"] = query
        data = self._list_all("ListProjects", payload)
        self._import({"projects": data})

    def sync_project(self, project_id=""):
        resolved_project_id = self.project_id_or_default(project_id)
        data = self.client.call("GetProject", {"ProjectId": resolved_project_id})
        self._import({"projects": data})

    def sync_project_members(self, project_id=""):
        resolved_project_id = self.project_id_or_default(project_id)
        data = self._list_all("ListProjectMembers", {"ProjectId": resolved_project_id})
        self._import({"project_members": {resolved_project_id: data}})

    def sync_task_relations(self, task_id, direction, project_id=""):
        resolved_project_id = self.project_id_or_default(project_id)
        action = "ListDownstreamTasks" if direction == "downstream" else "ListUpstreamTasks"
        data = self._list_all(action, {"ProjectId": resolved_project_id, "TaskId": task_id})
        self._import({"task_relations": {f"{resolved_project_id}:{task_id}:{direction}": data}})

    def sync_table_detail(self, table_name="", table_guid="", project_id=""):
        if not table_guid:
            raise RuntimeError("table_guid_required")
        payload = {"TableGuid": table_guid}
        data = self.client.call("GetTable", payload)
        self._import({"tables": data})

    def _list_all(self, action, payload, max_pages=None):
        first = self.client.call(action, {**payload, "PageNumber": 1, "PageSize": self.page_size})
        if "Error" in first.get("Response", {}):
            error = first["Response"]["Error"]
            raise RuntimeError(f"{action} failed: {error.get('Code')} {error.get('Message')}")
        data = first.get("Response", {}).get("Data", {})
        total_pages = int(data.get("TotalPageNumber") or data.get("PageCount") or _pages_from_total(data, self.page_size) or 1)
        stop_page = min(total_pages, max_pages or total_pages)
        items = list(data.get("Items") or [])
        for page in range(2, stop_page + 1):
            response = self.client.call(action, {**payload, "PageNumber": page, "PageSize": self.page_size})
            items.extend(response.get("Response", {}).get("Data", {}).get("Items") or [])
        first["Response"]["Data"]["Items"] = items
        return first

    def _import(self, dump):
        import_wedata_snapshot(self.store, snapshot_from_api_dump(dump))


def _day_window(instance_date):
    if instance_date:
        day = instance_date[:10]
        return f"{day} 00:00:00", f"{day} 23:59:59"
    today = datetime.now().date()
    yesterday = today - timedelta(days=1)
    return f"{yesterday:%Y-%m-%d} 00:00:00", f"{today:%Y-%m-%d} 23:59:59"


def _pages_from_total(data, page_size):
    total = int(data.get("TotalCount") or 0)
    return (total + page_size - 1) // page_size if total else 0
