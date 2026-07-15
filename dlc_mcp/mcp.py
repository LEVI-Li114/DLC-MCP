import json
import os


TOOLS = {
    "search_assets": {
        "description": "Search tables by name, domain, or description.",
        "schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    },
    "search_tasks": {
        "description": "Search WeData ETL tasks by id, name, owner, or status.",
        "schema": {"type": "object", "properties": {"query": {"type": "string"}, "live": {"type": "boolean"}}, "required": ["query"]},
    },
    "get_table_profile": {
        "description": "Return table metadata, columns, lineage, quality status, and core-table decision.",
        "schema": {"type": "object", "properties": {"table_name": {"type": "string"}, "live": {"type": "boolean"}}, "required": ["table_name"]},
    },
    "get_table_partition_profile": {
        "description": "Return table partition profile, row counts, recent partitions, and partition health based on synced partition facts.",
        "schema": {"type": "object", "properties": {"table_name": {"type": "string"}, "partition_date": {"type": "string"}}, "required": ["table_name"]},
    },
    "get_table_readiness": {
        "description": "Return a governance readiness report for any table asset profile.",
        "schema": {"type": "object", "properties": {"table_name": {"type": "string"}, "live": {"type": "boolean"}}, "required": ["table_name"]},
    },
    "get_table_production_status": {
        "description": "Return table-level production status from output tasks and latest task run instances.",
        "schema": {"type": "object", "properties": {"table_name": {"type": "string"}, "instance_date": {"type": "string"}, "live": {"type": "boolean"}}, "required": ["table_name"]},
    },
    "get_table_production_risk_detail": {
        "description": "Return actionable production-risk diagnosis for one table, including producer tasks, reasons, impact, and suggestions.",
        "schema": {
            "type": "object",
            "properties": {
                "table_name": {"type": "string"},
                "instance_date": {"type": "string"},
                "live": {"type": "boolean"},
            },
            "required": ["table_name"],
        },
    },
    "list_table_production_risks": {
        "description": "List table-level production risks from output tasks and task run instances.",
        "schema": {
            "type": "object",
            "properties": {
                "layer": {"type": "string"},
                "core_level": {"type": "string"},
                "instance_date": {"type": "string"},
                "status": {"type": "string"},
                "limit": {"type": "integer"},
            },
        },
    },
    "list_table_columns": {
        "description": "List fields for a table.",
        "schema": {"type": "object", "properties": {"table_name": {"type": "string"}, "live": {"type": "boolean"}}, "required": ["table_name"]},
    },
    "get_quality_status": {
        "description": "Return quality monitoring rules and latest status for a table.",
        "schema": {"type": "object", "properties": {"table_name": {"type": "string"}, "live": {"type": "boolean"}}, "required": ["table_name"]},
    },
    "get_table_lineage": {
        "description": "Return upstream and downstream assets for a table.",
        "schema": {"type": "object", "properties": {"table_name": {"type": "string"}, "live": {"type": "boolean"}}, "required": ["table_name"]},
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
                "live": {"type": "boolean"},
            },
        },
    },
    "get_task_code": {
        "description": "Return SQL/code content for a WeData task from cache or live GetTaskCode refresh.",
        "schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "task_name": {"type": "string"},
                "live": {"type": "boolean"},
            },
        },
    },
    "list_data_sources": {
        "description": "List data sources and their stored configuration summary.",
        "schema": {"type": "object", "properties": {"query": {"type": "string"}, "live": {"type": "boolean"}}},
    },
    "get_data_source": {
        "description": "Return one data source by id, including configuration details stored in the fact database.",
        "schema": {"type": "object", "properties": {"data_source_id": {"type": "string"}, "live": {"type": "boolean"}}, "required": ["data_source_id"]},
    },
    "list_data_source_tasks": {
        "description": "List WeData tasks related to one data source.",
        "schema": {"type": "object", "properties": {"data_source_id": {"type": "string"}, "live": {"type": "boolean"}}, "required": ["data_source_id"]},
    },
    "get_data_source_inventory": {
        "description": "Return one data source's related tasks, parsed tables, SQL DDL, and unresolved/missing-field gaps.",
        "schema": {
            "type": "object",
            "properties": {
                "data_source_id": {"type": "string"},
                "data_source_name": {"type": "string"},
                "live": {"type": "boolean"},
            },
        },
    },
    "get_table_risk_profile": {
        "description": "Return table risk level based on lineage, quality rules, and latest output task runs.",
        "schema": {"type": "object", "properties": {"table_name": {"type": "string"}, "live": {"type": "boolean"}}, "required": ["table_name"]},
    },
    "get_asset_value_profile": {
        "description": "Return reusable asset value tier and core-table decision for a table.",
        "schema": {"type": "object", "properties": {"table_name": {"type": "string"}, "live": {"type": "boolean"}}, "required": ["table_name"]},
    },
    "get_asset_owner_profile": {
        "description": "Return asset ownership chain and responsibility gaps for a table.",
        "schema": {"type": "object", "properties": {"table_name": {"type": "string"}, "live": {"type": "boolean"}}, "required": ["table_name"]},
    },
    "get_asset_usage_profile": {
        "description": "Return metadata-proxy usage signals for a table asset.",
        "schema": {"type": "object", "properties": {"table_name": {"type": "string"}, "live": {"type": "boolean"}}, "required": ["table_name"]},
    },
    "get_asset_lifecycle_profile": {
        "description": "Return lifecycle status and governance evidence for a table asset.",
        "schema": {"type": "object", "properties": {"table_name": {"type": "string"}, "live": {"type": "boolean"}}, "required": ["table_name"]},
    },
    "get_asset_change_impact": {
        "description": "Return bounded change impact analysis for a table asset.",
        "schema": {"type": "object", "properties": {"table_name": {"type": "string"}, "change_type": {"type": "string"}, "live": {"type": "boolean"}}, "required": ["table_name"]},
    },
    "get_metric_definition": {
        "description": "Explain metric definition for ads/dws tables from fields, lineage, and tasks.",
        "schema": {"type": "object", "properties": {"table_name": {"type": "string"}, "live": {"type": "boolean"}}, "required": ["table_name"]},
    },
    "list_quality_gaps": {
        "description": "List tables with downstream dependencies but no quality rules.",
        "schema": {"type": "object", "properties": {"layer": {"type": "string"}, "domain": {"type": "string"}, "limit": {"type": "integer"}}},
    },
    "get_expert_label": {
        "description": "Return expert label for one asset.",
        "schema": {"type": "object", "properties": {"asset_type": {"type": "string"}, "asset_name": {"type": "string"}}, "required": ["asset_name"]},
    },
    "list_expert_review_queue": {
        "description": "List high-impact tables that need expert labeling.",
        "schema": {"type": "object", "properties": {"layer": {"type": "string"}, "limit": {"type": "integer"}}},
    },
    "list_projects": {
        "description": "List WeData projects cached from Tencent Cloud ListProjects.",
        "schema": {"type": "object", "properties": {"query": {"type": "string"}, "live": {"type": "boolean"}}},
    },
    "get_project": {
        "description": "Return one WeData project by project_id, defaulting to WEDATA_PROJECT_ID.",
        "schema": {"type": "object", "properties": {"project_id": {"type": "string"}, "live": {"type": "boolean"}}},
    },
    "list_project_members": {
        "description": "List members and roles for a WeData project, defaulting to WEDATA_PROJECT_ID.",
        "schema": {"type": "object", "properties": {"project_id": {"type": "string"}, "live": {"type": "boolean"}}},
    },
    "list_downstream_tasks": {
        "description": "List downstream WeData tasks for a task id.",
        "schema": {"type": "object", "properties": {"task_id": {"type": "string"}, "project_id": {"type": "string"}, "live": {"type": "boolean"}}, "required": ["task_id"]},
    },
    "list_upstream_tasks": {
        "description": "List upstream WeData tasks for a task id.",
        "schema": {"type": "object", "properties": {"task_id": {"type": "string"}, "project_id": {"type": "string"}, "live": {"type": "boolean"}}, "required": ["task_id"]},
    },
    "get_table": {
        "description": "Return Tencent Cloud WeData table metadata detail by table_name or table_guid.",
        "schema": {"type": "object", "properties": {"table_name": {"type": "string"}, "table_guid": {"type": "string"}, "project_id": {"type": "string"}, "live": {"type": "boolean"}}},
    },
    "list_metadata": {
        "description": "List imported databases and table metadata.",
        "schema": {"type": "object", "properties": {}},
    },
    "get_sync_health": {
        "description": "Return sync health, asset counts, latest observed sync signals, and data gaps.",
        "schema": {"type": "object", "properties": {}},
    },
    "get_asset_coverage": {
        "description": "Return asset coverage by layer for tables, fields, lineage, quality rules, tasks, data sources, and runs.",
        "schema": {"type": "object", "properties": {}},
    },
    "list_asset_coverage_gaps": {
        "description": "List tables with missing asset profile coverage, filtered by gap type or layer.",
        "schema": {
            "type": "object",
            "properties": {
                "gap_type": {"type": "string"},
                "layer": {"type": "string"},
                "limit": {"type": "integer"},
            },
        },
    },
    "get_asset_governance_issue_inventory": {
        "description": "Return deterministic governance issue inventory for real asset gaps, grouped by issue type, layer, core level, and evidence.",
        "schema": {
            "type": "object",
            "properties": {
                "layer": {"type": "string"},
                "core_level": {"type": "string"},
                "issue_type": {"type": "string"},
                "limit": {"type": "integer"},
            },
        },
    },
    "get_asset_governance_daily_report": {
        "description": "Return a daily governance patrol report for production risks, coverage gaps, quality gaps, owner gaps, lifecycle watch items, and expert review queue.",
        "schema": {
            "type": "object",
            "properties": {
                "instance_date": {"type": "string"},
                "layer": {"type": "string"},
                "core_level": {"type": "string"},
            },
        },
    },
    "is_core_table": {
        "description": "Decide whether a table is core and return explainable scoring reasons.",
        "schema": {"type": "object", "properties": {"table_name": {"type": "string"}}, "required": ["table_name"]},
    },
}


