import base64
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
                store.upsert_lineage(input_table, output, task.get("name") or task["id"], "wedata_task_payload", "medium")

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

    for project in snapshot.get("projects", []):
        store.upsert_project(project)

    for item in snapshot.get("project_members", []):
        store.replace_project_members(item["project_id"], item.get("members", []))

    for item in snapshot.get("task_relations", []):
        store.replace_task_relations(item["project_id"], item["task_id"], item["direction"], item.get("relations", []))


def snapshot_from_api_dump(dump):
    tasks = [_task_from_api(item) for item in _items(dump.get("tasks", {}))]
    tables = [_table_from_api(item) for item in _items(dump.get("tables", {}))]
    data_sources = [_data_source_from_api(item) for item in _items(dump.get("data_sources", {}))]
    return {
        "tables": tables,
        "tasks": tasks,
        "task_instances": [_task_instance_from_api(item) for item in _items(dump.get("task_instances", {}))],
        "table_partitions": [_partition_from_api(item) for item in _items(dump.get("table_partitions", {}))],
        "data_sources": data_sources + _builtin_data_sources(tables, data_sources),
        "data_source_tasks": _data_source_tasks_from_dump(dump.get("data_source_tasks", {})),
        "projects": [_project_from_api(item) for item in _items(dump.get("projects", {}))],
        "project_members": _project_members_from_dump(dump.get("project_members", {})),
        "task_relations": _task_relations_from_dump(dump.get("task_relations", {})),
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
        for key in ("Project", "Table", "Detail"):
            if isinstance(data.get(key), dict):
                return [data[key]]
        if any(name in data for name in ("ProjectId", "TableName", "Guid", "Name")):
            return [data]
    return data if isinstance(data, list) else []


def _get(item, *names, default=""):
    for name in names:
        if name in item and item[name] is not None:
            return item[name]
    return default


def _table_from_api(item):
    name = _normalize_table_name(_get(item, "TableName", "Name", "tableName", "name"))
    metadata = item.get("TechnicalMetadata") or {}
    data_source_id = _get(item, "DatasourceId", "DataSourceId", "DatasourceID", "DataSourceID", default="")
    data_source_type = _get(item, "DatasourceType", "DataSourceType", default="")
    database = _get(item, "DatabaseName", "Database", "DbName", "SchemaName", "database")
    return {
        "name": name,
        "guid": _get(item, "Guid", "TableGuid", "TableId", "id"),
        "data_source_id": str(data_source_id or data_source_type or ""),
        "database": database,
        "layer": _table_layer(item, name, database),
        "domain": _get(item, "Domain", "BizDomain", "domain", default=_domain_from_tokens(name.lower().split("_"))),
        "owner": _get(item, "Owner", "OwnerName", "ResponsibleUser", "owner", default=metadata.get("Owner") or ""),
        "description": _get(item, "Description", "Comment", "description"),
        "project_id": str(_get(item, "ProjectId", "ProjectID", "projectId", default="")),
        "table_type": _get(item, "TableType", "Type", "TableKind", "tableType"),
        "catalog_name": _get(item, "CatalogName", "Catalog", "catalogName"),
        "schema_name": _get(item, "SchemaName", "Schema", "schemaName", default=database),
        "columns": [_column_from_api(column) for column in _get(item, "Columns", "ColumnList", "columns", default=[])],
        "raw": item,
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
    for document in _task_config_documents(item):
        node_type = str(document.get("NodeType") or "").upper()
        if node_type and node_type != direction.upper():
            continue
        for field in fields:
            names.extend(_table_names_from_value(document.get(field)))
        config = document.get("DependencyConfig") or document.get("TaskDependency") or document.get("Dependency") or {}
        if isinstance(config, str):
            config = _json_dict(config)
        if isinstance(config, dict):
            for field in fields:
                names.extend(_table_names_from_value(config.get(field)))
        names.extend(_table_names_from_named_config(document.get("Config"), direction))
    if not names:
        names.extend(_sql_table_names(_task_sql_text(item), direction))
    return _dedupe_table_names(names)


def _task_config_documents(item):
    documents = [item]
    for field in ("TaskConfiguration", "Configuration"):
        value = item.get(field)
        if isinstance(value, str):
            value = _json_dict(value)
        if isinstance(value, dict):
            documents.append(value)
    code = item.get("CodeContent")
    if isinstance(code, str) and code.strip():
        decoded = _decode_json_content(code)
        if isinstance(decoded, list):
            documents.extend(value for value in decoded if isinstance(value, dict))
        elif isinstance(decoded, dict):
            documents.append(decoded)
    return documents


def _decode_json_content(value):
    for candidate in (value, _decode_base64(value)):
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
    return None


def _decode_base64(value):
    try:
        return base64.b64decode(value, validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return ""


def _table_names_from_named_config(config, direction):
    if not isinstance(config, list):
        return []
    values = {str(item.get("Name") or ""): item.get("Value") for item in config if isinstance(item, dict)}
    node_tables = values.get("TableNames") or values.get("TableName") or values.get("TableId")
    return _table_names_from_value(node_tables) if node_tables else []


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
    value = value.replace("`.", ".").replace(".`", ".").replace("`", "")
    value = value.split(".")[-1].strip().strip("`'\"")
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
    for document in _task_config_documents(item):
        for field in SQL_FIELDS:
            value = document.get(field)
            if not isinstance(value, str) or not value.strip():
                continue
            if field == "CodeContent":
                if _decode_json_content(value) is not None:
                    continue
                chunks.append(_decode_base64(value) or value)
            else:
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
        "table_name": _normalize_table_name(_get(item, "TableName", "DatasourceTableName", "RuleTableName", "ObjectName", "SourceObjectDataName", "Table", "tableName", "QueriedTableName")),
        "rule_name": _get(item, "RuleName", "Name", "RuleTemplateName", "TemplateName", "ruleName", default=str(_get(item, "RuleId", "RuleIdStr", "Id", default=""))),
        "rule_type": str(_get(item, "RuleType", "RuleTemplateContent", "CompareRule", "RuleTemplateType", "Type", "ruleType")),
        "target": _get(item, "Target", "ColumnName", "FieldName", "FieldConfig", "SourceObjectValue", "SourceObjectValueName", "target"),
        "enabled": _get(item, "MonitorStatus", "Enabled", "IsEnabled", "enabled", default=True) not in (False, 0, "0", "false"),
        "last_status": _get(item, "LastStatus", "Status", "DeployStatus", "QualityDim", "lastStatus", default="configured"),
        "last_checked_at": _get(item, "LastCheckedAt", "CheckTime", "UpdateTime", "LastExecTime", "lastCheckedAt"),
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
        "row_count": _get(item, "RowCount", "Rows", "Records", "RecordCount", "rowCount", default=0),
        "storage_bytes": _get(item, "StorageBytes", "StorageSize", "DataFileStorage", "SizeBytes", "storageBytes", default=0),
        "file_count": _get(item, "FileCount", "Files", "DataFileSize", "fileCount", default=0),
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


def _project_from_api(item):
    project_id = str(_get(item, "ProjectId", "Id", "id"))
    return {
        "id": project_id,
        "name": _get(item, "ProjectName", "Name", "name"),
        "display_name": _get(item, "DisplayName", "Display", "Name", "ProjectName", "name"),
        "description": _get(item, "Description", "Desc", "description"),
        "owner": str(_get(item, "Owner", "OwnerName", "CreateUser", "Creator", "AdminUser", "owner")),
        "status": str(_get(item, "Status", "State", "ProjectStatus", "status")),
        "region": _get(item, "Region", "RegionId", "Area", "region"),
        "create_time": _get(item, "CreateTime", "CreatedAt", "CreateDate", "createTime"),
        "update_time": _get(item, "UpdateTime", "UpdatedAt", "ModifyTime", "updateTime"),
        "raw": item,
    }


def _project_members_from_dump(value):
    if not isinstance(value, dict):
        return []
    results = []
    for project_id, response in value.items():
        members = [_project_member_from_api(item) for item in _items(response)]
        results.append({"project_id": str(project_id), "members": members})
    return results


def _project_member_from_api(item):
    member_id = str(_get(item, "MemberId", "UserId", "UserUin", "Uin", "Id", "id"))
    role_id = str(_get(item, "RoleId", "ProjectRoleId", "roleId", default=""))
    if not role_id:
        role_id = _get(item, "RoleName", "ProjectRoleName", "roleName", default="")
    return {
        "member_id": member_id,
        "member_name": _get(item, "MemberName", "UserName", "Name", "UserAlias", "name"),
        "display_name": _get(item, "DisplayName", "NickName", "UserDisplayName", "UserName", "Name"),
        "role_name": _get(item, "RoleName", "ProjectRoleName", "roleName"),
        "role_id": str(role_id),
        "member_type": _get(item, "MemberType", "UserType", "Type", "type"),
        "join_time": _get(item, "JoinTime", "CreateTime", "CreatedAt", "createTime"),
        "raw": item,
    }


def _task_relations_from_dump(value):
    if not isinstance(value, dict):
        return []
    results = []
    for key, response in value.items():
        parts = str(key).split(":", 2)
        if len(parts) != 3:
            continue
        project_id, task_id, direction = parts
        results.append(
            {
                "project_id": project_id,
                "task_id": task_id,
                "direction": direction,
                "relations": [_task_relation_from_api(item, task_id) for item in _items(response)],
            }
        )
    return results


def _task_relation_from_api(item, source_task_id):
    related_task_id = str(_get(item, "TaskId", "RelatedTaskId", "Id", "id"))
    return {
        "related_task_id": related_task_id,
        "task_name": _get(item, "SourceTaskName", "CurrentTaskName", default=""),
        "related_task_name": _get(item, "TaskName", "RelatedTaskName", "Name", "name"),
        "dependency_type": _get(item, "DependencyType", "Dependency", "Type", "type"),
        "task_type": str(_get(item, "TaskType", "TaskTypeId", "type", default="")),
        "owner": str(_get(item, "Owner", "OwnerName", "ResponsibleUser", "owner")),
        "status": str(_get(item, "Status", "State", "TaskLatestVersionStatus", "status")),
        "raw": item,
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


def _table_layer(item, name, database):
    explicit = _get(item, "Layer", "TableLayer", "BizLayer", "DataLayer", "layer")
    for value in (
        explicit,
        database,
        _get(item, "FolderName", "FolderPath", "CategoryName", "ProjectName"),
        _get(item, "DatasourceName", "DataSourceName"),
        name,
    ):
        layer = _layer_from_text(value)
        if layer:
            return layer
    return ""


def _layer_from_name(name):
    return _layer_from_text(name)


def _layer_from_text(value):
    text = str(value or "").lower().replace("-", "_").replace("/", "_").replace(".", "_")
    parts = [part for part in text.split("_") if part]
    for part in parts:
        if part in {"ods", "dim", "dwd", "dws", "ads"}:
            return part
    return ""


def _resource_table_name(resource):
    props = {item.get("Name"): item.get("Value") for item in resource.get("ResourceProperties") or []}
    return props.get("TableName") or (resource.get("ResourceName") or "").split(".")[-1]


def _process_ids(relation):
    ids = [str(process.get("ProcessId")) for process in relation.get("Processes") or [] if process.get("ProcessId")]
    return ",".join(ids)
