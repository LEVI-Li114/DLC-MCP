import json
import os
import re
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

    for partition in snapshot.get("table_partitions", []):
        store.upsert_table_partition(partition)

    for data_source in snapshot.get("data_sources", []):
        store.upsert_data_source(data_source)

    for item in snapshot.get("data_source_tasks", []):
        store.replace_data_source_tasks(item["data_source_id"], item.get("tasks", []))


def snapshot_from_api_dump(dump):
    tasks = [_task_from_api(item) for item in _items(dump.get("tasks", {}))]
    tables = [_table_from_api(item) for item in _items(dump.get("tables", {}))]
    data_sources = [_data_source_from_api(item) for item in _items(dump.get("data_sources", {}))]
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
        "table_partitions": [_partition_from_api(item) for item in _items(dump.get("table_partitions", {}))],
        "data_sources": data_sources + _builtin_data_sources(tables, data_sources),
        "data_source_tasks": _data_source_tasks_from_dump(dump.get("data_source_tasks", {})),
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
    data_source_id = _get(item, "DatasourceId", "DataSourceId", "DatasourceID", "DataSourceID", default="")
    data_source_type = _get(item, "DatasourceType", "DataSourceType", default="")
    return {
        "name": name,
        "guid": _get(item, "Guid", "TableGuid", "TableId", "id"),
        "data_source_id": str(data_source_id or data_source_type or ""),
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
        "cycle": _get(item, "CycleType", "Cycle", "CycleUnit", "cycle"),
        "schedule_time": _task_schedule_time(item),
        "schedule_desc": _task_schedule_desc(item),
        "owner": str(_get(item, "Owner", "OwnerName", "OwnerUin", "ResponsibleUser", "owner")),
        "status": _get(item, "Status", "TaskLatestVersionStatus", "State", "status"),
        "inputs": _task_table_names(item, "input"),
        "outputs": _task_table_names(item, "output"),
    }


def _task_schedule_time(item):
    return _get(
        item,
        "ScheduleTime",
        "SchedulerTime",
        "TriggerTime",
        "CrontabExpression",
        "CronExpression",
        "StartTime",
        "ExecutionStartTime",
    )


def _task_schedule_desc(item):
    desc = _get(item, "ScheduleDesc", "CycleDesc", "ScheduleDescription", "TaskAction")
    if desc:
        return desc
    parts = [
        _get(item, "CycleType", "Cycle", "CycleUnit"),
        _get(item, "ScheduleTime", "SchedulerTime", "TriggerTime", "CrontabExpression", "CronExpression"),
    ]
    return " ".join(str(part) for part in parts if part)


INPUT_TABLE_FIELDS = (
    "Inputs",
    "InputTables",
    "InputTableList",
    "InputTableNames",
    "SourceTables",
    "SourceTableList",
    "SourceTableNames",
    "Sources",
    "ReadTables",
    "ReadTableList",
    "DependencyTables",
    "DependencyTableList",
    "UpstreamTables",
)

OUTPUT_TABLE_FIELDS = (
    "Outputs",
    "OutputTables",
    "OutputTableList",
    "OutputTableNames",
    "TargetTables",
    "TargetTableList",
    "TargetTableNames",
    "Targets",
    "WriteTables",
    "WriteTableList",
    "SinkTables",
    "ResultTables",
    "DownstreamTables",
)

TABLE_NAME_FIELDS = (
    "TableName",
    "Name",
    "tableName",
    "name",
    "Table",
    "table",
    "SourceTable",
    "TargetTable",
    "DbTableName",
    "DatabaseTable",
    "ResourceName",
)


def _task_table_names(item, direction):
    fields = INPUT_TABLE_FIELDS if direction == "input" else OUTPUT_TABLE_FIELDS
    names = []
    for field in fields:
        names.extend(_table_names_from_value(item.get(field)))
    config = item.get("DependencyConfig") or item.get("TaskDependency") or item.get("Dependency") or {}
    if isinstance(config, str):
        config = _json_dict(config)
    if isinstance(config, dict):
        config_fields = INPUT_TABLE_FIELDS if direction == "input" else OUTPUT_TABLE_FIELDS
        for field in config_fields:
            names.extend(_table_names_from_value(config.get(field)))
    if not names:
        names.extend(_sql_table_names(_task_sql_text(item), direction))
    return _dedupe_table_names(names)


