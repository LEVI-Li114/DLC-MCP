import json
import os
from datetime import datetime

from .cleanup_derived_tables import cleanup_task_name_pseudo_tables
from .dlc_query import QueryValidationError
from .live_assets import LiveAssetService
from .source import Source, resolve_source
from .wedata import task_output_tables


def _with_source_schema(schema):
    properties = dict(schema.get("properties") or {})
    properties.setdefault(
        "source",
        {
            "type": "string",
            "enum": ["auto", "live", "registry", "patrol_snapshot", "legacy_cache"],
        },
    )
    return {**schema, "properties": properties}


TOOLS = {
    "submit_dlc_sql_query": {
        "description": "Submit one read-only SELECT/WITH statement to the Tencent Cloud DLC engine. FULL OUTER JOIN is supported.",
        "schema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string"},
                "database_name": {"type": "string"},
                "data_engine_name": {"type": "string"},
                "datasource_connection_name": {"type": "string"},
                "resource_group_name": {"type": "string"},
            },
            "required": ["sql"],
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False},
    },
    "get_dlc_sql_query_result": {
        "description": "Get status and one result page for a previously submitted DLC SQL task.",
        "schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "next_token": {"type": "string"},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 1000},
            },
            "required": ["task_id"],
        },
    },
    "get_dlc_task_resource_usage": {
        "description": (
            "Return the DLC engine resource profile for one task instance. "
            "task_instance_id must be the DLC TaskInstanceId (the engine-side task instance id, "
            "e.g. from WeData setEngineTaskInfo.engineJobId), not a WeData instance_id; "
            "no implicit mapping is performed. The Core usage curve always comes from "
            "DescribeTaskResourceUsage. Optionally set include_cost=true and pass cost_task_id "
            "(the DLC task-id used by DescribeTasksAnalysis) to add CU consumption analysis; "
            "cost_task_id is never derived from task_instance_id."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "task_instance_id": {"type": "string", "description": "DLC TaskInstanceId, not a WeData instance_id."},
                "include_cost": {"type": "boolean", "description": "Also query CU consumption analysis."},
                "cost_task_id": {"type": "string", "description": "DLC task-id filter for cost analysis; not derived from task_instance_id."},
                "cost_start_time": {"type": "string", "description": "Cost analysis window start, format yyyy-mm-dd HH:MM:SS."},
                "cost_end_time": {"type": "string", "description": "Cost analysis window end, format yyyy-mm-dd HH:MM:SS."},
                "cost_limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "required": ["task_instance_id"],
        },
    },
    "search_assets": {
        "description": "Search tables by name, domain, or description.",
        "schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    },
    "search_tasks": {
        "description": "Search WeData ETL tasks by id, name, owner, or status.",
        "schema": {"type": "object", "properties": {"query": {"type": "string"}, "live": {"type": "boolean"}}, "required": ["query"]},
    },
    "list_tasks": {
        "description": (
            "List cached WeData tasks with pagination and optional keyword/task_type/owner filters. "
            "Returns total_count for task inventory. live=true refreshes from WeData ListTasks but requires keyword."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "Match task id or name (substring); required for live=true."},
                "task_type": {"type": "string", "description": "Exact task type code, for example 32 for DLC SQL."},
                "owner": {"type": "string", "description": "Match owner (substring)."},
                "limit": {"type": "integer", "description": "Page size, 1-200, default 20."},
                "offset": {"type": "integer", "description": "Page offset, default 0."},
                "live": {"type": "boolean", "description": "Force a WeData ListTasks refresh filtered by keyword before reading the cache."},
            },
        },
    },
    "get_table_profile": {
        "description": (
            "Return table metadata, columns, lineage, quality status, related tasks, and core-table decision. "
            "sections narrows the output to the listed sections; omit it to return everything."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "table_name": {"type": "string"},
                "sections": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["summary", "value", "storage", "expert_label", "columns", "lineage", "tasks", "data_source", "quality", "runs", "gaps"],
                    },
                    "description": (
                        "Optional section filter; omit it to return every section. "
                        "sections=[\"columns\"] replaces list_table_columns, [\"quality\"] replaces get_quality_status, "
                        "[\"lineage\"] replaces get_table_lineage. Combine with \"summary\" to keep the table identity."
                    ),
                },
                "live": {"type": "boolean"},
            },
            "required": ["table_name"],
        },
    },
    "get_table_partition_profile": {
        "description": "Return table partition profile, row counts, recent partitions, and partition health based on synced partition facts.",
        "schema": {"type": "object", "properties": {"table_name": {"type": "string"}, "partition_date": {"type": "string"}}, "required": ["table_name"]},
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
        "description": "Return SQL/code content for a WeData task from cache or live GetTaskCode refresh, plus output tables parsed from SQL task code.",
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
    "get_data_source_inventory": {
        "description": "Return one data source's related tasks, parsed tables, SQL DDL, and unresolved/missing-field gaps. view=tasks returns only the related task list.",
        "schema": {
            "type": "object",
            "properties": {
                "data_source_id": {"type": "string"},
                "data_source_name": {"type": "string"},
                "view": {"type": "string", "enum": ["full", "tasks"]},
                "live": {"type": "boolean"},
            },
        },
    },
    "get_table_risk_profile": {
        "description": (
            "Return a table-level risk or production report. view=risk returns risk level from lineage, quality "
            "rules, and latest output task runs; view=readiness returns the governance readiness report; "
            "view=production returns the produced-table status; view=production_detail returns the actionable "
            "production-risk diagnosis."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "table_name": {"type": "string"},
                "view": {"type": "string", "enum": ["risk", "readiness", "production", "production_detail"]},
                "instance_date": {"type": "string", "description": "Only used when view=production or production_detail."},
                "live": {"type": "boolean"},
            },
            "required": ["table_name"],
        },
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
    "list_asset_gaps": {
        "description": (
            "List table assets with governance gaps. view=quality lists high-impact tables without quality rules; "
            "view=expert_review lists high-impact unlabelled tables; view=coverage lists tables with missing asset "
            "profile coverage (optionally filtered by gap_type)."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "view": {"type": "string", "enum": ["quality", "expert_review", "coverage"]},
                "gap_type": {"type": "string", "description": "Only used when view=coverage."},
                "layer": {"type": "string"},
                "domain": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["view"],
        },
    },
    "get_expert_label": {
        "description": "Return expert label for one asset.",
        "schema": {"type": "object", "properties": {"asset_type": {"type": "string"}, "asset_name": {"type": "string"}}, "required": ["asset_name"]},
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
    "list_task_relations": {
        "description": "List upstream or downstream WeData tasks for a task id.",
        "schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "direction": {"type": "string", "enum": ["upstream", "downstream"]},
                "project_id": {"type": "string"},
                "live": {"type": "boolean"},
            },
            "required": ["task_id", "direction"],
        },
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
                "scope": {"type": "string"},
            },
        },
    },
    "cleanup_task_name_pseudo_tables": {
        "description": "Delete task-name pseudo-table rows from the asset fact database after a dry run, using strict safeguards.",
        "schema": {
            "type": "object",
            "properties": {
                "data_source_id": {"type": "string"},
                "apply": {"type": "boolean"},
            },
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": True},
    },
}