def handle_request(store, request, live=None):
    method = request.get("method")
    if method == "initialize":
        return _result(request, {"protocolVersion": "2024-11-05", "serverInfo": {"name": "dlc-mcp", "version": "0.1.0"}, "capabilities": {"tools": {}}})
    if method == "tools/list":
        tools = [
            {
                "name": name,
                "description": spec["description"],
                "inputSchema": spec["schema"],
                "annotations": spec.get("annotations", {"readOnlyHint": True}),
            }
            for name, spec in TOOLS.items()
        ]
        return _result(request, {"tools": tools})
    if method == "tools/call":
        return _call_tool(store, request, live)
    if method == "notifications/initialized":
        return None
    return _error(request, -32601, "method_not_found")


def _live_fallback(args, data, predicate):
    return args.get("live") or predicate(data)


def _has_error(data):
    return bool(data.get("error"))


def _empty_list(key):
    return lambda data: _has_error(data) or not data.get(key)


def _table_detail_incomplete(data):
    if _has_error(data):
        return True
    table = data.get("table") or {}
    return not table.get("guid") or not data.get("columns")


def _call_tool(store, request, live=None):
    params = request.get("params") or {}
    name = params.get("name")
    args = params.get("arguments") or {}
    if name not in TOOLS:
        return _error(request, -32602, "unknown_tool")

    if name == "search_assets":
        data = store.search_assets(args["query"])
    elif name == "search_tasks":
        data = store.search_tasks(args["query"])
        if live and _live_fallback(args, data, _empty_list("results")):
            live.sync_tasks(args["query"])
            data = store.search_tasks(args["query"])
    elif name == "get_table_profile":
        data = store.get_table_profile(args["table_name"])
        if live and _live_fallback(args, data, lambda item: _has_error(item) or not item.get("columns")):
            live.sync_table(args["table_name"])
            data = store.get_table_profile(args["table_name"])
    elif name == "get_table_partition_profile":
        data = store.get_table_partition_profile(args["table_name"], args.get("partition_date", ""))
    elif name == "get_table_readiness":
        data = store.get_table_readiness(args["table_name"])
        if live and _live_fallback(args, data, lambda item: _has_error(item) or item.get("score", 0) < 80):
            live.sync_table(args["table_name"])
            data = store.get_table_readiness(args["table_name"])
    elif name == "get_table_production_status":
        data = store.get_table_production_status(args["table_name"], args.get("instance_date", ""))
        if live and _live_fallback(args, data, lambda item: _has_error(item) or item.get("status") in {"not_run", "unknown"}):
            live.sync_table(args["table_name"])
            data = store.get_table_production_status(args["table_name"], args.get("instance_date", ""))
    elif name == "get_table_production_risk_detail":
        data = store.get_table_production_risk_detail(args["table_name"], args.get("instance_date", ""))
        if live and _live_fallback(args, data, lambda item: _has_error(item) or item.get("status") in {"not_run", "unknown"}):
            live.sync_table(args["table_name"])
            data = store.get_table_production_risk_detail(args["table_name"], args.get("instance_date", ""))
    elif name == "list_table_production_risks":
        data = store.list_table_production_risks(args.get("layer", ""), args.get("core_level", ""), args.get("instance_date", ""), args.get("status", ""), args.get("limit", 50))
    elif name == "list_table_columns":
        data = store.list_table_columns(args["table_name"])
        if live and _live_fallback(args, data, _empty_list("columns")):
            live.sync_table(args["table_name"])
            data = store.list_table_columns(args["table_name"])
    elif name == "get_quality_status":
        data = store.get_quality_status(args["table_name"])
        if live and _live_fallback(args, data, lambda item: _has_error(item) or not item.get("has_quality_monitoring")):
            live.sync_table(args["table_name"])
            data = store.get_quality_status(args["table_name"])
    elif name == "get_table_lineage":
        data = store.get_table_lineage(args["table_name"])
        if live and _live_fallback(args, data, lambda item: not item.get("downstream")):
            live.sync_table(args["table_name"])
            data = store.get_table_lineage(args["table_name"])
    elif name == "get_table_tasks":
        data = store.get_table_tasks(args["table_name"])
        if live and _live_fallback(args, data, _empty_list("tasks")):
            live.sync_table(args["table_name"])
            data = store.get_table_tasks(args["table_name"])
    elif name == "get_task_runs":
        if args.get("task_name"):
            data = store.get_task_runs_by_name(args["task_name"], args.get("limit", 10), args.get("instance_date", ""))
            if live and _live_fallback(args, data, _empty_list("runs")):
                live.sync_task_runs(task_name=args["task_name"], instance_date=args.get("instance_date", ""))
                data = store.get_task_runs_by_name(args["task_name"], args.get("limit", 10), args.get("instance_date", ""))
        else:
            data = store.get_task_runs(args["task_id"], args.get("limit", 10), args.get("instance_date", ""))
            if live and _live_fallback(args, data, _empty_list("runs")):
                live.sync_task_runs(task_id=args["task_id"], instance_date=args.get("instance_date", ""))
                data = store.get_task_runs(args["task_id"], args.get("limit", 10), args.get("instance_date", ""))
    elif name == "get_task_code":
        if not args.get("task_id") and not args.get("task_name"):
            data = _error_data("missing_task_identity")
        else:
            project_id = os.environ.get("WEDATA_PROJECT_ID", "")
            data = store.get_task_code(project_id, args.get("task_id", ""), args.get("task_name", ""))
            if live and _live_fallback(args, data, lambda item: item.get("error") in {"task_code_not_found", "task_not_found"}):
                live.sync_task_code(task_id=args.get("task_id", ""), task_name=args.get("task_name", ""), project_id=project_id)
                data = store.get_task_code(project_id, args.get("task_id", ""), args.get("task_name", ""))
    elif name == "list_data_sources":
        data = store.list_data_sources(args.get("query", ""))
        if live and _live_fallback(args, data, _empty_list("results")):
            live.sync_data_sources(args.get("query", ""))
            data = store.list_data_sources(args.get("query", ""))
    elif name == "get_data_source":
        data = store.get_data_source(args["data_source_id"])
        if live and _live_fallback(args, data, _has_error):
            live.sync_data_sources(args["data_source_id"])
            data = store.get_data_source(args["data_source_id"])
    elif name == "list_data_source_tasks":
        data = store.list_data_source_tasks(args["data_source_id"])
        if live and _live_fallback(args, data, _empty_list("tasks")):
            live.sync_data_sources(args["data_source_id"])
            data = store.list_data_source_tasks(args["data_source_id"])
    elif name == "get_data_source_inventory":
        data = store.get_data_source_inventory(args.get("data_source_id", ""), args.get("data_source_name", ""))
        if live and _live_fallback(args, data, lambda item: _has_error(item) or item.get("gaps", {}).get("unresolved_task_count")):
            live.sync_data_sources(args.get("data_source_id") or args.get("data_source_name", ""))
            data = store.get_data_source_inventory(args.get("data_source_id", ""), args.get("data_source_name", ""))
    elif name == "get_table_risk_profile":
        data = store.get_table_risk_profile(args["table_name"])
        if live and _live_fallback(args, data, _has_error):
            live.sync_table(args["table_name"])
            data = store.get_table_risk_profile(args["table_name"])
    elif name == "get_asset_value_profile":
        data = store.get_asset_value_profile(args["table_name"])
        if live and _live_fallback(args, data, _has_error):
            live.sync_table(args["table_name"])
            data = store.get_asset_value_profile(args["table_name"])
    elif name == "get_asset_owner_profile":
        data = store.get_asset_owner_profile(args["table_name"])
        if live and _live_fallback(args, data, lambda item: _has_error(item) or not item.get("owner_candidates")):
            live.sync_table(args["table_name"])
            data = store.get_asset_owner_profile(args["table_name"])
    elif name == "get_asset_usage_profile":
        data = store.get_asset_usage_profile(args["table_name"])
        if live and _live_fallback(args, data, lambda item: _has_error(item) or not item.get("signals")):
            live.sync_table(args["table_name"])
            data = store.get_asset_usage_profile(args["table_name"])
    elif name == "get_asset_lifecycle_profile":
        data = store.get_asset_lifecycle_profile(args["table_name"])
        if live and _live_fallback(args, data, lambda item: _has_error(item) or item.get("lifecycle_status") in {"新建/待补齐", "疑似废弃"}):
            live.sync_table(args["table_name"])
            data = store.get_asset_lifecycle_profile(args["table_name"])
    elif name == "get_asset_change_impact":
        data = store.get_asset_change_impact(args["table_name"], args.get("change_type", "logic_change"))
        if live and _live_fallback(args, data, lambda item: _has_error(item) or (not item.get("direct_downstream") and not item.get("affected_tasks"))):
            live.sync_table(args["table_name"])
            data = store.get_asset_change_impact(args["table_name"], args.get("change_type", "logic_change"))
    elif name == "get_metric_definition":
        data = store.get_metric_definition(args["table_name"])
        if live and _live_fallback(args, data, lambda item: _has_error(item) or not item.get("metric_fields")):
            live.sync_table(args["table_name"])
            data = store.get_metric_definition(args["table_name"])
    elif name == "list_quality_gaps":
        data = store.list_quality_gaps(args.get("layer", ""), args.get("domain", ""), args.get("limit", 50))
    elif name == "get_expert_label":
        data = store.get_expert_label(args.get("asset_type", "table"), args["asset_name"])
    elif name == "list_expert_review_queue":
        data = store.list_expert_review_queue(args.get("layer", ""), args.get("limit", 50))
    elif name == "list_projects":
        data = store.list_projects(args.get("query", ""))
        if live and _live_fallback(args, data, _empty_list("results")):
            live.sync_projects(args.get("query", ""))
            data = store.list_projects(args.get("query", ""))
    elif name == "get_project":
        project_id = _project_id_arg(args)
        if not project_id:
            data = _error_data("missing_project_id")
        else:
            data = store.get_project(project_id)
            if live and _live_fallback(args, data, _has_error):
                live.sync_project(project_id)
                data = store.get_project(project_id)
    elif name == "list_project_members":
        project_id = _project_id_arg(args)
        if not project_id:
            data = _error_data("missing_project_id")
        else:
            data = store.list_project_members(project_id)
            if live and _live_fallback(args, data, _empty_list("members")):
                live.sync_project_members(project_id)
                data = store.list_project_members(project_id)
    elif name == "list_downstream_tasks":
        project_id = _project_id_arg(args)
        if not project_id:
            data = _error_data("missing_project_id")
        else:
            data = store.list_task_relations(project_id, args["task_id"], "downstream")
            if live and _live_fallback(args, data, _empty_list("relations")):
                live.sync_task_relations(args["task_id"], "downstream", project_id)
                data = store.list_task_relations(project_id, args["task_id"], "downstream")
    elif name == "list_upstream_tasks":
        project_id = _project_id_arg(args)
        if not project_id:
            data = _error_data("missing_project_id")
        else:
            data = store.list_task_relations(project_id, args["task_id"], "upstream")
            if live and _live_fallback(args, data, _empty_list("relations")):
                live.sync_task_relations(args["task_id"], "upstream", project_id)
                data = store.list_task_relations(project_id, args["task_id"], "upstream")
    elif name == "get_table":
        table_name = args.get("table_name", "")
        table_guid = args.get("table_guid", "")
        if not table_name and not table_guid:
            data = _error_data("missing_table_identity")
        else:
            data = store.get_table_detail(table_name, table_guid)
            cached_guid = table_guid or (data.get("table") or {}).get("guid", "")
            if live and _live_fallback(args, data, _table_detail_incomplete):
                if cached_guid:
                    live.sync_table_detail(table_guid=cached_guid)
                    data = store.get_table_detail(table_name, cached_guid)
                else:
                    data = _error_data("table_guid_required", table_name=table_name)
    elif name == "list_metadata":
        data = store.list_metadata()
    elif name == "get_sync_health":
        data = store.get_sync_health()
    elif name == "get_asset_coverage":
        data = store.get_asset_coverage()
    elif name == "list_asset_coverage_gaps":
        data = store.list_asset_coverage_gaps(args.get("gap_type", ""), args.get("layer", ""), args.get("limit", 50))
    elif name == "get_asset_governance_issue_inventory":
        data = store.get_asset_governance_issue_inventory(
            args.get("layer", ""),
            args.get("core_level", ""),
            args.get("issue_type", ""),
            int(args.get("limit", 100)),
        )
    elif name == "get_asset_governance_daily_report":
        data = store.get_asset_governance_daily_report(args.get("instance_date", ""), args.get("layer", ""), args.get("core_level", ""))
    else:
        data = store.is_core_table(args["table_name"])

    return _result(request, {"content": [{"type": "text", "text": _format_markdown(name, data)}]})


