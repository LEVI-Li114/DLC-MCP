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
    return {
        "tables": [_table_from_api(item) for item in _items(dump.get("tables", {}))],
        "tasks": [_task_from_api(item) for item in _items(dump.get("tasks", {}))],
        "task_instances": [_task_instance_from_api(item) for item in _items(dump.get("task_instances", {}))],
        "data_sources": [_data_source_from_api(item) for item in _items(dump.get("data_sources", {}))],
        "lineage": [_lineage_from_api(item) for item in _items(dump.get("lineage", {}))],
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
    return {
        "name": _get(item, "TableName", "Name", "tableName", "name"),
        "database": _get(item, "DatabaseName", "Database", "DbName", "database"),
        "layer": _get(item, "Layer", "TableLayer", "layer"),
        "domain": _get(item, "Domain", "BizDomain", "domain"),
        "owner": _get(item, "Owner", "OwnerName", "ResponsibleUser", "owner"),
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


def _lineage_from_api(item):
    return {
        "upstream": _get(item, "Upstream", "Source", "SourceTable", "upstream"),
        "downstream": _get(item, "Downstream", "Target", "TargetTable", "downstream"),
        "via": _get(item, "Via", "TaskName", "TaskId", "via"),
    }


def _quality_rule_from_api(item):
    return {
        "table_name": _get(item, "TableName", "tableName"),
        "rule_name": _get(item, "RuleName", "Name", "ruleName"),
        "rule_type": _get(item, "RuleType", "Type", "ruleType"),
        "target": _get(item, "Target", "ColumnName", "FieldName", "target"),
        "enabled": bool(_get(item, "Enabled", "IsEnabled", "enabled", default=True)),
        "last_status": _get(item, "LastStatus", "Status", "lastStatus"),
        "last_checked_at": _get(item, "LastCheckedAt", "CheckTime", "lastCheckedAt"),
    }


def _task_instance_from_api(item):
    return {
        "task_id": str(_get(item, "TaskId", "TaskID", "taskId")),
        "instance_id": str(_get(item, "InstanceId", "InstanceID", "Id", "id")),
        "instance_date": _get(item, "InstanceDate", "CurRunDate", "ScheduleTime", "instanceDate"),
        "start_time": _get(item, "StartTime", "StartDate", "startTime"),
        "end_time": _get(item, "EndTime", "EndDate", "endTime"),
        "duration_seconds": int(_get(item, "CostTime", "CostSeconds", "DurationSeconds", "duration_seconds", default=0) or 0),
        "status": _get(item, "Status", "State", "ExecutionStatus", "status"),
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