for _tool_name, _tool_spec in TOOLS.items():
    if _tool_name not in {"submit_dlc_sql_query", "get_dlc_sql_query_result", "get_dlc_task_resource_usage"}:
        _tool_spec["schema"] = _with_source_schema(_tool_spec["schema"])


def handle_request(store, request, live=None, query_service=None):
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
        return _call_tool(store, request, live, query_service)
    if method == "notifications/initialized":
        return None
    return _error(request, -32601, "method_not_found")


def _live_fallback(args, data, predicate):
    return args.get("live") or predicate(data)


def _sync_task_output_tables(store, data):
    """Parse output tables from task code and persist the mapping; return the parsed names."""
    task_id = data.get("task_id", "")
    task = store.resolve_task(task_id) or {}
    tables = task_output_tables(task.get("task_type", ""), data.get("code_text", ""))
    if tables:
        store.upsert_task_table_mappings(task_id, tables, "output")
    return tables


def _has_error(data):
    return bool(data.get("error"))


def _empty_list(key):
    return lambda data: _has_error(data) or not data.get(key)


def _partition_refresh_needed(data, partition_date):
    if _has_error(data):
        return True
    if data.get("is_partitioned") and not data.get("partition_fact_available"):
        return True
    if partition_date and data.get("status") == "missing_partition":
        return True
    return False


def _table_detail_incomplete(data):
    if _has_error(data):
        return True
    table = data.get("table") or {}
    return not table.get("guid") or not data.get("columns")


def _new_query_meta(snapshot=False):
    return {
        "source": "cache_snapshot" if snapshot else "cache",
        "live_attempted": False,
        "live_reason": "",
        "live_error": "",
    }


def _maybe_live_refresh(meta, args, data, predicate, refresh_fn, reason=""):
    if not args.get("live") and not predicate(data):
        return False
    if reason:
        live_reason = reason
    elif args.get("live"):
        live_reason = "user_requested"
    else:
        live_reason = "cache_miss"
    meta["live_attempted"] = True
    meta["live_reason"] = live_reason
    had_cache = not _has_error(data)
    try:
        refresh_fn()
        meta["source"] = "cache_after_live_refresh"
        return True
    except Exception as exc:
        meta["live_error"] = str(exc)
        meta["source"] = "live_refresh_failed_cache" if had_cache else "live_refresh_failed_no_cache"
        return False


def _format_query_meta(meta):
    if meta.get("live_error"):
        live_status = "失败"
    else:
        live_status = "是" if meta.get("live_attempted") else "否"
    lines = [
        "**查询元信息**",
        "",
        f"- 数据来源：{_cell(meta.get('source'))}",
        f"- 实时刷新：{live_status}",
    ]
    if meta.get("live_reason"):
        lines.append(f"- 触发原因：{_cell(meta.get('live_reason'))}")
    if meta.get("live_error"):
        lines.append(f"- 失败原因：{_cell(meta.get('live_error'))}")
    return "\n".join(lines)


def _format_with_meta(tool_name, data, meta):
    return _format_query_meta(meta) + "\n\n" + _format_markdown(tool_name, data)


