class Source:
    AUTO = "auto"
    REGISTRY = "registry"
    LIVE = "live"
    PARTIAL_LIVE = "partial_live"
    PATROL_SNAPSHOT = "patrol_snapshot"
    LEGACY_CACHE = "legacy_cache"
    NOT_AVAILABLE = "not_available"


DYNAMIC_TOOLS = {
    "get_table_partition_profile",
    "get_table_production_status",
    "get_task_runs",
    "get_quality_status",
    "get_table_lineage",
    "get_table_tasks",
    "get_task_code",
    "get_table_risk_profile",
    "get_table_readiness",
    "get_table_profile",
    "get_table_production_risk_detail",
}

REGISTRY_TOOLS = {
    "search_assets",
    "search_tasks",
    "get_table",
    "list_table_columns",
    "list_data_sources",
    "get_data_source",
    "list_data_source_tasks",
    "get_data_source_inventory",
    "list_projects",
    "get_project",
    "list_project_members",
    "list_metadata",
    "get_asset_coverage",
    "get_sync_health",
}

PATROL_TOOLS = {
    "get_asset_governance_daily_report",
    "get_asset_governance_issue_inventory",
    "list_table_production_risks",
    "list_quality_gaps",
    "list_asset_coverage_gaps",
    "list_expert_review_queue",
}

VALID_SOURCES = {
    Source.AUTO,
    Source.REGISTRY,
    Source.LIVE,
    Source.PATROL_SNAPSHOT,
    Source.LEGACY_CACHE,
}


def resolve_source(tool_name, args):
    requested = (args or {}).get("source")
    if requested in VALID_SOURCES and requested != Source.AUTO:
        return requested
    if (args or {}).get("live") is True:
        return Source.LIVE
    if tool_name in DYNAMIC_TOOLS:
        return Source.LIVE
    if tool_name in PATROL_TOOLS:
        return Source.PATROL_SNAPSHOT
    if tool_name in REGISTRY_TOOLS:
        return Source.REGISTRY
    return Source.REGISTRY