def _result(request, result):
    return {"jsonrpc": "2.0", "id": request.get("id"), "result": result}


def _error(request, code, message):
    return {"jsonrpc": "2.0", "id": request.get("id"), "error": {"code": code, "message": message}}

def _project_id_arg(args):
    return args.get("project_id") or os.environ.get("WEDATA_PROJECT_ID", "")


def _error_data(error, **fields):
    return {"error": error, **fields}


def _format_markdown(tool_name, data):
    if isinstance(data, dict) and data.get("error"):
        return f"**未找到**\n\n- 错误：`{_cell(data['error'])}`\n" + "\n".join(f"- {k}: `{_cell(v)}`" for k, v in data.items() if k != "error")
    if tool_name == "list_projects":
        rows = data.get("results", [])
        return _section("项目列表", [f"查询：`{_cell(data.get('query', ''))}`", f"数量：{len(rows)}"]) + "\n\n" + _table(
            ["项目ID", "名称", "展示名", "负责人", "状态", "区域", "创建时间", "更新时间"],
            [[r.get("id"), r.get("name"), r.get("display_name"), r.get("owner"), r.get("status"), r.get("region"), r.get("create_time"), r.get("update_time")] for r in rows],
        )
    if tool_name == "get_project":
        return _section(
            "项目详情",
            [
                f"项目ID：`{_cell(data.get('id'))}`",
                f"名称：**{_cell(data.get('name'))}**",
                f"展示名：{_cell(data.get('display_name'))}",
                f"负责人：`{_cell(data.get('owner'))}`",
                f"状态：`{_cell(data.get('status'))}`",
                f"区域：`{_cell(data.get('region'))}`",
                f"创建时间：{_cell(data.get('create_time'))}",
                f"更新时间：{_cell(data.get('update_time'))}",
                f"描述：{_cell(data.get('description'))}",
            ],
        )
    if tool_name == "list_project_members":
        rows = data.get("members", [])
        return _section("项目成员", [f"项目ID：`{_cell(data.get('project_id'))}`", f"成员数：{len(rows)}"]) + "\n\n" + _table(
            ["成员ID", "账号", "展示名", "角色", "角色ID", "类型", "加入时间"],
            [[r.get("member_id"), r.get("member_name"), r.get("display_name"), r.get("role_name"), r.get("role_id"), r.get("member_type"), r.get("join_time")] for r in rows],
        )
    if tool_name in {"list_downstream_tasks", "list_upstream_tasks"}:
        rows = data.get("relations", [])
        title = "下游任务" if tool_name == "list_downstream_tasks" else "上游任务"
        return _section(title, [f"项目ID：`{_cell(data.get('project_id'))}`", f"TaskId：`{_cell(data.get('task_id'))}`", f"任务数：{len(rows)}"]) + "\n\n" + _table(
            ["相关TaskId", "任务名", "依赖类型", "负责人", "状态"],
            [[r.get("related_task_id"), r.get("related_task_name"), r.get("dependency_type"), r.get("owner"), r.get("status")] for r in rows],
        )
    if tool_name == "get_table":
        table = data.get("table", {})
        columns = data.get("columns", [])
        return _section(
            "表元数据详情",
            [
                f"表名：**{_cell(table.get('name'))}**",
                f"GUID：`{_cell(table.get('guid'))}`",
                f"项目ID：`{_cell(table.get('project_id'))}`",
                f"库：`{_cell(table.get('database'))}`",
                f"Catalog：`{_cell(table.get('catalog_name'))}`",
                f"Schema：`{_cell(table.get('schema_name'))}`",
                f"类型：`{_cell(table.get('table_type'))}`",
                f"数据源：`{_cell(table.get('data_source_id'))}`",
                f"负责人：`{_cell(table.get('owner'))}`",
                f"描述：{_cell(table.get('description'))}",
                f"字段数：{len(columns)}",
            ],
        ) + "\n\n" + _table(["字段名", "类型", "说明"], [[c.get("name"), c.get("type"), c.get("description")] for c in columns[:20]])
    if tool_name == "list_data_sources":
        rows = data.get("results", [])
        return _section("数据源列表", [f"查询：`{_cell(data.get('query', ''))}`", f"数量：{len(rows)}"]) + "\n\n" + _table(
            ["ID", "名称", "类型", "负责人", "花名", "任务数", "库", "Host", "URL"],
            [[r.get("id"), r.get("name"), r.get("type"), r.get("owner"), r.get("owner_name"), r.get("task_count"), r.get("config", {}).get("database"), r.get("config", {}).get("host"), r.get("config", {}).get("url")] for r in rows],
        )
    if tool_name == "get_data_source":
        config = data.get("config", {})
        return _section("数据源详情", [f"ID：`{_cell(data.get('id'))}`", f"名称：**{_cell(data.get('name'))}**", f"类型：`{_cell(data.get('type'))}`", f"负责人：`{_cell(data.get('owner'))}` / `{_cell(data.get('owner_name'))}`", f"已关联任务数：**{data.get('task_count', 0)}**", f"描述：{_cell(data.get('description'))}"]) + "\n\n" + _table(
            ["配置项", "值"],
            [[k, v] for k, v in config.items()],
        )
    if tool_name == "list_data_source_tasks":
        rows = data.get("tasks", [])
        return _section("数据源关联任务", [f"数据源ID：`{_cell(data.get('data_source_id'))}`", f"任务数：{len(rows)}"]) + "\n\n" + _table(
            ["TaskId", "任务名", "类型", "项目", "创建时间", "负责人"],
            [[r.get("task_id"), r.get("task_name"), r.get("task_type"), r.get("project_name"), r.get("create_time"), r.get("owner")] for r in rows],
        )
    if tool_name == "get_data_source_inventory":
        return _format_data_source_inventory(data)
    if tool_name == "get_table_risk_profile":
        return "\n\n".join(
            [
                _section(
                    f"表风险画像：{data.get('table_name')}",
                    [
                        f"风险等级：**{_cell(data.get('risk_level'))}**",
                        f"层级：`{_cell(data.get('layer'))}`",
                        f"下游依赖数：**{data.get('downstream_count')}**",
                        f"质量规则数：**{data.get('quality_rule_count')}**",
                        f"原因：{', '.join(data.get('reasons') or [])}",
                        f"建议：{'; '.join(data.get('suggestions') or [])}",
                    ],
                ),
                _format_expert_label(data.get("expert_label")),
                _table(
                    ["TaskId", "任务名", "实例日期", "开始时间", "结束时间", "耗时秒", "状态"],
                    [[r.get("task_id"), r.get("task_name"), r.get("instance_date"), r.get("start_time"), r.get("end_time"), r.get("duration_seconds"), r.get("status")] for r in data.get("latest_runs", [])],
                ),
            ]
        )
    if tool_name == "get_asset_value_profile":
        return _format_asset_value_profile(data)
    if tool_name == "get_asset_owner_profile":
        return _format_asset_owner_profile(data)
    if tool_name == "get_asset_usage_profile":
        return _format_asset_usage_profile(data)
    if tool_name == "get_asset_lifecycle_profile":
        return _format_asset_lifecycle_profile(data)
    if tool_name == "get_asset_change_impact":
        return _format_asset_change_impact(data)
    if tool_name == "get_metric_definition":
        return _format_metric_definition(data)
    if tool_name == "list_quality_gaps":
        rows = data.get("results", [])
        return _section("质量监控缺口", [f"层级：`{_cell(data.get('layer'))}`", f"领域：`{_cell(data.get('domain'))}`", f"数量：{len(rows)}"]) + "\n\n" + _table(
            ["表名", "层级", "领域", "负责人", "下游依赖数", "质量规则数"],
            [[r.get("name"), r.get("layer"), r.get("domain"), r.get("owner"), r.get("downstream_count"), r.get("quality_rule_count")] for r in rows],
        )
    if tool_name == "get_expert_label":
        return _format_expert_label(data)
    if tool_name == "list_expert_review_queue":
        rows = data.get("results", [])
        return _section("专家评审队列", [f"层级：`{_cell(data.get('layer'))}`", f"数量：{len(rows)}"]) + "\n\n" + _table(
            ["表名", "层级", "领域", "负责人", "下游依赖数", "质量规则数"],
            [[r.get("name"), r.get("layer"), r.get("domain"), r.get("owner"), r.get("downstream_count"), r.get("quality_rule_count")] for r in rows],
        )
    if tool_name == "search_tasks":
        rows = data.get("results", [])
        return _section("任务搜索结果", [f"查询：`{_cell(data.get('query'))}`", f"数量：{len(rows)}"]) + "\n\n" + _table(
            ["TaskId", "任务名", "类型", "负责人", "状态", "产出表"],
            [[r.get("id"), r.get("name"), r.get("task_type"), r.get("owner"), r.get("status"), ", ".join(r.get("outputs") or [])] for r in rows],
        )
    if tool_name == "get_task_code":
        code_text = data.get("code_text", "")
        language = _code_fence_language(code_text)
        return _section(
            "任务代码",
            [
                f"项目ID：`{_cell(data.get('project_id'))}`",
                f"TaskId：`{_cell(data.get('task_id'))}`",
                f"任务名：**{_cell(data.get('task_name'))}**",
                f"代码大小：{data.get('code_file_size', 0)}",
                f"编码：`{_cell(data.get('encoding'))}`",
                f"更新时间：{_cell(data.get('updated_at'))}",
            ],
        ) + f"\n\n```{language}\n{code_text}\n```"
    if tool_name == "get_task_runs":
        rows = data.get("runs", [])
        title = f"任务运行实例：{data.get('task_name') or data.get('task_id')}"
        return _section(title, [f"TaskId：`{_cell(data.get('task_id'))}`", f"数量：{len(rows)}"]) + "\n\n" + _table(
            ["实例日期", "开始时间", "结束时间", "耗时秒", "状态", "实例ID"],
            [[r.get("instance_date"), r.get("start_time"), r.get("end_time"), r.get("duration_seconds"), r.get("status"), r.get("instance_id")] for r in rows],
        )
    if tool_name == "list_table_columns":
        return _section(f"字段列表：{data.get('table_name')}", [f"字段数：{len(data.get('columns', []))}"]) + "\n\n" + _table(
            ["字段名", "类型", "说明"],
            [[c.get("name"), c.get("type"), c.get("description")] for c in data.get("columns", [])],
        )
    if tool_name == "get_quality_status":
        return _section(f"质量状态：{data.get('table_name')}", [f"是否有监控：{data.get('has_quality_monitoring')}", f"规则数：{data.get('rule_count')}", f"最新状态：`{_cell(data.get('latest_status'))}`"]) + "\n\n" + _table(
            ["规则名", "类型", "目标", "启用", "状态", "检查时间"],
            [[r.get("rule_name"), r.get("rule_type"), r.get("target"), r.get("enabled"), r.get("last_status"), r.get("last_checked_at")] for r in data.get("rules", [])],
        )
    if tool_name == "get_table_lineage":
        upstream = _table(["上游", "经由"], [[r.get("upstream"), r.get("via")] for r in data.get("upstream", [])])
        downstream = _table(["下游", "经由"], [[r.get("downstream"), r.get("via")] for r in data.get("downstream", [])])
        return f"**血缘关系**\n\n上游：\n\n{upstream}\n\n下游：\n\n{downstream}"
    if tool_name == "get_table_profile":
        return _format_table_profile(data)
    if tool_name == "get_table_partition_profile":
        return _format_table_partition_profile(data)
    if tool_name == "get_table_readiness":
        return _format_table_readiness(data)
    if tool_name == "get_table_production_status":
        return _format_table_production_status(data)
    if tool_name == "get_table_production_risk_detail":
        return _format_table_production_risk_detail(data)
    if tool_name == "list_table_production_risks":
        rows = data.get("results", [])
        return "\n\n".join(
            [
                _section(
                    "表产出风险清单",
                    [
                        f"层级：`{_cell(data.get('layer'))}`",
                        f"核心等级：`{_cell(data.get('core_level'))}`",
                        f"实例日期：`{_cell(data.get('instance_date'))}`",
                        f"状态：`{_cell(data.get('status'))}`",
                        f"数量：{len(rows)}",
                    ],
                ),
                _table(
                    ["表名", "层级", "领域", "负责人", "核心等级", "价值分层", "产出状态", "产出任务数", "原因", "建议"],
                    [
                        [
                            r.get("name"),
                            r.get("layer"),
                            r.get("domain"),
                            r.get("owner"),
                            r.get("core_level"),
                            r.get("value_tier"),
                            r.get("status_label"),
                            r.get("producer_task_count"),
                            "；".join(r.get("reasons") or []),
                            "；".join(r.get("suggestions") or []),
                        ]
                        for r in rows
                    ],
                ),
            ]
        )
    if tool_name == "get_sync_health":
        counts = data.get("counts", {})
        signals = data.get("latest_signals", {})
        ratios = data.get("coverage_ratios", {})
        thresholds = data.get("coverage_thresholds", {})
        return "\n\n".join(
            [
                _section(
                    "同步健康检查",
                    [
                        f"状态：**{_cell(data.get('status'))}**",
                        f"缺口数：**{len(data.get('gaps') or [])}**",
                        f"说明：{'; '.join(data.get('notes') or [])}",
                    ],
                ),
                _table("资产类型 数量".split(), [[_count_label(k), v] for k, v in counts.items()]),
                _table(["覆盖维度", "当前覆盖率", "健康阈值"], [[_count_label(k), f"{v:.1%}", f"{thresholds.get(k, 0):.0%}"] for k, v in ratios.items()]),
                _section("最新同步线索", []) + "\n\n" + _table(
                    ["线索", "时间"],
                    [[_count_label(k), v] for k, v in signals.items()],
                ),
                _section("当前缺口", data.get("gaps") or ["暂无明显缺口"]),
            ]
        )
    if tool_name == "get_asset_coverage":
        totals = data.get("totals", {})
        warehouse = data.get("warehouse_coverage", {})
        unknown = data.get("unknown_pool", {})
        ratios = warehouse.get("ratios", {})
        return "\n\n".join(
            [
                _section("资产覆盖率", ["按已同步表资产统计。"]),
                _table("资产类型 数量".split(), [[_count_label(k), v] for k, v in totals.items()]),
                _section(
                    "有效数仓覆盖",
                    [
                        f"数仓层：{', '.join(data.get('warehouse_layers') or [])}",
                        f"表数：{warehouse.get('table_count', 0)}",
                        f"字段：{ratios.get('fields', 0):.1%}",
                        f"血缘：{ratios.get('lineage', 0):.1%}",
                        f"任务映射：{ratios.get('tasks', 0):.1%}",
                        f"运行实例关联：{ratios.get('runs', 0):.1%}",
                        f"数据源：{ratios.get('data_source', 0):.1%}",
                    ],
                ),
                _section(
                    "unknown 资产池",
                    [
                        f"表数：{unknown.get('table_count', 0)}",
                        f"有字段：{unknown.get('tables_with_columns', 0)}",
                        f"有血缘：{unknown.get('tables_with_lineage', 0)}",
                        f"有关联任务：{unknown.get('tables_with_tasks', 0)}",
                        f"有运行实例：{unknown.get('tables_with_runs', 0)}",
                        "unknown 不计入主覆盖率，但仍作为治理缺口追踪。",
                    ],
                ),
                _table(
                    ["层级", "表数", "有字段", "有质量规则", "有下游", "有上游", "有关联任务", "有运行实例", "有数据源"],
                    [
                        [
                            r.get("layer"),
                            r.get("table_count"),
                            _ratio(r.get("tables_with_columns"), r.get("table_count")),
                            _ratio(r.get("tables_with_quality_rules"), r.get("table_count")),
                            _ratio(r.get("tables_with_downstream"), r.get("table_count")),
                            _ratio(r.get("tables_with_upstream"), r.get("table_count")),
                            _ratio(r.get("tables_with_tasks"), r.get("table_count")),
                            _ratio(r.get("tables_with_runs"), r.get("table_count")),
                            _ratio(r.get("tables_with_data_source"), r.get("table_count")),
                        ]
                        for r in data.get("layers", [])
                    ],
                ),
                _section("说明", data.get("coverage_notes") or []),
            ]
        )
    if tool_name == "list_asset_coverage_gaps":
        rows = data.get("results", [])
        return "\n\n".join(
            [
                _section(
                    "资产画像缺口清单",
                    [
                        f"缺口类型：`{_cell(data.get('gap_type'))}`",
                        f"层级：`{_cell(data.get('layer'))}`",
                        f"数量：{len(rows)}",
                        f"支持类型：{', '.join(data.get('supported_gap_types') or [])}",
                    ],
                ),
                _table(
                    ["表名", "层级", "负责人", "字段", "质量规则", "上游", "下游", "任务", "产出任务", "运行实例", "运行实例缺口原因", "数据源", "缺口"],
                    [
                        [
                            r.get("name"),
                            r.get("layer"),
                            r.get("owner"),
                            r.get("column_count"),
                            r.get("quality_rule_count"),
                            r.get("upstream_count"),
                            r.get("downstream_count"),
                            r.get("task_count"),
                            r.get("producer_task_count"),
                            r.get("run_count"),
                            _run_gap_reason_label(r.get("run_gap_reason")),
                            r.get("data_source_id"),
                            "、".join(r.get("gaps") or []),
                        ]
                        for r in rows
                    ],
                ),
            ]
        )
    if tool_name == "get_asset_governance_daily_report":
        return _format_asset_governance_daily_report(data)
    if tool_name == "is_core_table":
        return _format_core_decision(data)
    return "```json\n" + json.dumps(data, ensure_ascii=False, indent=2) + "\n```"