def _call_tool(store, request, live=None, query_service=None):
    params = request.get("params") or {}
    name = params.get("name")
    args = params.get("arguments") or {}
    source = resolve_source(name, args)
    snapshot_tools = {"get_sync_health", "get_asset_coverage", "get_asset_governance_issue_inventory", "get_asset_governance_daily_report"}
    meta = _new_query_meta(snapshot=name in snapshot_tools)
    meta["source"] = source
    if name not in TOOLS:
        return _error(request, -32602, "unknown_tool")

    if name in {"submit_dlc_sql_query", "get_dlc_sql_query_result"}:
        meta["source"] = "dlc_live"
        if query_service is None:
            data = _error_data("dlc_query_service_unavailable")
        else:
            try:
                if name == "submit_dlc_sql_query":
                    data = query_service.submit(
                        args.get("sql", ""),
                        database_name=args.get("database_name", ""),
                        data_engine_name=args.get("data_engine_name", ""),
                        datasource_connection_name=args.get("datasource_connection_name", ""),
                        resource_group_name=args.get("resource_group_name", ""),
                    )
                else:
                    data = query_service.result(
                        args.get("task_id", ""),
                        next_token=args.get("next_token", ""),
                        max_results=args.get("max_results", 1000),
                    )
            except (QueryValidationError, RuntimeError, ValueError, OSError) as exc:
                data = _error_data(str(exc))
    elif name == "get_dlc_task_resource_usage":
        meta["source"] = "dlc_live"
        if query_service is None:
            data = _error_data("dlc_query_service_unavailable")
        else:
            try:
                data = query_service.resource_usage(
                    args.get("task_instance_id", ""),
                    include_cost=bool(args.get("include_cost")),
                    cost_task_id=args.get("cost_task_id", ""),
                    cost_start_time=args.get("cost_start_time", ""),
                    cost_end_time=args.get("cost_end_time", ""),
                    cost_limit=args.get("cost_limit", 10),
                )
            except (QueryValidationError, RuntimeError, ValueError, OSError) as exc:
                data = _error_data(str(exc))
    elif name == "search_assets":
        data = store.search_assets(args["query"])
    elif name == "search_tasks":
        data = store.search_tasks(args["query"])
        if live:
            refreshed = _maybe_live_refresh(meta, args, data, _empty_list("results"), lambda: live.sync_tasks(args["query"]))
            if refreshed:
                data = store.search_tasks(args["query"])
    elif name == "list_tasks":
        keyword = args.get("keyword", "")
        has_keyword = bool((keyword or "").strip())
        if args.get("live") and not has_keyword:
            data = _error_data("keyword_required_for_live")
        else:
            data = store.list_tasks(
                keyword,
                args.get("task_type", ""),
                args.get("owner", ""),
                args.get("limit", 20),
                args.get("offset", 0),
            )
            if live and has_keyword:
                _maybe_live_refresh(meta, args, data, _empty_list("results"), lambda: live.sync_tasks(keyword))
                data = store.list_tasks(
                    keyword,
                    args.get("task_type", ""),
                    args.get("owner", ""),
                    args.get("limit", 20),
                    args.get("offset", 0),
                )
    elif name == "get_table_profile":
        data = store.get_table_profile(args["table_name"])
        if live:
            refreshed = _maybe_live_refresh(meta, args, data, lambda item: _has_error(item) or not item.get("columns"), lambda: live.sync_table(args["table_name"]), reason="incomplete" if not data.get("columns") else "")
            if refreshed:
                data = store.get_table_profile(args["table_name"])
            if not _has_error(data) and not (data.get("heat") or {}).get("heat_value"):
                try:
                    live.sync_table_stats(args["table_name"])
                    data = store.get_table_profile(args["table_name"])
                    meta["source"] = "cache_after_live_refresh"
                except (RuntimeError, ValueError, OSError):
                    pass
        if not _has_error(data):
            data["sections"] = args.get("sections") or []
    elif name == "get_table_partition_profile":
        partition_date = args.get("partition_date", "")
        data = store.get_table_partition_profile(args["table_name"], partition_date)
        if source == Source.LEGACY_CACHE:
            meta["source"] = Source.LEGACY_CACHE
        elif live:
            result = LiveAssetService(store, live).get_partition_profile(args["table_name"], partition_date)
            meta["source"] = result.source
            meta["live_attempted"] = True
            meta["live_reason"] = "user_requested" if args.get("live") else "live_first"
            data = result.as_dict()
        else:
            meta["source"] = Source.NOT_AVAILABLE
            data = {
                "error": "live_source_unavailable",
                "table_name": args["table_name"],
                "requested_source": source,
            }
    elif name == "list_table_production_risks":
        data = store.list_table_production_risks(args.get("layer", ""), args.get("core_level", ""), args.get("instance_date", ""), args.get("status", ""), args.get("limit", 50))
    elif name == "get_task_runs":
        if not args.get("task_id") and not args.get("task_name"):
            data = _error_data("missing_task_identity")
        elif source == Source.LEGACY_CACHE:
            meta["source"] = Source.LEGACY_CACHE
            if args.get("task_name"):
                data = store.get_task_runs_by_name(args["task_name"], args.get("limit", 10), args.get("instance_date", ""))
            else:
                data = store.get_task_runs(args["task_id"], args.get("limit", 10), args.get("instance_date", ""))
        elif live:
            result = LiveAssetService(store, live).get_task_runs(
                task_id=args.get("task_id", ""),
                task_name=args.get("task_name", ""),
                instance_date=args.get("instance_date", ""),
                limit=args.get("limit", 10),
            )
            meta["source"] = result.source
            meta["live_attempted"] = True
            meta["live_reason"] = "live_first"
            data = result.as_dict()
        else:
            meta["source"] = Source.NOT_AVAILABLE
            data = _error_data("live_source_unavailable", requested_source=source)
    elif name == "get_task_code":
        if not args.get("task_id") and not args.get("task_name"):
            data = _error_data("missing_task_identity")
        else:
            project_id = os.environ.get("WEDATA_PROJECT_ID", "")
            data = store.get_task_code(project_id, args.get("task_id", ""), args.get("task_name", ""))
            if live:
                refreshed = _maybe_live_refresh(
                    meta,
                    args,
                    data,
                    lambda item: item.get("error") in {"task_code_not_found", "task_not_found"},
                    lambda: live.sync_task_code(task_id=args.get("task_id", ""), task_name=args.get("task_name", ""), project_id=project_id),
                )
                if refreshed:
                    data = store.get_task_code(project_id, args.get("task_id", ""), args.get("task_name", ""))
            if not _has_error(data):
                data["output_tables"] = _sync_task_output_tables(store, data)
    elif name == "list_data_sources":
        data = store.list_data_sources(args.get("query", ""))
        if live and _live_fallback(args, data, _empty_list("results")):
            live.sync_data_sources(args.get("query", ""))
            data = store.list_data_sources(args.get("query", ""))
    elif name == "get_data_source":
        data = store.get_data_source(args["data_source_id"])
        if live:
            refreshed = _maybe_live_refresh(meta, args, data, _has_error, lambda: live.sync_data_sources(args["data_source_id"]))
            if refreshed:
                data = store.get_data_source(args["data_source_id"])
    elif name == "get_data_source_inventory":
        view = args.get("view", "full")
        if view not in {"full", "tasks"}:
            data = _error_data("invalid_view", view=view, supported_views=["full", "tasks"])
        else:
            data_source_id = args.get("data_source_id", "")
            data_source_name = args.get("data_source_name", "")
            if not data_source_id and not data_source_name:
                data = _error_data("missing_data_source_identity")
            else:
                data = store.get_data_source_inventory(data_source_id, data_source_name)
                if live and _live_fallback(args, data, lambda item: _has_error(item) or item.get("gaps", {}).get("unresolved_task_count")):
                    live.sync_data_sources(data_source_id or data_source_name)
                    data = store.get_data_source_inventory(data_source_id, data_source_name)
            if not _has_error(data):
                data["view"] = view
    elif name == "get_table_risk_profile":
        view = args.get("view", "risk")
        instance_date = args.get("instance_date", "")
        if view == "risk":
            data = store.get_table_risk_profile(args["table_name"])
            if live and _live_fallback(args, data, _has_error):
                live.sync_table(args["table_name"])
                data = store.get_table_risk_profile(args["table_name"])
        elif view == "readiness":
            data = store.get_table_readiness(args["table_name"])
            if live and _live_fallback(args, data, lambda item: _has_error(item) or item.get("score", 0) < 80):
                live.sync_table(args["table_name"])
                data = store.get_table_readiness(args["table_name"])
        elif view == "production":
            data = store.get_table_production_status(args["table_name"], instance_date)
            if live:
                refreshed = _maybe_live_refresh(meta, args, data, lambda item: _has_error(item) or item.get("status") in {"not_run", "unknown"}, lambda: live.sync_table(args["table_name"]), reason=data.get("status", ""))
                if refreshed:
                    data = store.get_table_production_status(args["table_name"], instance_date)
        elif view == "production_detail":
            data = store.get_table_production_risk_detail(args["table_name"], instance_date)
            if live:
                refreshed = _maybe_live_refresh(meta, args, data, lambda item: _has_error(item) or item.get("status") in {"not_run", "unknown"}, lambda: live.sync_table(args["table_name"]), reason=data.get("status", ""))
                if refreshed:
                    data = store.get_table_production_risk_detail(args["table_name"], instance_date)
        else:
            data = _error_data("invalid_view", view=view, supported_views=["risk", "readiness", "production", "production_detail"])
        if not _has_error(data):
            data["view"] = view
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
        if live and not _has_error(data) and not data.get("heat_value"):
            try:
                live.sync_table_stats(args["table_name"])
                data = store.get_asset_usage_profile(args["table_name"])
            except (RuntimeError, ValueError, OSError):
                pass
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
    elif name == "list_asset_gaps":
        view = args.get("view", "")
        layer = args.get("layer", "")
        limit = args.get("limit", 50)
        if view == "quality":
            data = store.list_quality_gaps(layer, args.get("domain", ""), limit)
        elif view == "expert_review":
            data = store.list_expert_review_queue(layer, limit)
        elif view == "coverage":
            data = store.list_asset_coverage_gaps(args.get("gap_type", ""), layer, limit)
        else:
            data = _error_data("invalid_view", view=view, supported_views=["quality", "expert_review", "coverage"])
        if not _has_error(data):
            data["view"] = view
    elif name == "get_expert_label":
        data = store.get_expert_label(args.get("asset_type", "table"), args["asset_name"])
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
    elif name == "list_task_relations":
        direction = args.get("direction", "")
        if direction not in {"upstream", "downstream"}:
            data = _error_data("invalid_direction", direction=direction)
        else:
            project_id = _project_id_arg(args)
            if not project_id:
                data = _error_data("missing_project_id")
            else:
                data = store.list_task_relations(project_id, args["task_id"], direction)
                if live and _live_fallback(args, data, _empty_list("relations")):
                    live.sync_task_relations(args["task_id"], direction, project_id)
                    data = store.list_task_relations(project_id, args["task_id"], direction)
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
    elif name == "get_asset_governance_issue_inventory":
        if source == Source.LEGACY_CACHE:
            meta["source"] = Source.LEGACY_CACHE
            data = store.get_asset_governance_issue_inventory(
                args.get("layer", ""),
                args.get("core_level", ""),
                args.get("issue_type", ""),
                int(args.get("limit", 100)),
            )
        else:
            meta["source"] = Source.PATROL_SNAPSHOT
            run = store.latest_patrol_run(args.get("instance_date", ""), args.get("scope", ""))
            if not run:
                data = {"source": Source.PATROL_SNAPSHOT, "error": "patrol_snapshot_not_found"}
            else:
                report = store.get_patrol_report_data(run["run_id"])
                findings = report.get("findings", [])
                issue_type = args.get("issue_type", "")
                if issue_type:
                    findings = [item for item in findings if item.get("issue_type") == issue_type]
                data = {"source": Source.PATROL_SNAPSHOT, "run_id": run["run_id"], "findings": findings[: int(args.get("limit", 100))]}
    elif name == "get_asset_governance_daily_report":
        if source == Source.LEGACY_CACHE:
            meta["source"] = Source.LEGACY_CACHE
            data = store.get_asset_governance_daily_report(args.get("instance_date", ""), args.get("layer", ""), args.get("core_level", ""))
        else:
            meta["source"] = Source.PATROL_SNAPSHOT
            run = store.latest_patrol_run(args.get("instance_date", ""), args.get("scope", ""))
            if not run:
                data = {"source": Source.PATROL_SNAPSHOT, "error": "patrol_snapshot_not_found"}
            else:
                data = store.get_patrol_report_data(run["run_id"])
                data["source"] = Source.PATROL_SNAPSHOT
    elif name == "cleanup_task_name_pseudo_tables":
        data = cleanup_task_name_pseudo_tables(store.conn, args.get("data_source_id", ""), bool(args.get("apply", False)))
    else:
        return _error(request, -32602, "unknown_tool")

    return _result(request, {"content": [{"type": "text", "text": _format_with_meta(name, data, meta)}]})


