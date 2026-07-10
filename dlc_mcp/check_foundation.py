import argparse
import os
import sqlite3

from .assets import AssetStore
from .server import _load_env_file


DEFAULT_GAP_TYPES = "fields,lineage,quality,tasks,runs,data_source"


def main():
    args = _parse_args()
    if args.env_file and os.path.exists(args.env_file):
        _load_env_file(args.env_file)

    db_path = args.db or os.environ.get("DLC_MCP_DB", "data/assets.db")
    gap_types = _split_csv(args.gap_types or os.environ.get("DLC_MCP_SYNC_GAP_TYPES", DEFAULT_GAP_TYPES))
    gap_limit = args.gap_limit or int(os.environ.get("DLC_MCP_SYNC_GAP_LIMIT", "20"))

    store = AssetStore(sqlite3.connect(db_path))
    store.init_schema()
    print(render_foundation_report(store, db_path, gap_types, gap_limit))


def _parse_args():
    parser = argparse.ArgumentParser(description="Print a readable DLC-MCP asset foundation health report.")
    parser.add_argument("--env-file", default=os.environ.get("DLC_MCP_ENV_FILE", "/etc/dlc-mcp/env"), help="Optional env file to load before checking.")
    parser.add_argument("--db", default="", help="SQLite asset database path. Defaults to DLC_MCP_DB or data/assets.db.")
    parser.add_argument("--gap-types", default="", help="Comma-separated gap types to list.")
    parser.add_argument("--gap-limit", type=int, default=0, help="Maximum rows per gap type.")
    return parser.parse_args()


def render_foundation_report(store, db_path, gap_types=None, gap_limit=20, report_source="", quality_rule_count=None, unknown_layer_count=None):
    health = store.get_sync_health()
    coverage = store.get_asset_coverage()
    gap_types = gap_types or _split_csv(DEFAULT_GAP_TYPES)

    sections = [
        "# DLC-MCP 资产底座检查报告",
        _format_inspection_source(db_path, report_source, quality_rule_count, unknown_layer_count),
        _format_health(health),
        _format_coverage(coverage),
        _format_core_candidates(store.list_core_candidates(limit=gap_limit)),
    ]
    for gap_type in gap_types:
        sections.append(_format_gaps(store.list_asset_coverage_gaps(gap_type=gap_type, limit=gap_limit)))
    sections.append(_format_next_actions(health, coverage))
    return "\n\n".join(section for section in sections if section)


def _format_inspection_source(db_path, report_source="", quality_rule_count=None, unknown_layer_count=None):
    lines = [f"数据库：`{_cell(db_path)}`"]
    if report_source:
        lines.append(f"来源：{_cell(report_source)}")
    if quality_rule_count is not None:
        lines.append(f"质量规则基线：**{quality_rule_count}**（来自最新服务端资产库巡检）")
    if unknown_layer_count is not None:
        lines.append(f"unknown 层表基线：**{unknown_layer_count}**（来自最新服务端资产库巡检）")
    return _section("巡检来源", lines)


def _format_health(health):
    counts = health.get("counts", {})
    signals = health.get("latest_signals", {})
    gaps = health.get("gaps", [])
    return "\n\n".join(
        [
            _section("同步健康", [f"状态：**{_cell(health.get('status'))}**", f"缺口数：**{len(gaps)}**"]),
            _table(["资产类型", "数量"], [[_count_label(key), value] for key, value in counts.items()]),
            _section("最新同步线索", []) + "\n\n" + _table(["线索", "时间"], [[_count_label(key), value] for key, value in signals.items()]),
            _section("当前健康缺口", gaps or ["暂无健康缺口"]),
        ]
    )


def _format_coverage(coverage):
    rows = coverage.get("layers", [])
    return _section("资产覆盖率", ["按已同步表资产统计。"]) + "\n\n" + _table(
        ["层级", "表数", "有字段", "有质量规则", "有下游", "有上游", "有关联任务", "有数据源"],
        [
            [
                row.get("layer"),
                row.get("table_count"),
                _ratio(row.get("tables_with_columns"), row.get("table_count")),
                _ratio(row.get("tables_with_quality_rules"), row.get("table_count")),
                _ratio(row.get("tables_with_downstream"), row.get("table_count")),
                _ratio(row.get("tables_with_upstream"), row.get("table_count")),
                _ratio(row.get("tables_with_tasks"), row.get("table_count")),
                _ratio(row.get("tables_with_data_source"), row.get("table_count")),
            ]
            for row in rows
        ],
    )