def _run_gap_reason_label(reason):
    labels = {
        "missing_producer_task": "缺产出任务",
        "missing_task_runs": "有产出任务但缺运行实例",
    }
    return labels.get(reason or "", "")


def _code_fence_language(code_text):
    lowered = (code_text or "").lower()
    if any(token in lowered for token in ("select ", "insert ", "update ", "delete ", "create ", "with ")):
        return "sql"
    return ""


def _section(title, lines):
    body = "\n".join(f"- {line}" for line in lines if line)
    return f"**{title}**" + (f"\n\n{body}" if body else "")


def _format_expert_label(label):
    if not label or label.get("error"):
        return "**专家标注**\n\n_暂无专家标注_"
    return _section(
        "专家标注",
        [
            f"资产：`{_cell(label.get('asset_type'))}` / **{_cell(label.get('asset_name'))}**",
            f"核心等级：`{_cell(label.get('core_level'))}`",
            f"价值分层：`{_cell(label.get('value_tier'))}`",
            f"分类：`{_cell(label.get('domain'))}`",
            f"使用场景：{_cell(label.get('use_case'))}",
            f"指标口径：{_cell(label.get('metric_definition'))}",
            f"Owner：`{_cell(label.get('owner'))}`，Reviewer：`{_cell(label.get('reviewer'))}`",
            f"原因：{_cell(label.get('reason'))}",
            f"更新时间：`{_cell(label.get('updated_at'))}`",
        ],
    )