def _result(request, result):
    return {"jsonrpc": "2.0", "id": request.get("id"), "result": result}


def _error(request, code, message):
    return {"jsonrpc": "2.0", "id": request.get("id"), "error": {"code": code, "message": message}}

def _project_id_arg(args):
    return args.get("project_id") or os.environ.get("WEDATA_PROJECT_ID", "")


def _error_data(error, **fields):
    return {"error": error, **fields}



def _json_loads(value):
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value or "{}")
    except Exception:
        return {}


def _format_patrol_snapshot_report(data):
    run = data.get("run") or {}
    snapshots = data.get("snapshots") or []
    findings = data.get("findings") or []
    errors = data.get("errors") or []
    summary = _json_loads(run.get("summary_json", "{}"))
    lines = ["## 每日巡检报告", ""]
    lines.extend(["## 巡检摘要", ""])
    lines.append(f"- Run ID：`{_cell(run.get('run_id', ''))}`")
    lines.append(f"- 日期：`{_cell(run.get('instance_date', ''))}`")
    lines.append(f"- Scope：`{_cell(run.get('scope', ''))}`")
    lines.append(f"- 状态：**{_cell(run.get('status', ''))}**")
    lines.append(f"- checked_count：{_cell(summary.get('checked_count', run.get('checked_count', 0)))}")
    lines.append(f"- live 完整成功：{_cell(summary.get('live_success_count', 0))}")
    lines.append(f"- live 部分缺失：{_cell(summary.get('live_partial_count', 0))}")
    lines.append(f"- live 失败：{_cell(summary.get('live_failed_count', 0))}")
    lines.append(f"- P0：{_cell(summary.get('p0_count', 0))}")
    lines.append(f"- P1：{_cell(summary.get('p1_count', 0))}")
    lines.extend(["", "## 数据来源与查询策略", "", "| 信息 | 查询方式 |", "| --- | --- |"])
    first_snapshot = _json_loads(snapshots[0].get("snapshot_json", "{}")) if snapshots else {}
    for key, value in (first_snapshot.get("source_policy") or {}).items():
        lines.append(f"| {key} | {value} |")
    lines.extend(["", "## 覆盖总览", "", "| 表名 | 层级 | Owner | 状态 |", "| --- | --- | --- | --- |"])
    for row in snapshots[:50]:
        lines.append(f"| `{_cell(row.get('asset_name', ''))}` | {_cell(row.get('layer', ''))} | {_cell(row.get('owner', ''))} | {_cell(row.get('status', ''))} |")
    lines.extend(["", "## 问题清单", "", "| 表名 | 严重级别 | 问题 | 建议 |", "| --- | --- | --- | --- |"])
    for row in findings[:100]:
        lines.append(f"| `{_cell(row.get('asset_name', ''))}` | {_cell(row.get('severity', ''))} | {_cell(row.get('issue_type', ''))} | {_cell(row.get('suggested_action', ''))} |")
    if errors:
        lines.extend(["", "## live 查询失败清单", "", "| 表名 | 模块 | 错误 |", "| --- | --- | --- |"])
        for row in errors[:100]:
            lines.append(f"| `{_cell(row.get('asset_name', ''))}` | {_cell(row.get('module', ''))} | {_cell(row.get('error_message', ''))} |")
    lines.extend(["", "## 巡检指标", "", "## 本次巡检未完成检查"])
    return "\n".join(lines)

