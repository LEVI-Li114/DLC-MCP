import json
import os
import sqlite3

from .assets import AssetStore


def import_wedata_snapshot(store, snapshot):
    for table in snapshot.get("tables", []):
        store.upsert_table(table)
        for index, column in enumerate(table.get("columns", []), start=1):
            store.upsert_column(
                table["name"],
                column["name"],
                column.get("type", ""),
                column.get("description", ""),
                column.get("ordinal", index),
            )

    for task in snapshot.get("tasks", []):
        store.upsert_task(task)
        for output in task.get("outputs", []):
            for input_table in task.get("inputs", []):
                store.upsert_lineage(input_table, output, task.get("name") or task["id"])

    for edge in snapshot.get("lineage", []):
        store.upsert_lineage(edge["upstream"], edge["downstream"], edge.get("via", ""))

    for rule in snapshot.get("quality_rules", []):
        store.upsert_quality_rule(rule)

    for run in snapshot.get("task_instances", []):
        store.upsert_task_run(run)

    for data_source in snapshot.get("data_sources", []):
        store.upsert_data_source(data_source)


def snapshot_from_api_dump(dump):
    tasks = [_task_from_api(item) for item in _items(dump.get("tasks", {}))]
    tables = [_table_from_api(item) for item in _items(dump.get("tables", {}))]
    existing_tables = {table["name"] for table in tables if table["name"]}
    for task in tasks:
        table_name = _derived_output_table(task["name"])
        if table_name and not task["outputs"]:
            task["outputs"] = [table_name]
        if table_name and table_name not in existing_tables:
            tables.append(_table_from_task(task, table_name))
            existing_tables.add(table_name)
    return {
        "tables": tables,
        "tasks": tasks,
        "task_instances": [_task_instance_from_api(item) for item in _items(dump.get("task_instances", {}))],
        "data_sources": [_data_source_from_api(item) for item in _items(dump.get("data_sources", {}))],
        "lineage": [edge for edge in (_lineage_from_api(item) for item in _items(dump.get("lineage", {}))) if edge["upstream"] and edge["downstream"] and edge["upstream"] != edge["downstream"]],
        "quality_rules": [_quality_rule_from_api(item) for item in _items(dump.get("quality_rules", {}))],
    }


def import_snapshot_file(db_path, snapshot_path):
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    with open(snapshot_path, "r", encoding="utf-8") as f:
        snapshot = json.load(f)
    store = AssetStore(sqlite3.connect(db_path))
    store.init_schema()
    import_wedata_snapshot(store, snapshot)
    return db_path


def _items(response):
    data = response.get("Response", response)
    for key in ("Data", "Result"):
        if isinstance(data, dict) and key in data:
            data = data[key]
    if isinstance(data, dict):
        for key in ("Items", "Rows", "List", "Records"):
            if isinstance(data.get(key), list):
                return data[key]
    return data if isinstance(data, list) else []


def _get(item, *names, default=""):
    for name in names:
        if name in item and item[name] is not None:
            return item[name]
    return default


def _table_from_api(item):
    name = _get(item, "TableName", "Name", "tableName", "name")
    metadata = item.get("TechnicalMetadata") or {}
    return {
        "name": name,
        "guid": _get(item, "Guid", "TableGuid", "TableId", "id"),
        "database": _get(item, "DatabaseName", "Database", "DbName", "database"),
        "layer": _get(item, "Layer", "TableLayer", "layer", default=_layer_from_name(name)),
        "domain": _get(item, "Domain", "BizDomain", "domain", default=_domain_from_tokens(name.lower().split("_"))),
        "owner": _get(item, "Owner", "OwnerName", "ResponsibleUser", "owner", default=metadata.get("Owner") or ""),
        "description": _get(item, "Description", "Comment", "description"),
        "columns": [_column_from_api(column) for column in _get(item, "Columns", "ColumnList", "columns", default=[])],
    }


def _column_from_api(item):
    return {
        "name": _get(item, "ColumnName", "Name", "name"),
        "type": _get(item, "ColumnType", "Type", "type"),
        "description": _get(item, "Description", "Comment", "description"),
        "ordinal": _get(item, "Ordinal", "Position", "ordinal", default=0),
    }


def _task_from_api(item):
    return {
        "id": str(_get(item, "TaskId", "Id", "id")),
        "name": _get(item, "TaskName", "Name", "name"),
        "task_type": str(_get(item, "TaskType", "TaskTypeId", "Type", "taskType")),
        "cycle": _get(item, "CycleType", "Cycle", "cycle"),
        "owner": str(_get(item, "Owner", "OwnerName", "OwnerUin", "ResponsibleUser", "owner")),
        "status": _get(item, "Status", "TaskLatestVersionStatus", "State", "status"),
        "inputs": _get(item, "Inputs", "InputTables", "inputs", default=[]),
        "outputs": _get(item, "Outputs", "OutputTables", "outputs", default=[]),
    }