def _format_data_source_inventory(data):
    source = data.get("data_source") or {}
    tasks = data.get("tasks") or []
    tables = data.get("tables") or []
    gaps = data.get("gaps") or {}
    ddl_sections = []
    for table in tables:
        if table.get("ddl"):
            ddl_sections.append(f"### {table.get('name')}\n\n```sql\n{table.get('ddl')}\n```")
    if not ddl_sections:
        ddl_sections.append("_当前没有可生成 DDL 的表；需要先补齐字段同步。_")
    return "\n\n".join(
        [
            _section(
                f"数据源资产清单：{source.get('name')}",
                [
                    f"ID：`{_cell(source.get('id'))}`",
                    f"类型：`{_cell(source.get('type'))}`",
                    f"负责人：`{_cell(source.get('owner'))}` / `{_cell(source.get('owner_name'))}`",
                    f"任务数：**{len(tasks)}**",
                    f"表数：**{len(tables)}**",
                    f"未解析任务数：**{gaps.get('unresolved_task_count', 0)}**",
                    f"缺字段表数：**{gaps.get('missing_field_table_count', 0)}**",
                ],
            ),
            _table(
                ["TaskId", "任务名", "状态", "类型", "项目", "负责人", "关联表"],
                [
                    [
                        task.get("task_id"),
                        task.get("task_name"),
                        task.get("parse_status"),
                        task.get("task_type"),
                        task.get("project_name"),
                        task.get("owner"),
                        ", ".join(_task_table_names(task)),
                    ]
                    for task in tasks
                ],
            ),
            _table(
                ["表名", "状态", "字段数", "库", "层级", "负责人", "任务映射"],
                [
                    [
                        table.get("name"),
                        table.get("parse_status"),
                        len(table.get("columns") or []),
                        table.get("database"),
                        table.get("layer"),
                        table.get("owner"),
                        ", ".join(f"{item.get('task_id')}:{item.get('direction')}" for item in table.get("task_mappings") or []),
                    ]
                    for table in tables
                ],
            ),
            _section(
                "缺口",
                [
                    "未解析任务：" + ", ".join(item.get("task_name", "") for item in gaps.get("unresolved_tasks", [])[:20])
                    if gaps.get("unresolved_tasks")
                    else "未解析任务：无",
                    "缺字段表：" + ", ".join(gaps.get("missing_field_tables", [])[:50])
                    if gaps.get("missing_field_tables")
                    else "缺字段表：无",
                ],
            ),
            "**SQL DDL**\n\n" + "\n\n".join(ddl_sections),
        ]
    )


def _task_table_names(task):
    return [item.get("table_name", "") for item in task.get("tables") or [] if item.get("table_name")]