def _format_markdown(tool_name, data):
    if isinstance(data, dict) and data.get("error"):
        return f"**未找到**\n\n- 错误：`{_cell(data['error'])}`\n" + "\n".join(f"- {k}: `{_cell(v)}`" for k, v in data.items() if k != "error")
    if isinstance(data, dict) and data.get("errors"):
        error_rows = [
            [err.get("module"), err.get("status"), err.get("api_action"), err.get("error_message"), err.get("retryable")]
            for err in data.get("errors", [])
        ]
        base = {k: v for k, v in data.items() if k != "errors"}
        return _section("部分查询失败", [f"状态：`{_cell(base.get('status', 'unknown'))}`"]) + "\n\n" + _table(
            ["模块", "状态", "API", "错误", "可重试"],
            error_rows,
        )
    if tool_name == "submit_dlc_sql_query":
        return _section(
            "DLC SQL 已提交",
            [
                f"任务 ID：`{_cell(data.get('task_id'))}`",
                f"状态：`{_cell(data.get('status'))}`",
                f"引擎类型：`{_cell(data.get('engine_type'))}`",
                f"数据引擎：`{_cell(data.get('data_engine_name'))}`",
                f"数据库：`{_cell(data.get('database_name'))}`",
                f"SQL SHA-256：`{_cell(data.get('sql_sha256'))}`",
            ],
        )
    if tool_name == "get_dlc_sql_query_result":
        lines = [
            f"任务 ID：`{_cell(data.get('task_id'))}`",
            f"状态：`{_cell(data.get('status'))}`（{_cell(data.get('state'))}）",
            f"进度：{_cell(data.get('progress_percent'))}%",
        ]
        if data.get("message"):
            lines.append(f"消息：{_cell(data.get('message'))}")
        if data.get("next_token"):
            lines.append(f"下一页 token：`{_cell(data.get('next_token'))}`")
        result = _section("DLC SQL 查询结果", lines)
        rows = data.get("rows")
        if isinstance(rows, list) and rows and all(isinstance(row, dict) for row in rows):
            columns = list(rows[0].keys())
            result += "\n\n" + _table(columns, [[row.get(column) for column in columns] for row in rows])
        elif rows not in (None, [], ""):
            result += "\n\n```json\n" + json.dumps(rows, ensure_ascii=False, indent=2) + "\n```"
        return result
    if tool_name == "get_dlc_task_resource_usage":
        series = data.get("series") or []
        lines = [
            f"DLC 任务实例 ID：`{_cell(data.get('task_instance_id'))}`",
            f"采样点数：{len(series)}",
        ]
        if not series:
            lines.append("_未返回 Core 用量曲线；请确认该 TaskInstanceId 属于 DLC 引擎侧实例。_")
        result = _section("DLC 引擎 Core 用量曲线", lines)
        if series:
            result += "\n\n" + _table(
                ["时间戳(毫秒)", "时间", "Core 用量"],
                [[point.get("timestamp"), _format_epoch_millis(point.get("timestamp")), point.get("core_usage")] for point in series],
            )
        cost = data.get("cost_analysis")
        if cost:
            cost_lines = [
                f"任务 ID：`{_cell(cost.get('task_id'))}`",
                f"统计窗口：`{_cell(cost.get('start_time'))}` ~ `{_cell(cost.get('end_time'))}`",
                f"匹配实例数：{_cell(cost.get('total_count'))}",
            ]
            if cost.get("error"):
                cost_lines.append(f"错误：`{_cell(cost.get('error'))}`")
            result += "\n\n" + _section("DLC CU 消耗分析", cost_lines)
            tasks = cost.get("tasks") or []
            if tasks:
                result += "\n\n" + _table(
                    ["实例 ID", "状态", "引擎", "开始时间", "执行耗时(毫秒)", "CU 资源消耗(秒)"],
                    [
                        [
                            task.get("id"),
                            task.get("state"),
                            task.get("data_engine_name"),
                            _format_epoch_millis(task.get("instance_start_time")),
                            task.get("job_time_sum_ms"),
                            task.get("task_time_sum_seconds"),
                        ]
                        for task in tasks
                    ],
                )
        return result
    if tool_name == "get_asset_governance_issue_inventory" and data.get("source") == "patrol_snapshot":
        if data.get("error"):
            return _section("治理问题清单", [f"错误：`{_cell(data.get('error'))}`", "没有可用巡检快照，请先运行每日巡检。"])
        findings = data.get("findings") or []
        return _section("治理问题清单", [f"Run ID：`{_cell(data.get('run_id'))}`", f"问题数：{len(findings)}"]) + "\n\n" + _table(
            ["资产", "问题", "严重级别", "责任桶", "建议动作"],
            [[f.get("asset_name"), f.get("issue_type"), f.get("severity"), f.get("owner_bucket"), f.get("suggested_action")] for f in findings],
        )
    if tool_name == "get_asset_governance_daily_report" and data.get("source") == "patrol_snapshot":
        if data.get("error"):
            return _section("每日巡检报告", [f"错误：`{_cell(data.get('error'))}`", "没有可用巡检快照，请先运行每日巡检。"])
        return _format_patrol_snapshot_report(data)
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
    if tool_name == "list_task_relations":
        rows = data.get("relations", [])
        title = "下游任务" if data.get("direction") == "downstream" else "上游任务"
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
    if tool_name == "get_data_source_inventory":
        if data.get("view") == "tasks":
            rows = data.get("tasks") or []
            return _section("数据源关联任务", [f"数据源ID：`{_cell((data.get('data_source') or {}).get('id'))}`", f"任务数：{len(rows)}"]) + "\n\n" + _table(
                ["TaskId", "任务名", "类型", "项目", "创建时间", "负责人"],
                [[r.get("task_id"), r.get("task_name"), _task_type_display(r.get("task_type")), r.get("project_name"), r.get("create_time"), r.get("owner")] for r in rows],
            )
        return _format_data_source_inventory(data)
    if tool_name == "get_table_risk_profile":
        view = data.get("view") or "risk"
        if view == "readiness":
            return _format_table_readiness(data)
        if view == "production":
            return _format_table_production_status(data)
        if view == "production_detail":
            return _format_table_production_risk_detail(data)
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
    if tool_name == "list_asset_gaps":
        view = data.get("view") or ""
        rows = data.get("results", [])
        if view == "coverage":
            return _format_asset_coverage_gaps(data)
        title = "质量监控缺口" if view == "quality" else "专家评审队列"
        header = [f"层级：`{_cell(data.get('layer'))}`"]
        if view == "quality":
            header.append(f"领域：`{_cell(data.get('domain'))}`")
        header.append(f"数量：{len(rows)}")
        return _section(title, header) + "\n\n" + _table(
            ["表名", "层级", "领域", "负责人", "下游依赖数", "质量规则数"],
            [[r.get("name"), r.get("layer"), r.get("domain"), r.get("owner"), r.get("downstream_count"), r.get("quality_rule_count")] for r in rows],
        )
    if tool_name == "get_expert_label":
        return _format_expert_label(data)
    if tool_name == "search_tasks":
        rows = data.get("results", [])
        return _section("任务搜索结果", [f"查询：`{_cell(data.get('query'))}`", f"数量：{len(rows)}"]) + "\n\n" + _table(
            ["TaskId", "任务名", "类型", "负责人", "状态", "产出表"],
            [[r.get("id"), r.get("name"), _task_type_display(r.get("task_type")), _owner_display(r), r.get("status"), ", ".join(r.get("outputs") or [])] for r in rows],
        )
    if tool_name == "list_tasks":
        rows = data.get("results", [])
        return _section(
            "任务列表",
            [
                f"总数：**{data.get('total_count', 0)}**",
                f"本页：{len(rows)}（limit={data.get('limit', 0)}，offset={data.get('offset', 0)}）",
                "说明：来自本地缓存的全量任务同步结果。",
            ],
        ) + "\n\n" + _table(
            ["TaskId", "任务名", "类型", "负责人", "状态", "产出表"],
            [[r.get("id"), r.get("name"), _task_type_display(r.get("task_type")), _owner_display(r), r.get("status"), ", ".join(r.get("outputs") or [])] for r in rows],
        )
    if tool_name == "get_task_code":
        code_text = data.get("code_text", "")
        language = _code_fence_language(code_text)
        output_tables = data.get("output_tables") or []
        return _section(
            "任务代码",
            [
                f"项目ID：`{_cell(data.get('project_id'))}`",
                f"TaskId：`{_cell(data.get('task_id'))}`",
                f"任务名：**{_cell(data.get('task_name'))}**",
                f"代码大小：{data.get('code_file_size', 0)}",
                f"编码：`{_cell(data.get('encoding'))}`",
                f"更新时间：{_cell(data.get('updated_at'))}",
                f"输出表：{', '.join(f'`{name}`' for name in output_tables) if output_tables else '（无，仅支持 SQL 类任务解析）'}",
            ],
        ) + f"\n\n```{language}\n{code_text}\n```"
    if tool_name == "get_task_runs":
        rows = data.get("runs", [])
        title = f"任务运行实例：{data.get('task_name') or data.get('task_id')}"
        return _section(title, [f"TaskId：`{_cell(data.get('task_id'))}`", f"数量：{len(rows)}"]) + "\n\n" + _table(
            ["实例日期", "开始时间", "结束时间", "耗时秒", "状态", "实例ID"],
            [[r.get("instance_date"), r.get("start_time"), r.get("end_time"), r.get("duration_seconds"), r.get("status"), r.get("instance_id")] for r in rows],
        )
    if tool_name == "get_table_profile":
        return _format_table_profile(data)
    if tool_name == "get_table_partition_profile":
        return _format_table_partition_profile(data)
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
    if tool_name == "get_asset_governance_daily_report":
        return _format_asset_governance_daily_report(data)
    return "```json\n" + json.dumps(data, ensure_ascii=False, indent=2) + "\n```"


