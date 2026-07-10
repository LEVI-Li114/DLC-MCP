import argparse
import os
import sqlite3

from .assets import AssetStore


def main(argv=None):
    args = _parse_args(argv)
    db_dir = os.path.dirname(args.db)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    store = AssetStore(sqlite3.connect(args.db))
    store.init_schema()
    report = render_core_asset_validation(store, args.limit, args.instance_date)
    if args.output:
        output_dir = os.path.dirname(args.output)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report)
    else:
        print(report)


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Render core candidate asset end-to-end validation report.")
    parser.add_argument("--db", default=os.environ.get("DLC_MCP_DB", "data/assets.db"))
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--instance-date", default="")
    parser.add_argument("--output", default="")
    return parser.parse_args(argv)


def render_core_asset_validation(store, limit=20, instance_date=""):
    tables = _core_validation_tables(store, limit)
    sections = [
        "# 核心候选资产端到端验收报告",
        "",
        f"- 验收表数：**{len(tables)}**",
        f"- instance_date：`{instance_date}`",
        "- 报告基于当前 SQLite 资产事实生成，不触发外部 API。",
    ]
    for table_name in tables:
        sections.append(_render_table_validation(store, table_name, instance_date))
    return "\n\n".join(section for section in sections if section)


def _core_validation_tables(store, limit):
    candidates = store.list_core_candidates(limit=limit).get("results", [])
    names = [row["name"] for row in candidates if row.get("table_synced")]
    if len(names) >= limit:
        return names[:limit]
    fallback_rows = store._all(
        """
        select t.name
        from tables t
        left join (select upstream, count(*) as downstream_count from lineage group by upstream) d on d.upstream = t.name
        where t.name not in ({})
        order by coalesce(d.downstream_count, 0) desc,
                 case t.layer when 'ads' then 1 when 'dws' then 2 when 'dwd' then 3 else 9 end,
                 t.name
        limit ?
        """.format(",".join("?" for _ in names) or "''"),
        tuple(names + [limit - len(names)]) if names else (limit,),
    )
    names.extend(row["name"] for row in fallback_rows)
    return names[:limit]


def _render_table_validation(store, table_name, instance_date):
    profile = store.get_table_profile(table_name)
    core = store.is_core_table(table_name)
    value = store.get_asset_value_profile(table_name)
    quality = store.get_quality_status(table_name)
    production = store.get_table_production_status(table_name, instance_date)
    risk = store.get_table_production_risk_detail(table_name, instance_date)
    owner = store.get_asset_owner_profile(table_name)
    issues = [item for item in store.get_asset_governance_issue_inventory(limit=200).get("results", []) if item.get("asset_name") == table_name]
    completeness = _profile_completeness(profile, issues)
    lines = [
        f"## {table_name}",
        "",
        f"- 画像完整度：{completeness}%",
        f"- 核心判断：{core.get('core_level', '')} / {value.get('value_tier', '')}",
        f"- 质量状态：规则数 {quality.get('rule_count', 0)}，状态 {quality.get('latest_status', '') or '未知'}",
        f"- 生产状态：{production.get('status', '未知')}",
        f"- Owner：{owner.get('owner', '') or 'unknown owner'}",
        f"- 风险解释：{risk.get('summary', risk.get('status', '暂无风险摘要'))}",
        "- 当前缺口：",
    ]
    if issues:
        lines.extend(f"  - {issue['issue_type']}：{issue['suspected_root_cause']}" for issue in issues)
    else:
        lines.append("  - 暂无治理缺口")
    lines.append("- 建议动作：")
    lines.extend(_table_recommendations(issues))
    return "\n".join(lines)


def _profile_completeness(profile, issues):
    checks = 6
    missing = 0
    table = profile.get("table") or {}
    if not table.get("layer") or table.get("layer") == "unknown":
        missing += 1
    if not table.get("owner"):
        missing += 1
    if not profile.get("columns"):
        missing += 1
    if not profile.get("tasks"):
        missing += 1
    if not profile.get("quality", {}).get("rule_count"):
        missing += 1
    if not table.get("data_source_id"):
        missing += 1
    return round((checks - missing) / checks * 100)


def _table_recommendations(issues):
    if not issues:
        return ["  - 保持当前治理状态，纳入日常巡检。"]
    actions = []
    for issue in issues:
        actions.append(f"  - {issue['recommended_next_check']}")
    return actions


if __name__ == "__main__":
    main()