def _format_asset_value_profile(data):
    dimensions = (data.get("machine") or {}).get("dimensions") or data.get("dimensions") or {}
    final = data.get("final") or {}
    machine = data.get("machine") or {}
    manual = data.get("manual") or {}
    return "\n\n".join(
        [
            _section(
                f"资产价值模型：{data.get('table_name')}",
                [
                    f"最终价值分层：**{_cell(data.get('value_tier'))}**",
                    f"最终核心等级：**{_cell(data.get('core_level'))}**",
                    f"是否核心表：**{data.get('is_core')}**",
                    f"判断来源：`{_cell(data.get('source'))}`",
                    f"最终分数：**{data.get('score')}**",
                    f"置信度：`{_cell(data.get('confidence'))}`",
                    f"复核建议：{_cell(data.get('review_suggestion'))}",
                ],
            ),
            _section(
                "机器初判",
                [
                    f"机器分数：**{machine.get('score')}**",
                    f"机器等级：`{_cell(machine.get('core_level'))}` / `{_cell(machine.get('value_tier'))}`",
                    f"依据：{', '.join(machine.get('evidence') or data.get('evidence') or [])}",
                ],
            ),
            _table(
                ["维度", "分数"],
                [[key, value] for key, value in dimensions.items()],
            ),
            _section(
                "最终判断",
                [
                    f"等级：`{_cell(final.get('core_level'))}`",
                    f"分层：`{_cell(final.get('value_tier'))}`",
                    f"来源：`{_cell(final.get('source'))}`",
                ],
            ),
            _section(
                "人工标注摘要",
                [
                    f"等级：`{_cell(manual.get('core_level'))}`",
                    f"分层：`{_cell(manual.get('value_tier'))}`",
                    f"Reviewer：`{_cell(manual.get('reviewer'))}`",
                    f"原因：{_cell(manual.get('reason'))}",
                ] if manual else ["暂无人工标注"],
            ),
            _section("当前缺口", data.get("gaps") or ["暂无明显缺口"]),
            _format_expert_label(data.get("expert_label")),
        ]
    )


def _format_asset_owner_profile(data):
    return "\n\n".join(
        [
            _section(
                f"资产责任画像：{data.get('table_name')}",
                [
                    f"表Owner：`{_cell(data.get('table_owner'))}`",
                    f"专家Owner：`{_cell(data.get('expert_owner'))}`，Reviewer：`{_cell(data.get('expert_reviewer'))}`",
                    f"数据源Owner：`{_cell(data.get('data_source_owner'))}`",
                ],
            ),
            _section("责任人候选", data.get("owner_candidates") or ["暂无"]),
            _section("Owner 证据", []) + "\n\n" + _table("来源 Owner".split(), [["产出任务", owner] for owner in data.get("producer_task_owners", [])] + [["消费任务", owner] for owner in data.get("consumer_task_owners", [])] + [[f"下游表 {row.get('name')}", row.get("owner")] for row in data.get("downstream_owners", [])]),
            _section("责任缺口", data.get("gaps") or ["暂无明显缺口"]),
            _section("处理建议", data.get("suggestions") or []),
        ]
    )


def _format_asset_usage_profile(data):
    return "\n\n".join(
        [
            _section(
                f"资产使用画像：{data.get('table_name')}",
                [
                    f"使用等级：**{_cell(data.get('usage_level'))}**",
                    f"证据来源：`{_cell(data.get('usage_source'))}`（当前为元数据代理证据，不是真实查询日志）",
                    f"下游数：**{data.get('downstream_count', 0)}**，消费任务数：**{data.get('consumer_task_count', 0)}**，产出任务数：**{data.get('producer_task_count', 0)}**",
                    f"质量规则数：**{data.get('quality_rule_count', 0)}**，最近运行实例数：**{data.get('latest_run_count', 0)}**",
                    f"专家使用场景：{_cell(data.get('expert_use_case'))}",
                ],
            ),
            _section("使用信号", data.get("signals") or ["暂无元数据使用信号"]),
            _section("当前缺口", data.get("gaps") or []),
            _section("处理建议", data.get("suggestions") or []),
        ]
    )


def _format_asset_lifecycle_profile(data):
    return "\n\n".join(
        [
            _section(
                f"资产生命周期：{data.get('table_name')}",
                [
                    f"生命周期状态：**{_cell(data.get('lifecycle_status'))}**",
                    f"最近产出时间：`{_cell(data.get('latest_run_time'))}`",
                    f"最近质量检查：`{_cell(data.get('latest_quality_check'))}`",
                    f"专家更新时间：`{_cell(data.get('expert_updated_at'))}`",
                    f"产出任务：**{data.get('producer_task_count', 0)}**，消费任务：**{data.get('consumer_task_count', 0)}**，下游：**{data.get('downstream_count', 0)}**",
                ],
            ),
            _section("生命周期证据", data.get("evidence") or []),
            _section("当前缺口", data.get("gaps") or ["暂无明显缺口"]),
            _section("治理建议", data.get("suggestions") or []),
        ]
    )


def _format_asset_change_impact(data):
    return "\n\n".join(
        [
            _section(
                f"资产变更影响分析：{data.get('table_name')}",
                [
                    f"变更类型：`{_cell(data.get('change_type'))}`",
                    f"风险等级：**{_cell(data.get('risk_level'))}**",
                    f"直接下游：**{len(data.get('direct_downstream') or [])}**，间接下游：**{len(data.get('indirect_downstream') or [])}**，影响任务：**{len(data.get('affected_tasks') or [])}**",
                ],
            ),
            _section("直接下游", []) + "\n\n" + _table(["下游表", "经由"], [[row.get("downstream"), row.get("via")] for row in data.get("direct_downstream", [])]),
            _section("间接下游", []) + "\n\n" + _table(["上游", "下游", "经由"], [[row.get("upstream"), row.get("downstream"), row.get("via")] for row in data.get("indirect_downstream", [])]),
            _section("影响任务", []) + "\n\n" + _table(["TaskId", "任务名", "方向", "Owner", "状态"], [[row.get("id"), row.get("name"), row.get("direction"), row.get("owner"), row.get("status")] for row in data.get("affected_tasks", [])]),
            _section("核心下游资产", [f"{row.get('name')}（{row.get('core_level')} / {row.get('value_tier')}）" for row in data.get("affected_core_assets", [])] or ["暂无"]),
            _section("变更前检查", data.get("checks") or []),
            _section("处理建议", data.get("suggestions") or []),
        ]
    )


def _format_manual_review_top_items(data):
    rows = []
    for item in (data.get("manual_review_top_items") or [])[:10]:
        evidence = f"下游{item.get('downstream_count', 0)}，任务{item.get('task_count', 0)}，产出任务{item.get('producer_task_count', 0)}，运行实例{item.get('run_count', 0)}"
        rows.append(
            [
                item.get("severity", ""),
                item.get("issue_label", ""),
                item.get("name", ""),
                evidence,
                item.get("owner_bucket_label", ""),
                item.get("daily_action", ""),
            ]
        )
    return _section("今日优先人工判断问题", []) + "\n\n" + _table(["优先级", "问题类型", "表名", "影响证据", "责任方", "今日动作"], rows)


def _format_manual_review_sections(data):
    parts = [_section("需要人工判断的资产覆盖问题", [])]
    for section in data.get("manual_review_sections") or []:
        rows = []
        if section.get("key") == "owner_review":
            for item in (section.get("items") or [])[:10]:
                rows.append(
                    [
                        item.get("name", ""),
                        item.get("layer", ""),
                        item.get("owner", ""),
                        "、".join(item.get("owner_candidates") or []),
                        "、".join(item.get("gaps") or []),
                    ]
                )
            table = _table(["表名", "层级", "Owner", "候选责任人", "缺口"], rows)
        else:
            for item in (section.get("items") or [])[:10]:
                rows.append(
                    [
                        item.get("name", ""),
                        item.get("layer", ""),
                        item.get("owner", ""),
                        item.get("downstream_count", 0),
                        item.get("task_count", 0),
                        item.get("producer_task_count", 0),
                        item.get("run_count", 0),
                        item.get("recommended_next_check", ""),
                    ]
                )
            table = _table(["表名", "层级", "Owner", "下游", "任务", "产出任务", "运行实例", "建议"], rows)
        parts.append(f"**{_cell(section.get('title'))}**\n\n{table}")
    return "\n\n".join(parts)


def _format_asset_governance_daily_report(data):
    summary = data.get("summary") or {}
    return "\n\n".join(
        [
            _section(
                "资产巡检日报",
                [
                    f"日期：`{_cell(data.get('instance_date'))}`",
                    f"层级：`{_cell(data.get('layer'))}`，核心等级：`{_cell(data.get('core_level'))}`",
                    f"同步状态：**{_cell(summary.get('sync_status'))}**",
                    f"产出风险：**{summary.get('production_risk_count', 0)}**（失败 {summary.get('failed_count', 0)}，未执行 {summary.get('not_run_count', 0)}，执行中 {summary.get('running_count', 0)}，未知 {summary.get('unknown_count', 0)}）",
                    f"画像缺口：**{summary.get('coverage_gap_count', 0)}**，质量缺口：**{summary.get('quality_gap_count', 0)}**，Owner缺口：**{summary.get('owner_gap_count', 0)}**",
                    f"生命周期关注：**{summary.get('lifecycle_watch_count', 0)}**，专家评审：**{summary.get('expert_review_count', 0)}**",
                ],
            ),
            _section("今日优先动作", data.get("top_actions") or []),
            _section("产出风险 Top 表", []) + "\n\n" + _table(["表名", "层级", "Owner", "核心等级", "状态", "原因"], [[row.get("name"), row.get("layer"), row.get("owner"), row.get("core_level"), row.get("status_label"), "；".join(row.get("reasons") or [])] for row in data.get("production_risks", [])]),
            _section("资产画像缺口", []) + "\n\n" + _table(["表名", "层级", "Owner", "缺口"], [[row.get("name"), row.get("layer"), row.get("owner"), "、".join(row.get("gaps") or [])] for row in data.get("coverage_gaps", [])]),
            _format_manual_review_top_items(data),
            _format_manual_review_sections(data),
            _section("质量规则缺口", []) + "\n\n" + _table(["表名", "层级", "Owner", "下游", "质量规则"], [[row.get("name"), row.get("layer"), row.get("owner"), row.get("downstream_count"), row.get("quality_rule_count")] for row in data.get("quality_gaps", [])]),
            _section("Owner 责任缺口", []) + "\n\n" + _table(["表名", "层级", "Owner", "候选责任人", "缺口"], [[row.get("name"), row.get("layer"), row.get("owner"), "、".join(row.get("owner_candidates") or []), "、".join(row.get("gaps") or [])] for row in data.get("owner_gaps", [])]),
            _section("生命周期关注", []) + "\n\n" + _table(["表名", "层级", "Owner", "状态", "最近产出", "缺口"], [[row.get("name"), row.get("layer"), row.get("owner"), row.get("lifecycle_status"), row.get("latest_run_time"), "、".join(row.get("gaps") or [])] for row in data.get("lifecycle_watch", [])]),
            _section("专家评审队列", []) + "\n\n" + _table(["表名", "层级", "领域", "Owner", "下游", "质量规则"], [[row.get("name"), row.get("layer"), row.get("domain"), row.get("owner"), row.get("downstream_count"), row.get("quality_rule_count")] for row in data.get("expert_review_queue", [])]),
            _section("说明", data.get("notes") or []),
        ]
    )