def _table_names_from_value(value):
    if value is None or value == "":
        return []
    if isinstance(value, str):
        stripped = value.strip()
        parsed = None
        if stripped.startswith(("[", "{")):
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                parsed = None
        if parsed is not None:
            return _table_names_from_value(parsed)
        return [_normalize_table_name(part) for part in re.split(r"[,;\n\s]+", stripped) if _normalize_table_name(part)]
    if isinstance(value, dict):
        for field in TABLE_NAME_FIELDS:
            if value.get(field):
                return _table_names_from_value(value[field])
        names = []
        for field in INPUT_TABLE_FIELDS + OUTPUT_TABLE_FIELDS + ("Items", "List", "Tables", "tables"):
            if field in value:
                names.extend(_table_names_from_value(value[field]))
        return names
    if isinstance(value, list):
        names = []
        for item in value:
            names.extend(_table_names_from_value(item))
        return names
    return [_normalize_table_name(str(value))]


def _normalize_table_name(name):
    value = str(name or "").strip().strip("`'\"")
    if not value:
        return ""
    value = value.split(".")[-1]
    if value.startswith(("${", "$[")):
        return ""
    return value if _layer_from_name(value) or "_" in value else ""


def _dedupe_table_names(names):
    result = []
    seen = set()
    for name in names:
        if name and name not in seen:
            seen.add(name)
            result.append(name)
    return result


SQL_FIELDS = (
    "Sql",
    "SQL",
    "SqlContent",
    "ScriptContent",
    "Content",
    "TaskContent",
    "CodeContent",
    "TaskSql",
    "QuerySql",
)


def _task_sql_text(item):
    chunks = []
    for field in SQL_FIELDS:
        value = item.get(field)
        if isinstance(value, str) and value.strip():
            chunks.append(value)
    for container in (item.get("TaskExt") or {}, item.get("Properties") or {}, item.get("Params") or {}):
        if isinstance(container, str):
            container = _json_dict(container)
        if isinstance(container, dict):
            for field in SQL_FIELDS:
                value = container.get(field)
                if isinstance(value, str) and value.strip():
                    chunks.append(value)
    return "\n".join(chunks)


def _sql_table_names(sql, direction):
    if not sql:
        return []
    text = _strip_sql_comments(sql)
    if direction == "output":
        patterns = [
            r"\binsert\s+(?:overwrite\s+|into\s+)?(?:table\s+)?([`\w.]+)",
            r"\bcreate\s+(?:or\s+replace\s+)?table\s+([`\w.]+)",
        ]
    else:
        patterns = [r"\bfrom\s+([`\w.]+)", r"\bjoin\s+([`\w.]+)"]
    names = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            name = _normalize_table_name(match.group(1))
            if name and not _is_sql_keyword_name(name):
                names.append(name)
    return _dedupe_table_names(names)


def _strip_sql_comments(sql):
    text = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    text = re.sub(r"--.*?$", " ", text, flags=re.MULTILINE)
    return text


def _is_sql_keyword_name(name):
    return name.lower() in {"select", "where", "lateral", "values", "unnest"}


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


def _partition_from_api(item):
    table_name = _get(item, "QueriedTableName", "TableName", "Name", "tableName")
    partition_name = _get(item, "PartitionName", "Partition", "PartitionSpec", "Name", "partitionName")
    return {
        "table_name": table_name,
        "partition_name": partition_name,
        "partition_date": _get(item, "PartitionDate", "Dt", "Date", "BizDate", "partitionDate", default=_date_from_partition_name(partition_name)),
        "row_count": _get(item, "RowCount", "Rows", "RecordCount", "rowCount", default=0),
        "storage_bytes": _get(item, "StorageBytes", "StorageSize", "SizeBytes", "storageBytes", default=0),
        "file_count": _get(item, "FileCount", "Files", "fileCount", default=0),
        "updated_at": _get(item, "UpdateTime", "ModifiedTime", "LastModifyTime", "updatedAt"),
        "collected_at": _get(item, "CollectedAt", "CreateTime", "createTime"),
    }