def _format_asset_coverage_gaps(data):
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
                ["表名", "层级", "负责人", "字段", "质量规则", "上游", "下游", "任务", "产出任务", "运行实例", "运行实例缺口原因", "数据源", "缺口", "疑似原因", "下一步检查"],
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
                        r.get("suspected_root_cause", ""),
                        r.get("recommended_next_check", ""),
                    ]
                    for r in rows
                ],
            ),
        ]
    )


def _run_gap_reason_label(reason):
    labels = {
        "missing_producer_task": "缺产出任务",
        "missing_task_runs": "有产出任务但缺运行实例",
    }
    return labels.get(reason or "", "")


TASK_TYPE_LABELS = {
    "21": "JDBC SQL",
    "23": "TDSQL-PostgreSQL",
    "26": "离线同步",
    "30": "Python",
    "31": "PySpark",
    "32": "DLC SQL",
    "33": "Impala",
    "34": "Hive SQL",
    "35": "Shell",
    "36": "Spark SQL",
    "38": "Shell 表单",
    "39": "Spark",
    "40": "TCHouse-P",
    "41": "Kettle",
    "42": "TCHouse-X",
    "43": "TCHouse-X SQL",
    "46": "DLC Spark",
    "47": "TiOne",
    "48": "Trino",
    "50": "DLC PySpark",
    "92": "MapReduce",
    "130": "分支节点",
    "131": "归并节点",
    "132": "Notebook",
    "133": "SSH",
    "134": "StarRocks",
    "137": "For-each",
    "138": "Setats SQL",
}