def _format_core_decision(data):
    machine = data.get("machine") or {}
    final = data.get("final") or {}
    manual = data.get("manual") or {}
    dimensions = machine.get("dimensions") or {}
    return "\n\n".join(
        [
            _section(
                f"核心资产判断：{data.get('table_name')}",
                [
                    f"最终结论：**{'核心资产' if data.get('is_core') else '非核心/待观察'}**",
                    f"核心等级：**{_cell(data.get('core_level'))}**",
                    f"价值分层：**{_cell(data.get('value_tier'))}**",
                    f"判断来源：`{_cell(data.get('source'))}`",
                    f"最终分数：**{data.get('score')}**",
                    f"置信度：`{_cell(data.get('confidence'))}`",
                ],
            ),
            _section(
                "机器初判",
                [
                    f"机器分数：**{machine.get('score')}**",
                    f"机器等级：`{_cell(machine.get('core_level'))}` / `{_cell(machine.get('value_tier'))}`",
                    f"任务依赖：{_cell(machine.get('task_dependency'))}",
                    f"依据：{', '.join(machine.get('evidence') or data.get('reasons') or [])}",
                ],
            ),
            _table(["维度", "分数"], [[key, value] for key, value in dimensions.items()]),
            _section(
                "人工标注",
                [
                    f"等级：`{_cell(manual.get('core_level'))}`",
                    f"分层：`{_cell(manual.get('value_tier'))}`",
                    f"Reviewer：`{_cell(manual.get('reviewer'))}`",
                    f"原因：{_cell(manual.get('reason'))}",
                ] if manual else ["暂无人工标注"],
            ),
            _section(
                "最终判断",
                [
                    f"等级：`{_cell(final.get('core_level'))}`",
                    f"分层：`{_cell(final.get('value_tier'))}`",
                    f"来源：`{_cell(final.get('source'))}`",
                ],
            ),
            _section("当前缺口", data.get("gaps") or ["暂无明显缺口"]),
            _section("复核建议", [data.get("review_suggestion", "")]),
        ]
    )


def _format_metric_definition(data):
    table = data.get("table", {})
    role = data.get("role", {})
    return "\n\n".join(
        [
            _section(
                f"指标口径：{table.get('name')}",
                [
                    f"层级：`{_cell(table.get('layer'))}`",
                    f"口径角色：**{_cell(role.get('name'))}**",
                    f"是否口径主表：**{role.get('primary_definition')}**",
                    f"主题：`{_cell(data.get('subject'))}`",
                    f"时间粒度：`{_cell(data.get('time_grain'))}`",
                    f"统计粒度：{', '.join(_field_names(data.get('statistical_grain', []))) or '未识别'}",
                    f"口径摘要：{_cell(data.get('summary'))}",
                    f"说明：{_cell(data.get('explanation'))}",
                ],
            ),
            _section("时间字段", []) + "\n\n" + _table(
                ["字段名", "字段类型", "说明"],
                [[r.get("name"), r.get("type"), r.get("description")] for r in data.get("time_fields", [])],
            ),
            _section("维度字段", []) + "\n\n" + _table(
                ["字段名", "字段类型", "说明"],
                [[r.get("name"), r.get("type"), r.get("description")] for r in data.get("dimension_fields", [])],
            ),
            _section("指标字段", []) + "\n\n" + _table(
                ["字段名", "指标类型", "字段类型", "说明"],
                [[r.get("name"), r.get("metric_type"), r.get("type"), r.get("description")] for r in data.get("metric_fields", [])],
            ),
            _section("描述字段", []) + "\n\n" + _table(
                ["字段名", "字段类型", "说明"],
                [[r.get("name"), r.get("type"), r.get("description")] for r in data.get("description_fields", [])],
            ),
            _section("上游 dws 口径表", []) + "\n\n" + _table(["表名", "经由"], [[r.get("upstream"), r.get("via")] for r in data.get("upstream_dws", [])]),
            _section("上游来源表", []) + "\n\n" + _table(["表名", "经由"], [[r.get("upstream"), r.get("via")] for r in data.get("upstream_sources", [])]),
            _section("下游 ads 指标结果表", []) + "\n\n" + _table(["表名", "经由"], [[r.get("downstream"), r.get("via")] for r in data.get("downstream_ads", [])]),
            _section("相关任务", []) + "\n\n" + _table(["TaskId", "任务名", "方向", "状态"], [[t.get("id"), t.get("name"), t.get("direction"), t.get("status")] for t in data.get("tasks", [])]),
            _format_expert_label(data.get("expert_label")),
        ]
    )


def _format_table_profile(data):
    table = data.get("table", {})
    core = data.get("core", {})
    quality = data.get("quality", {})
    lineage = data.get("lineage", {})
    source = data.get("data_source") or {}
    return "\n\n".join(
        [
            _section(
                f"标准表画像：{table.get('name')}",
                [
                    f"库：`{_cell(table.get('database'))}`",
                    f"层级：`{_cell(table.get('layer'))}`",
                    f"领域：`{_cell(table.get('domain'))}`",
                    f"负责人：`{_cell(table.get('owner'))}`",
                    f"描述：{_cell(table.get('description'))}",
                    f"数据源ID：`{_cell(table.get('data_source_id'))}`",
                ],
            ),
            _section(
                "资产价值与核心表判断",
                [
                    f"是否核心：**{core.get('is_core')}**",
                    f"核心等级：**{_cell(core.get('core_level'))}**",
                    f"价值分层：**{_cell(core.get('value_tier'))}**",
                    f"分数：**{core.get('score')}**",
                    f"依据：{', '.join(core.get('reasons') or [])}",
                ],
            ),
            _format_expert_label(data.get("expert_label")),
            _section("字段信息", [f"字段数：{len(data.get('columns', []))}"]) + "\n\n" + _table(
                ["字段名", "类型", "说明"],
                [[c.get("name"), c.get("type"), c.get("description")] for c in data.get("columns", [])],
            ),
            _section("上下游血缘", [f"上游数：{len(lineage.get('upstream', []))}", f"下游数：{len(lineage.get('downstream', []))}"])
            + "\n\n上游：\n\n"
            + _table(["表名", "经由"], [[r.get("upstream"), r.get("via")] for r in lineage.get("upstream", [])])
            + "\n\n下游：\n\n"
            + _table(["表名", "经由"], [[r.get("downstream"), r.get("via")] for r in lineage.get("downstream", [])]),
            _section("相关任务", [f"任务数：{len(data.get('tasks', []))}"]) + "\n\n" + _table(
                ["TaskId", "任务名", "方向", "状态", "负责人", "调度周期", "调度时间", "调度说明"],
                [[t.get("id"), t.get("name"), t.get("direction"), t.get("status"), t.get("owner"), t.get("cycle"), t.get("schedule_time"), t.get("schedule_desc")] for t in data.get("tasks", [])],
            ),
            _format_profile_data_source(source),
            _section("质量监控", [f"是否有监控：{bool(quality.get('rule_count'))}", f"规则数：{quality.get('rule_count')}", f"最新状态：`{_cell(quality.get('latest_status'))}`"])
            + "\n\n"
            + _table(
                ["规则名", "类型", "目标", "启用", "状态", "检查时间"],
                [[r.get("rule_name"), r.get("rule_type"), r.get("target"), r.get("enabled"), r.get("last_status"), r.get("last_checked_at")] for r in quality.get("rules", [])],
            ),
            _section("运行状态", [f"最近运行实例数：{len(data.get('latest_runs', []))}"]) + "\n\n" + _table(
                ["TaskId", "任务名", "实例日期", "开始时间", "结束时间", "耗时秒", "状态"],
                [[r.get("task_id"), r.get("task_name"), r.get("instance_date"), r.get("start_time"), r.get("end_time"), r.get("duration_seconds"), r.get("status")] for r in data.get("latest_runs", [])],
            ),
            _section("当前缺口", data.get("gaps") or ["暂无明显缺口"]),
        ]
    )