def _format_gaps(data):
    rows = data.get("results", [])
    title = f"资产画像缺口：{data.get('gap_type') or 'all'}"
    lines = [f"缺口类型：`{_cell(data.get('gap_type'))}`", f"数量：**{len(rows)}**"]
    return _section(title, lines) + "\n\n" + _table(
        ["表名", "层级", "负责人", "字段", "质量规则", "上游", "下游", "任务", "运行实例", "数据源", "缺口"],
        [
            [
                row.get("name"),
                row.get("layer"),
                row.get("owner"),
                row.get("column_count"),
                row.get("quality_rule_count"),
                row.get("upstream_count"),
                row.get("downstream_count"),
                row.get("task_count"),
                row.get("run_count"),
                row.get("data_source_id"),
                "、".join(row.get("gaps") or []),
            ]
            for row in rows
        ],
    )


def _format_core_candidates(data):
    rows = data.get("results", [])
    if not rows:
        return _section("核心候选资产覆盖", ["尚未导入核心候选资产清单。"])
    synced = sum(1 for row in rows if row.get("table_synced"))
    with_columns = sum(1 for row in rows if row.get("column_count"))
    with_quality = sum(1 for row in rows if row.get("quality_rule_count"))
    with_lineage = sum(1 for row in rows if row.get("upstream_count") or row.get("downstream_count"))
    with_tasks = sum(1 for row in rows if row.get("task_count"))
    with_runs = sum(1 for row in rows if row.get("run_count"))
    total = len(rows)
    summary = [
        f"候选资产数：**{total}**",
        f"已同步表：**{_ratio(synced, total)}**",
        f"字段覆盖：**{_ratio(with_columns, total)}**",
        f"质量规则覆盖：**{_ratio(with_quality, total)}**",
        f"血缘覆盖：**{_ratio(with_lineage, total)}**",
        f"任务覆盖：**{_ratio(with_tasks, total)}**",
        f"运行实例覆盖：**{_ratio(with_runs, total)}**",
    ]
    return _section("核心候选资产覆盖", summary) + "\n\n" + _table(
        ["表名", "核心等级", "价值分层", "领域", "Owner", "已同步", "字段", "质量规则", "血缘", "任务", "运行实例", "缺口"],
        [
            [
                row.get("name"),
                row.get("core_level"),
                row.get("value_tier"),
                row.get("domain"),
                row.get("owner"),
                "Y" if row.get("table_synced") else "N",
                row.get("column_count"),
                row.get("quality_rule_count"),
                (row.get("upstream_count") or 0) + (row.get("downstream_count") or 0),
                row.get("task_count"),
                row.get("run_count"),
                "、".join(row.get("gaps") or []),
            ]
            for row in rows
        ],
    )


def _format_next_actions(health, coverage):
    counts = health.get("counts", {})
    actions = []
    if counts.get("tasks", 0) == 0:
        actions.append("优先跑通 `ListTasks`，补齐任务和任务表映射。")
    if counts.get("data_sources", 0) == 0:
        actions.append("开启 `WEDATA_SYNC_DATA_SOURCES=1`，补齐数据源和数据源关联任务。")
    if counts.get("task_runs", 0) == 0:
        actions.append("用小窗口开启 `WEDATA_SYNC_INSTANCES=1`，补齐任务运行实例。")
    if counts.get("columns", 0) == 0 or counts.get("lineage_edges", 0) == 0 or counts.get("quality_rules", 0) == 0:
        actions.append("开启 `WEDATA_SYNC_METADATA=1` 并限制 `WEDATA_METADATA_TABLE_LIMIT`，补齐字段、血缘、质量规则。")
    if not coverage.get("layers"):
        actions.append("当前没有表资产，先确认 `ListTasks` 或 `ListTable` 是否能返回真实表。")
    return _section("建议下一步", actions or ["当前基础覆盖较完整，下一步可抽样核对真实 WeData 页面和 MCP 返回是否一致。"])


def _section(title, lines):
    body = "\n".join(f"- {line}" for line in lines)
    return f"## {title}" + (f"\n\n{body}" if body else "")


def _table(headers, rows):
    if not rows:
        return "_无数据_"
    header = "| " + " | ".join(headers) + " |"
    sep = "| " + " | ".join(["---"] * len(headers)) + " |"
    body = ["| " + " | ".join(_cell(value) for value in row) + " |" for row in rows]
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


def _split_csv(value):
    return [item.strip() for item in (value or "").split(",") if item.strip()]


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


if __name__ == "__main__":
    main()
