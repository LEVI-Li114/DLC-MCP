import json


TOOLS = {
    "search_assets": {
        "description": "Search tables by name, domain, or description.",
        "schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    },
    "search_tasks": {
        "description": "Search WeData ETL tasks by id, name, owner, or status.",
        "schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    },
    "get_table_profile": {
        "description": "Return table metadata, columns, lineage, quality status, and core-table decision.",
        "schema": {"type": "object", "properties": {"table_name": {"type": "string"}}, "required": ["table_name"]},
    },
    "list_table_columns": {
        "description": "List fields for a table.",
        "schema": {"type": "object", "properties": {"table_name": {"type": "string"}}, "required": ["table_name"]},
    },
    "get_quality_status": {
        "description": "Return quality monitoring rules and latest status for a table.",
        "schema": {"type": "object", "properties": {"table_name": {"type": "string"}}, "required": ["table_name"]},
    },
    "get_table_lineage": {
        "description": "Return upstream and downstream assets for a table.",
        "schema": {"type": "object", "properties": {"table_name": {"type": "string"}}, "required": ["table_name"]},
    },
    "get_table_tasks": {
        "description": "Return ETL tasks that read from or produce a table.",
        "schema": {"type": "object", "properties": {"table_name": {"type": "string"}}, "required": ["table_name"]},
    },
    "get_task_runs": {
        "description": "Return task instances by task id or exact task name, with optional instance date filter.",
        "schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "task_name": {"type": "string"},
                "instance_date": {"type": "string"},
                "limit": {"type": "integer"},
            },
        },
    },
    "list_data_sources": {
        "description": "List data sources and their stored configuration summary.",
        "schema": {"type": "object", "properties": {"query": {"type": "string"}}},
    },
    "get_data_source": {
        "description": "Return one data source by id, including configuration details stored in the fact database.",
        "schema": {"type": "object", "properties": {"data_source_id": {"type": "string"}}, "required": ["data_source_id"]},
    },
    "list_metadata": {
        "description": "List imported databases and table metadata.",
        "schema": {"type": "object", "properties": {}},
    },
    "is_core_table": {
        "description": "Decide whether a table is core and return explainable scoring reasons.",
        "schema": {"type": "object", "properties": {"table_name": {"type": "string"}}, "required": ["table_name"]},
    },
}


def handle_request(store, request):
    method = request.get("method")
    if method == "initialize":
        return _result(request, {"protocolVersion": "2024-11-05", "serverInfo": {"name": "dlc-agent", "version": "0.1.0"}, "capabilities": {"tools": {}}})
    if method == "tools/list":
        tools = [
            {
                "name": name,
                "description": spec["description"],
                "inputSchema": spec["schema"],
            }
            for name, spec in TOOLS.items()
        ]
        return _result(request, {"tools": tools})
    if method == "tools/call":
        return _call_tool(store, request)
    if method == "notifications/initialized":
        return None
    return _error(request, -32601, "method_not_found")


def _call_tool(store, request):
    params = request.get("params") or {}
    name = params.get("name")
    args = params.get("arguments") or {}
    if name not in TOOLS:
        return _error(request, -32602, "unknown_tool")

    if name == "search_assets":
        data = store.search_assets(args["query"])
    elif name == "search_tasks":
        data = store.search_tasks(args["query"])
    elif name == "get_table_profile":
        data = store.get_table_profile(args["table_name"])
    elif name == "list_table_columns":
        data = store.list_table_columns(args["table_name"])
    elif name == "get_quality_status":
        data = store.get_quality_status(args["table_name"])
    elif name == "get_table_lineage":
        data = store.get_table_lineage(args["table_name"])
    elif name == "get_table_tasks":
        data = store.get_table_tasks(args["table_name"])
    elif name == "get_task_runs":
        if args.get("task_name"):
            data = store.get_task_runs_by_name(args["task_name"], args.get("limit", 10), args.get("instance_date", ""))
        else:
            data = store.get_task_runs(args["task_id"], args.get("limit", 10), args.get("instance_date", ""))
    elif name == "list_data_sources":
        data = store.list_data_sources(args.get("query", ""))
    elif name == "get_data_source":
        data = store.get_data_source(args["data_source_id"])
    elif name == "list_metadata":
        data = store.list_metadata()
    else:
        data = store.is_core_table(args["table_name"])

    return _result(request, {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False, indent=2)}]})


def _result(request, result):
    return {"jsonrpc": "2.0", "id": request.get("id"), "result": result}


def _error(request, code, message):
    return {"jsonrpc": "2.0", "id": request.get("id"), "error": {"code": code, "message": message}}