def _format_table_partition_profile(data):
    target = data.get("target_partition") or {}
    latest = data.get("latest_partition") or {}
    earliest = data.get("earliest_partition") or {}
    return "\n\n".join(
        [
            _section(
                f"表分区画像：{data.get('table_name')}",
                [
                    f"查询分区日期：`{_cell(data.get('partition_date'))}`",
                    f"是否分区表：**{data.get('is_partitioned')}**",
                    f"分区数量：**{data.get('partition_count', 0)}**",
                    f"最新分区：`{_cell(latest.get('partition_name'))}`",
                    f"最早分区：`{_cell(earliest.get('partition_name'))}`",
                    f"总行数：**{data.get('total_rows', 0)}**",
                    f"总存储字节：**{data.get('total_storage_bytes', 0)}**",
                    f"健康状态：**{_cell(data.get('health_label'))}** (`{_cell(data.get('health_status'))}`)",
                ],
            ),
            _section("目标分区", []) + "\n\n" + _table(["分区", "日期", "行数", "存储字节", "文件数", "更新时间"], [[target.get("partition_name"), target.get("partition_date"), target.get("row_count"), target.get("storage_bytes"), target.get("file_count"), target.get("updated_at")]] if target else []),
            _section("最近分区", []) + "\n\n" + _table(["分区", "日期", "行数", "存储字节", "文件数", "更新时间"], [[row.get("partition_name"), row.get("partition_date"), row.get("row_count"), row.get("storage_bytes"), row.get("file_count"), row.get("updated_at")] for row in data.get("recent_partitions", [])]),
            _section("判断依据", data.get("reasons") or []),
            _section("处理建议", data.get("suggestions") or []),
        ]
    )


def _format_table_readiness(data):
    summary = data.get("summary") or {}
    return "\n\n".join(
        [
            _section(
                f"表资产治理就绪度：{data.get('table_name')}",
                [
                    f"验收状态：**{_cell(data.get('status'))}**",
                    f"完整度分数：**{data.get('score')}**",
                    f"层级：`{_cell(summary.get('layer'))}`，领域：`{_cell(summary.get('domain'))}`，Owner：`{_cell(summary.get('owner'))}`",
                    f"核心等级：`{_cell(summary.get('core_level'))}`，价值分层：`{_cell(summary.get('value_tier'))}`，置信度：`{_cell(summary.get('confidence'))}`",
                ],
            ),
            _section("画像维度检查", []) + "\n\n" + _table(
                ["维度", "状态", "证据"],
                [[row.get("name"), row.get("status"), row.get("evidence")] for row in data.get("checks", [])],
            ),
            _section("相关任务明细", []) + "\n\n" + _table(
                ["TaskId", "任务名", "方向", "责任人", "调度周期", "调度时间", "调度说明", "任务状态"],
                [[row.get("task_id"), row.get("task_name"), row.get("direction"), row.get("owner"), row.get("cycle"), row.get("schedule_time"), row.get("schedule_desc"), row.get("status")] for row in data.get("related_tasks", [])],
            ),
            _section("最近任务执行实例", []) + "\n\n" + _table(
                ["TaskId", "任务名", "方向", "责任人", "执行状态", "开始时间", "结束时间", "耗时秒"],
                [[row.get("task_id"), row.get("task_name"), row.get("direction"), row.get("owner"), row.get("execution_status"), row.get("start_time"), row.get("end_time"), row.get("duration_seconds")] for row in data.get("task_runs", [])],
            ),
            _section("当前缺口", data.get("gaps") or ["暂无明显缺口"]),
            _section("治理动作建议", data.get("next_actions") or []),
            _section("核心/价值判断摘要", [
                f"最终结论：**{'核心资产' if (data.get('profile') or {}).get('core', {}).get('is_core') else '非核心/待观察'}**",
                f"复核建议：{_cell((data.get('profile') or {}).get('core', {}).get('review_suggestion', ''))}",
            ]),
        ]
    )


def _format_table_production_status(data):
    return "\n\n".join(
        [
            _section(
                f"表产出状态：{data.get('table_name')}",
                [
                    f"查询日期：`{_cell(data.get('instance_date'))}`",
                    f"汇总状态：**{_cell(data.get('status_label'))}** (`{_cell(data.get('status'))}`)",
                    f"产出任务数：**{data.get('producer_task_count')}**",
                ],
            ),
            _section("产出任务实例", []) + "\n\n" + _table(
                ["TaskId", "任务名", "责任人", "调度时间", "原始状态", "状态", "开始时间", "结束时间", "耗时秒"],
                [
                    [
                        task.get("task_id"),
                        task.get("task_name"),
                        task.get("owner"),
                        task.get("schedule_time"),
                        (task.get("latest_run") or {}).get("raw_status"),
                        (task.get("latest_run") or {}).get("status_label"),
                        (task.get("latest_run") or {}).get("start_time"),
                        (task.get("latest_run") or {}).get("end_time"),
                        (task.get("latest_run") or {}).get("duration_seconds"),
                    ]
                    for task in data.get("tasks", [])
                ],
            ),
            _section("判断依据", data.get("reasons") or []),
            _section("建议", data.get("suggestions") or ["暂无"]),
        ]
    )


def _format_table_production_risk_detail(data):
    table = data.get("table") or {}
    core = data.get("core") or {}
    quality = data.get("quality") or {}
    production = data.get("production") or {}
    impact = data.get("impact") or {}
    return "\n\n".join(
        [
            _section(
                f"表产出风险诊断：{data.get('table_name')}",
                [
                    f"查询日期：`{_cell(data.get('instance_date'))}`",
                    f"汇总状态：**{_cell(data.get('status_label'))}** (`{_cell(data.get('status'))}`)",
                    f"层级：`{_cell(table.get('layer'))}`，领域：`{_cell(table.get('domain'))}`，Owner：`{_cell(table.get('owner'))}`",
                    f"核心等级：`{_cell(core.get('core_level'))}`，价值分层：`{_cell(core.get('value_tier'))}`，分数：**{core.get('score', 0)}**",
                    f"下游影响数：**{impact.get('downstream_count', 0)}**，质量规则数：**{quality.get('rule_count', 0)}**",
                ],
            ),
            _section("产出任务实例", []) + "\n\n" + _table(
                ["TaskId", "任务名", "责任人", "调度时间", "原始状态", "状态", "开始时间", "结束时间", "耗时秒"],
                [
                    [
                        task.get("task_id"),
                        task.get("task_name"),
                        task.get("owner"),
                        task.get("schedule_time"),
                        (task.get("latest_run") or {}).get("raw_status"),
                        (task.get("latest_run") or {}).get("status_label"),
                        (task.get("latest_run") or {}).get("start_time"),
                        (task.get("latest_run") or {}).get("end_time"),
                        (task.get("latest_run") or {}).get("duration_seconds"),
                    ]
                    for task in production.get("tasks", [])
                ],
            ),
            _section("影响面", [f"上游数：{impact.get('upstream_count', 0)}", f"下游数：{impact.get('downstream_count', 0)}"])
            + "\n\n"
            + _table(["下游表", "经由"], [[row.get("downstream"), row.get("via")] for row in impact.get("downstream", [])]),
            _section("风险判断", data.get("diagnosis") or []),
            _section("判断依据", data.get("reasons") or []),
            _section("处理建议", data.get("suggestions") or ["暂无"]),
        ]
    )


def _format_profile_data_source(source):
    if not source:
        return _section("数据源", ["未关联数据源"])
    return _section(
        "数据源",
        [
            f"名称：**{_cell(source.get('name'))}**",
            f"类型：`{_cell(source.get('type'))}`",
            f"负责人：`{_cell(source.get('owner'))}` / `{_cell(source.get('owner_name'))}`",
            f"关联任务数：{source.get('task_count', 0)}",
        ],
    )


def _field_names(fields):
    return [field.get("name", "") for field in fields if field.get("name")]


def _table(headers, rows):
    if not rows:
        return "_无数据_"
    header = "| " + " | ".join(headers) + " |"
    sep = "| " + " | ".join(["---"] * len(headers)) + " |"
    body = ["| " + " | ".join(_cell(v) for v in row) + " |" for row in rows]
    return "\n".join([header, sep, *body])


def _cell(value):
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def _ratio(value, total):
    value = int(value or 0)
    total = int(total or 0)
    if not total:
        return "0/0"
    return f"{value}/{total} ({value / total:.0%})"


def _count_label(key):
    labels = {
        "tables": "表资产",
        "columns": "字段",
        "tasks": "任务",
        "task_table_mappings": "任务表映射",
        "task_runs": "运行实例",
        "data_sources": "数据源",
        "data_source_tasks": "数据源关联任务",
        "lineage_edges": "血缘边",
        "quality_rules": "质量规则",
        "expert_labels": "专家标注",
        "latest_task_run_start": "最近任务开始",
        "latest_task_run_end": "最近任务结束",
        "latest_quality_check": "最近质量检查",
        "latest_data_source_task_create": "最近数据源任务创建",
    }
    return labels.get(key, key)