def _task_type_display(value):
    """Render a WeData TaskTypeId code as `名称 (码值)`; unknown values pass through."""
    text = "" if value is None else str(value).strip()
    label = TASK_TYPE_LABELS.get(text)
    return f"{label} ({text})" if label else text


def _code_fence_language(code_text):
    lowered = (code_text or "").lower()
    if any(token in lowered for token in ("pyspark", "sparksession", "spark.read", "spark.sql", "import spark")):
        return "python"
    if any(token in lowered for token in ("#!/bin/bash", "set -e", "echo $")):
        return "shell"
    if any(token in lowered for token in ("select ", "insert ", "update ", "delete ", "create ", "with ")):
        return "sql"
    if lowered.startswith("#!") or any(token in lowered for token in ("def ", "import ", "print(", "__name__")):
        return "python"
    return ""


def _section(title, lines):
    body = "\n".join(f"- {line}" for line in lines if line)
    return f"**{title}**" + (f"\n\n{body}" if body else "")


def _format_epoch_millis(value):
    try:
        return datetime.fromtimestamp(int(value) / 1000).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError, OverflowError):
        return ""


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
                        _task_type_display(task.get("task_type")),
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
            _format_daily_execution_summary(data),
            _format_daily_responsibility_buckets(data),
            _format_daily_acceptance_criteria(data),
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


def _format_daily_execution_summary(data):
    summary = data.get("execution_summary") or {}
    rows = []
    for severity in ("p0", "p1", "p2"):
        for item in summary.get(severity, []):
            rows.append([severity.upper(), item.get("name"), item.get("issue"), item.get("owner_bucket"), item.get("action")])
    return _section("治理执行摘要", ["按 P0/P1/P2 汇总今日优先治理动作。"] ) + "\n\n" + _table(
        ["级别", "资产", "问题", "责任桶", "动作"],
        rows,
    )


def _format_daily_responsibility_buckets(data):
    buckets = data.get("responsibility_buckets") or {}
    rows = [[bucket, len(items), "、".join(item.get("name", "") for item in items[:5])] for bucket, items in buckets.items()]
    return _section("按责任方拆解", ["只基于确定性证据分桶；Owner 不足时进入 unknown_owner。"] ) + "\n\n" + _table(
        ["责任桶", "数量", "示例资产"],
        rows,
    )


def _format_daily_acceptance_criteria(data):
    return _section("验收标准", data.get("acceptance_criteria") or [])




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



def _owner_display(item):
    owner = item.get("owner", "")
    owner_name = item.get("owner_name", "") or (item.get("owner_identity") or {}).get("resolved_owner", "")
    if owner and owner_name and owner_name != owner:
        return f"{owner} / {owner_name}"
    return owner_name or owner

