# DLC-Agent Project Rules

## Tool Boundary

- 查数据：走 `dlc-mcp` MCP server。
- 部署、补数、重启、查日志：走 `ssh`。
- Query asset data only through the native `dlc-mcp` MCP tools loaded by Codex.
- Never downgrade a data query to `ssh`, an SSH tunnel, `curl`, direct Gateway HTTP, or direct SQLite access.
- If native `dlc-mcp` tools are unavailable, stop the query and report that Codex must reload or the MCP configuration must be repaired.
- Use `ssh` only for deployment, backfill, service restart, and log inspection.

## Task Lineage

- Treat "downstream" as the first-level downstream task dependency unless the user explicitly asks for downstream table lineage.
- For data-source task, downstream task, output-table, or DDL requests, follow `.agents/skills/dlc-task-lineage/SKILL.md`.
- Never infer an input or output table from a task name.

## Architecture Boundary

- MCP Tools 层：用户只调用工具，输出治理结论、DDL、任务、血缘、缺口。
- Live Connector 层：封装 WeData/DLC API，负责分页、重试、限流、字段解析。
- Asset Store 层：SQLite 缓存/资产图谱，存事实、证据、刷新状态，支持跨资产分析。
- Sync Jobs / Admin Ops 层：全量补数、增量同步、重启服务、查日志。

普通数据查询不要绕过 MCP tools 去读 SQLite、跑 `curl` 或走 `ssh`。只有运维动作才使用 `ssh`。