def _data_source_from_api(item):
    config_source = _json_dict(_get(item, "ProdConProperties", "DevConProperties", default=""))
    config = {}
    for source_key, target_key in (
        ("Host", "host"),
        ("ip", "host"),
        ("vip", "vip"),
        ("Port", "port"),
        ("port", "port"),
        ("DatabaseName", "database"),
        ("DbName", "database"),
        ("db", "database"),
        ("VpcId", "vpc_id"),
        ("vpcId", "vpc_id"),
        ("url", "url"),
        ("vurl", "vurl"),
        ("region", "region"),
        ("username", "username"),
    ):
        value = _get(item, source_key, default=None)
        if value is None and config_source:
            value = config_source.get(source_key)
        if value is not None:
            config[target_key] = value
    return {
        "id": str(_get(item, "DataSourceId", "DatasourceId", "Id", "id")),
        "name": _get(item, "DataSourceName", "DatasourceName", "Name", "name"),
        "type": _get(item, "Type", "DataSourceType", "DatasourceType", "type"),
        "owner": _get(item, "Owner", "OwnerName", "OwnerUin", "CreateUser", "owner"),
        "description": _get(item, "Description", "Remark", "Comment", "description"),
        "config": config,
    }


def _builtin_data_sources(tables, data_sources):
    existing = {source["id"] for source in data_sources}
    missing = sorted({table.get("data_source_id") for table in tables if table.get("data_source_id")} - existing)
    return [{"id": source_id, "name": source_id, "type": source_id, "owner": "", "description": "WeData table catalog source", "config": {}} for source_id in missing]


def _data_source_tasks_from_dump(value):
    items = value.items() if isinstance(value, dict) else []
    return [{"data_source_id": str(data_source_id), "tasks": _related_tasks_from_api(response)} for data_source_id, response in items]


def _related_tasks_from_api(response):
    tasks = []
    for project in response.get("Response", {}).get("Data") or []:
        for group in project.get("TaskInfo") or []:
            for item in group.get("TaskList") or []:
                tasks.append(
                    {
                        "task_id": str(_get(item, "TaskId", "Id", "id")),
                        "task_name": _get(item, "TaskName", "Name", "name"),
                        "task_type": _get(group, "TaskType", "type"),
                        "project_id": str(project.get("ProjectId") or ""),
                        "project_name": project.get("ProjectName") or "",
                        "create_time": item.get("CreateTime") or "",
                        "owner": ",".join(item.get("OwnerUinList") or []),
                    }
                )
    return tasks


def _json_dict(value):
    if not value:
        return {}
    try:
        data = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _duration_seconds(item, cost_time):
    if cost_time is not None:
        return int((int(cost_time) or 0) / 1000)
    return int(_get(item, "CostSeconds", "DurationSeconds", "duration_seconds", default=0) or 0)


def _date_from_partition_name(name):
    match = re.search(r"\d{4}-\d{2}-\d{2}|\d{8}", str(name or ""))
    if not match:
        return ""
    value = match.group(0)
    return f"{value[:4]}-{value[4:6]}-{value[6:8]}" if len(value) == 8 else value


def _layer_from_name(name):
    prefix = (name or "").split("_", 1)[0].lower()
    return prefix if prefix in {"ods", "dim", "dwd", "dws", "ads"} else ""


def _resource_table_name(resource):
    props = {item.get("Name"): item.get("Value") for item in resource.get("ResourceProperties") or []}
    return props.get("TableName") or (resource.get("ResourceName") or "").split(".")[-1]


def _process_ids(relation):
    ids = [str(process.get("ProcessId")) for process in relation.get("Processes") or [] if process.get("ProcessId")]
    return ",".join(ids)