def _format_table_storage_heat(data):
    storage = data.get("storage") or {}
    heat = data.get("heat") or {}
    has_storage = bool(storage.get("total_storage_bytes"))
    has_heat = bool(heat.get("heat_value"))
    if not has_storage and not has_heat:
        return _section(
            "存储与热度",
            [
                "表级存储/热度暂无数据（可通过 DLC DescribeTable 同步，或查询分区画像获取分区级存储）。",
                f"存储来源：`{_cell(storage.get('source', 'not_available'))}`",
                f"热度来源：`{_cell(heat.get('source', 'not_available'))}`",
            ],
        )
    lines = []
    if has_storage:
        lines.append(f"总存储大小：**{_human_bytes(storage.get('total_storage_bytes', 0))}** (`{storage.get('total_storage_bytes', 0)}` bytes)")
    else:
        lines.append(f"总存储大小：暂未获取 (来源 `{_cell(storage.get('source', 'not_available'))}`)")
    if has_heat:
        lines.append(f"表热度值：**{heat.get('heat_value')}**")
    else:
        lines.append(f"表热度值：暂未获取 (来源 `{_cell(heat.get('source', 'not_available'))}`)")
    updated = storage.get("updated_at") or heat.get("updated_at")
    if updated:
        lines.append(f"更新于：`{updated}`")
    return _section("存储与热度", lines)


def _human_bytes(size):
    size = int(size or 0)
    if size <= 0:
        return "0"
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} EB"


def _format_table_profile(data):
    table = data.get("table", {})
    core = data.get("core", {})
    quality = data.get("quality", {})
    lineage = data.get("lineage", {})
    source = data.get("data_source") or {}
    blocks = [
        ("summary", _section(
            f"标准表画像：{table.get('name')}",
            [
                f"库：`{_cell(table.get('database'))}`",
                f"层级：`{_cell(table.get('layer'))}`",
                f"领域：`{_cell(table.get('domain'))}`",
                f"负责人：`{_cell(table.get('owner'))}`",
                f"解析负责人：`{_cell((data.get('owner_resolution') or {}).get('resolved_owner'))}`",
                f"负责人来源：`{_cell((data.get('owner_resolution') or {}).get('owner_source'))}`",
                f"描述：{_cell(table.get('description'))}",
                f"数据源ID：`{_cell(table.get('data_source_id'))}`",
            ],
        )),
        ("value", _section(
            "资产价值与核心表判断",
            [
                f"是否核心：**{core.get('is_core')}**",
                f"核心等级：**{_cell(core.get('core_level'))}**",
                f"价值分层：**{_cell(core.get('value_tier'))}**",
                f"分数：**{core.get('score')}**",
                f"依据：{', '.join(core.get('reasons') or [])}",
            ],
        )),
        ("storage", _format_table_storage_heat(data)),
        ("expert_label", _format_expert_label(data.get("expert_label"))),
        ("columns", _section("字段信息", [f"字段数：{len(data.get('columns', []))}"]) + "\n\n" + _table(
            ["字段名", "类型", "说明"],
            [[c.get("name"), c.get("type"), c.get("description")] for c in data.get("columns", [])],
        )),
        ("lineage", _section("上下游血缘", [f"上游数：{len(lineage.get('upstream', []))}", f"下游数：{len(lineage.get('downstream', []))}"])
            + "\n\n上游：\n\n"
            + _table(["表名", "经由"], [[r.get("upstream"), r.get("via")] for r in lineage.get("upstream", [])])
            + "\n\n下游：\n\n"
            + _table(["表名", "经由"], [[r.get("downstream"), r.get("via")] for r in lineage.get("downstream", [])])),
        ("tasks", _section("相关任务", [f"任务数：{len(data.get('tasks', []))}"]) + "\n\n" + _table(
            ["TaskId", "任务名", "方向", "状态", "负责人", "调度周期", "调度时间", "调度说明"],
            [[t.get("id"), t.get("name"), t.get("direction"), t.get("status"), _owner_display(t), t.get("cycle"), t.get("schedule_time"), t.get("schedule_desc")] for t in data.get("tasks", [])],
        )),
        ("data_source", _format_profile_data_source(source)),
        ("quality", _section("质量监控", [f"是否有监控：{bool(quality.get('rule_count'))}", f"规则数：{quality.get('rule_count')}", f"最新状态：`{_cell(quality.get('latest_status'))}`"])
            + "\n\n"
            + _table(
                ["规则名", "类型", "目标", "启用", "状态", "检查时间"],
                [[r.get("rule_name"), r.get("rule_type"), r.get("target"), r.get("enabled"), r.get("last_status"), r.get("last_checked_at")] for r in quality.get("rules", [])],
            )),
        ("runs", _section("运行状态", [f"最近运行实例数：{len(data.get('latest_runs', []))}"]) + "\n\n" + _table(
            ["TaskId", "任务名", "实例日期", "开始时间", "结束时间", "耗时秒", "状态"],
            [[r.get("task_id"), r.get("task_name"), r.get("instance_date"), r.get("start_time"), r.get("end_time"), r.get("duration_seconds"), r.get("status")] for r in data.get("latest_runs", [])],
        )),
        ("gaps", _section("当前缺口", data.get("gaps") or ["暂无明显缺口"])),
    ]
    selected = set(data.get("sections") or [])
    if selected:
        blocks = [text for key, text in blocks if key in selected]
    else:
        blocks = [text for _, text in blocks]
    return "\n\n".join(blocks)


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
                    f"分区字段：`{', '.join(data.get('partition_keys') or [])}`",
                    f"分区证据：{_cell('、'.join(data.get('partition_evidence') or []))}",
                    f"分区事实：`{_cell(data.get('partition_fact_status', ''))}`",
                    f"分区事实可用：**{data.get('partition_fact_available', False)}**",
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
