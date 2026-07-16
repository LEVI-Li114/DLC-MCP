from dlc_mcp.source import Source, resolve_source


def test_dynamic_tool_auto_resolves_to_live():
    assert resolve_source("get_table_partition_profile", {}) == Source.LIVE
    assert resolve_source("get_task_runs", {"source": "auto"}) == Source.LIVE


def test_registry_tool_auto_resolves_to_registry():
    assert resolve_source("search_assets", {"source": "auto"}) == Source.REGISTRY
    assert resolve_source("list_data_sources", {}) == Source.REGISTRY


def test_patrol_tool_auto_resolves_to_patrol_snapshot():
    assert resolve_source("get_asset_governance_daily_report", {}) == Source.PATROL_SNAPSHOT
    assert resolve_source("get_asset_governance_issue_inventory", {"source": "auto"}) == Source.PATROL_SNAPSHOT


def test_explicit_source_wins():
    assert resolve_source("get_table_partition_profile", {"source": "legacy_cache"}) == Source.LEGACY_CACHE
    assert resolve_source("search_assets", {"source": "live"}) == Source.LIVE


def test_live_true_maps_to_live_for_compatibility():
    assert resolve_source("get_table_partition_profile", {"live": True}) == Source.LIVE


def test_live_false_does_not_force_legacy_cache():
    assert resolve_source("get_table_partition_profile", {"live": False}) == Source.LIVE