def _derived_output_table(task_name):
    name = (task_name or "").strip()
    for prefix in ("build_", "etl_", "sync_"):
        if name.startswith(prefix):
            name = name[len(prefix):]
    if name.endswith(("_check", "_kafka", "_back", "_bak", "_tmp", "_test")):
        return ""
    if name.split("_", 1)[0] in {"ods", "dim", "dwd", "dws", "ads"}:
        return name
    return ""


def _table_from_task(task, table_name):
    tokens = table_name.lower().split("_")
    return {
        "name": table_name,
        "database": "",
        "layer": tokens[0],
        "domain": _domain_from_tokens(tokens),
        "owner": task.get("owner", ""),
        "description": f"Derived from WeData task {task.get('name', '')}",
    }


def _domain_from_tokens(tokens):
    if {"fin", "finance", "bill", "revenue", "pay", "income"} & set(tokens):
        return "finance"
    if {"customer", "user", "member"} & set(tokens):
        return "customer"
    if {"order", "trade"} & set(tokens):
        return "order"
    if {"biz", "business"} & set(tokens):
        return "business"
    return ""


def _lineage_from_api(item):
    resource = item.get("Resource") or {}
    return {
        "upstream": _get(item, "QueriedTableName", "Upstream", "Source", "SourceTable", "upstream"),
        "downstream": _resource_table_name(resource) or _get(item, "Downstream", "Target", "TargetTable", "downstream"),
        "via": _process_ids(item.get("Relation") or {}) or _get(item, "Via", "TaskName", "TaskId", "via"),
    }


def _quality_rule_from_api(item):
    return {
        "table_name": _get(item, "TableName", "tableName"),
        "rule_name": _get(item, "RuleName", "Name", "ruleName", default=str(_get(item, "RuleId", default=""))),
        "rule_type": str(_get(item, "RuleType", "RuleTemplateContent", "Type", "ruleType")),
        "target": _get(item, "Target", "ColumnName", "FieldName", "SourceObjectValue", "target"),
        "enabled": _get(item, "MonitorStatus", "Enabled", "IsEnabled", "enabled", default=True) not in (False, 0, "0", "false"),
        "last_status": _get(item, "LastStatus", "Status", "DeployStatus", "lastStatus", default="configured"),
        "last_checked_at": _get(item, "LastCheckedAt", "CheckTime", "UpdateTime", "lastCheckedAt"),
    }


def _task_instance_from_api(item):
    cost_time = _get(item, "CostTime", default=None)
    return {
        "task_id": str(_get(item, "TaskId", "TaskID", "taskId")),
        "instance_id": str(_get(item, "InstanceId", "InstanceID", "InstanceKey", "Id", "id")),
        "instance_date": _get(item, "InstanceDate", "CurRunDate", "SchedulerTime", "ScheduleTime", "instanceDate"),
        "start_time": _get(item, "StartTime", "StartDate", "startTime"),
        "end_time": _get(item, "EndTime", "EndDate", "endTime"),
        "duration_seconds": _duration_seconds(item, cost_time),
        "status": _get(item, "Status", "State", "ExecutionStatus", "InstanceState", "status"),
    }


def _data_source_from_api(item):
    config = {}
    for source_key, target_key in (("Host", "host"), ("Port", "port"), ("DatabaseName", "database"), ("DbName", "database"), ("VpcId", "vpc_id")):
        value = _get(item, source_key, default=None)
        if value is not None:
            config[target_key] = value
    return {
        "id": str(_get(item, "DataSourceId", "DatasourceId", "Id", "id")),
        "name": _get(item, "DataSourceName", "DatasourceName", "Name", "name"),
        "type": _get(item, "Type", "DataSourceType", "DatasourceType", "type"),
        "owner": _get(item, "Owner", "OwnerName", "OwnerUin", "owner"),
        "description": _get(item, "Description", "Remark", "Comment", "description"),
        "config": config,
    }


def _duration_seconds(item, cost_time):
    if cost_time is not None:
        return int((int(cost_time) or 0) / 1000)
    return int(_get(item, "CostSeconds", "DurationSeconds", "duration_seconds", default=0) or 0)


def _layer_from_name(name):
    prefix = (name or "").split("_", 1)[0].lower()
    return prefix if prefix in {"ods", "dim", "dwd", "dws", "ads"} else ""


def _resource_table_name(resource):
    props = {item.get("Name"): item.get("Value") for item in resource.get("ResourceProperties") or []}
    return props.get("TableName") or (resource.get("ResourceName") or "").split(".")[-1]


def _process_ids(relation):
    ids = [str(process.get("ProcessId")) for process in relation.get("Processes") or [] if process.get("ProcessId")]
    return ",".join(ids)
