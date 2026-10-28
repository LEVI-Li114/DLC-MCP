# DLC-MCP

面向 WeData 的数据资产 MCP 服务，可供 Codex 等客户端查询已同步的 WeData 数据资产、任务、元数据、质量规则、血缘、数据源、任务实例、指标定义和核心表决策。

面向用户的 MCP 查询为只读。腾讯云 AK/SK 保存在可信服务端；普通用户只需要 Gateway 地址和访问令牌。

## 用户安装

在终端执行：

```bash
DLC_MCP_GATEWAY_TOKEN=your-token npx -y @levisli/dlc-mcp install-codex
```

如果 Gateway 地址不是默认值：

```bash
DLC_MCP_GATEWAY_URL=https://64.186.234.87/mcp \
DLC_MCP_GATEWAY_TOKEN=your-token \
  npx -y @levisli/dlc-mcp install-codex
```

安装器会写入以下 Codex 配置：

> **本地开发提示：** 如果在 `@levisli/dlc-mcp` 源码仓库目录直接运行普通 `npx`，npm 可能优先解析当前包。生成的配置使用系统临时目录作为 `--prefix`，以避免该冲突。

```toml
[mcp_servers.dlc-mcp]
command = "npx"
args = ["--yes", "--prefix", "/private/tmp", "@levisli/dlc-mcp@0.1.9"]
type = "stdio"

[mcp_servers.dlc-mcp.env]
DLC_MCP_GATEWAY_URL = "https://64.186.234.87/mcp"
DLC_MCP_GATEWAY_TOKEN = "your-token"
```

重启 Codex 后，可以尝试提问：

- `dws_360_fin_job_seat_1d_di 统计了哪些指标？`
- `ads_bill_company_1d_di 今天执行耗时是多少？`
- `dwd_call_sms_instance_bill_di 是不是核心表？`
- `tech_support 这个数据源关联了多少任务？`

普通数据查询应直接使用 `dlc-mcp` MCP 工具，不要通过 shell、`curl` 或 `ssh` 绕过 MCP。

## WeData 告警分析 Agent

本仓库提供任务实例和日志查询 MCP 工具，也保留独立告警 Webhook 与队列作为备用接入方式；**不包含 Agent、LLM 或飞书发送运行时**。

生产主流程由 WeData 将告警直接推送给 Agent：Agent 从告警内容识别任务和实例日期，调用 `get_task_runs` 匹配运行实例，再用实例键调用 `get_task_instance_log` 获取日志，分析后由 Agent 发送飞书通知。飞书凭证由 Agent 管理。告警中的 `CreateTime` 不一定是实例日期，信息不足时应先查询近期实例再匹配。

若 Agent 直接接收告警的链路不可用，可使用备用 Webhook 队列：Webhook 接收服务校验并持久化告警，Agent 调用 `claim_wedata_alerts` 领取、处理后调用 `complete_wedata_alert` 记录 `completed` 或 `failed`。备用 Webhook 与 MCP Gateway 必须使用相同的 `DLC_MCP_DB`。

## 服务端部署与配置

服务端设置、WeData 凭证、同步任务、定时任务、Gateway 启动和冒烟测试见 [服务端 WeData 接入说明](docs/server-mcp-wedata-flow.md)。

项目架构与各层边界见[架构说明](docs/architecture.md)。核心表与资产价值评分见[核心表模型说明](docs/core-table-model.md)。普通用户访问和令牌管理见[用户访问说明](docs/user-access.md)。

## 查询模式

面向用户的服务使用显式数据来源模式，不会把所有 SQLite 数据都当作实时事实。

DLC MCP 的主要数据来源：

- `registry`：SQLite 索引，保存表、任务、数据源和项目信息。
- `live`：腾讯云、DLC、WeData API 的当前结果，用于分区、任务实例、质量、血缘和任务代码等动态事实。
- `patrol_snapshot`：某次每日巡检的快照，用于治理报告和问题清单。

默认 `source=auto` 行为：

- 单表和单任务诊断使用 `live`。
- 搜索和列表工具使用 `registry`。
- 治理报告和问题清单使用最新的 `patrol_snapshot`。

仅在排查旧 SQLite 动态事实时使用 `source=legacy_cache`；该缓存不代表当前真实状态。

查询失败会报告为 `check_failed` 或 `partial_live`，不会被误判为分区、任务实例、质量规则或血缘确实不存在。

查询模式不会修改远端 WeData/DLC 业务对象，但可能读取远端元数据、代码和项目信息，并更新本地 SQLite 注册表或巡检快照。工具通过 MCP `readOnlyHint` 注解声明只读属性；支持注解的客户端可以据此进行更安全的自动批准，但确认提示仍由 MCP Host 控制。

## 资产巡检模式

资产巡检复用现有服务注册表保存稳定事实，并在巡检期间实时刷新动态证据。

稳定缓存/注册表证据：

- 表元数据
- 字段
- 表血缘
- 数据源
- 核心表决策

仅实时获取并写入巡检快照、发现和错误记录的证据：

- 关联任务及生产任务覆盖情况
- 任务详情和任务依赖
- 质量状态
- 生产状态和任务实例

每日核心资产巡检：

```bash
python3 -m dlc_mcp.asset_patrol --scope daily_core --instance-date 2026-07-16 --limit 100
```

按批次执行月度全量巡检：

```bash
python3 -m dlc_mcp.asset_patrol --scope monthly_full --instance-date 2026-07-16 --limit 500 --batch-size 500 --offset 0
```

手动巡检指定表：

```bash
python3 -m dlc_mcp.asset_patrol --scope manual --table ads_360_fin_income_cost_1d_di --instance-date 2026-07-16
```

`daily_p0` 仍作为兼容巡检范围保留。

巡检默认优先保证完整性，而非激进压缩运行时间：并发数为 3，每张表超时为 120 秒，重试 2 次，重试退避 2 秒，API 调用间隔 0.2 秒，失败阈值为 0.3。检查缓慢或失败会记录在 `patrol_errors` 并标记为 `check_failed`，不会被视为已确认的数据缺失。

巡检写入以下数据表：

- `patrol_runs`
- `patrol_asset_snapshots`
- `patrol_findings`
- `patrol_metrics`
- `patrol_errors`

治理报告工具读取同一个巡检 `run_id`，保证报告证据的时间一致性。如果没有巡检快照，工具会提示先运行巡检，而不会回退到旧动态缓存。

## MCP 工具

新增 MCP 工具时，请同步更新本列表。

| 工具 | 用途 |
| --- | --- |
| `search_assets(query)` | 按名称、领域或描述搜索表资产。 |
| `search_tasks(query, live)` | 按任务 ID、名称、负责人或状态搜索 WeData 任务。 |
| `get_table_profile(table_name, sections, live)` | 返回元数据、字段、血缘、质量摘要、关联任务和核心表决策；`sections` 可限定返回部分，`columns`、`quality`、`lineage` 分别对应字段、质量和血缘。 |
| `get_table_partition_profile(table_name, partition_date)` | 返回分区数据量、近期分区和分区健康情况。 |
| `get_task_runs(task_id/task_name, instance_date, live)` | 按任务 ID 或名称查询任务实例的开始时间、结束时间、耗时和状态。 |
| `get_task_instance_log(instance_key, ...)` | 使用 `get_task_runs` 返回的实例键获取一页 WeData 任务实例日志。 |
| `claim_wedata_alerts(limit)` | 领取待处理的 WeData Webhook 告警，领取后状态变为 `processing`。 |
| `complete_wedata_alert(alert_id, status, analysis)` | 备用队列流程：保存 Agent 分析并将告警标记为完成或失败；飞书消息由 Agent 发送。 |
| `get_task_code(task_id/task_name, live)` | 返回缓存或实时刷新的 WeData 任务 SQL/代码，以及从 SQL 解析出的输出表。离线同步任务无法获取代码时，根据任务定义的源/目标配置解析输入和输出表，必要时回退到 WeData 任务血缘。 |
| `list_tasks(keyword, task_type, owner, limit, offset, live)` | 分页列出 WeData 任务及总数；`live=true` 时按 `keyword` 调用 WeData `ListTasks` 实时刷新，且必须提供 `keyword`。 |
| `list_data_sources(query, live)` | 列出数据源、配置摘要和关联任务数。 |
| `get_data_source(data_source_id, live)` | 返回一个数据源的类型、负责人、关联任务数、描述和配置摘要。 |
| `list_projects(query, live)` | 列出从腾讯云 `ListProjects` 同步的 WeData 项目。 |
| `list_workflows(project_id, keyword, workflow_type)` | 实时查询 WeData 项目工作流列表；未提供项目 ID 时默认使用 `WEDATA_PROJECT_ID`。 |
| `create_wedata_task(...)` | 在 WeData 项目工作流中创建任务。 |
| `get_project(project_id, live)` | 返回 WeData 项目；未提供时默认使用 `WEDATA_PROJECT_ID`。 |
| `list_project_members(project_id, live)` | 列出 WeData 项目成员和角色。 |
| `list_task_relations(task_id, direction, project_id, live)` | 查询任务的上游或下游 WeData 依赖关系。 |
| `get_table(table_name/table_guid, live)` | 获取腾讯云 WeData 表元数据详情。 |
| `get_data_source_inventory(data_source_id/data_source_name, view, live)` | 返回数据源关联任务、解析出的表、SQL DDL 及未解析或字段缺失问题；`view=tasks` 仅返回关联任务列表。 |
| `list_asset_gaps(view, gap_type, layer, domain, limit)` | 列出存在治理缺口的表资产：`view=quality` 为高影响但缺少质量规则，`view=expert_review` 为高影响但未标注，`view=coverage` 为资产档案覆盖缺失，可按 `gap_type` 筛选。 |
| `list_metadata()` | 列出已导入的数据库和表元数据。 |
| `get_sync_health()` | 返回同步健康情况、资产数量、最新同步信号和当前数据缺口。 |
| `get_asset_coverage()` | 按字段、血缘、质量规则、任务、数据源和运行实例等层面统计资产覆盖率。 |
| `get_asset_governance_issue_inventory(layer, core_level, issue_type, limit)` | 返回确定性治理问题清单，包括证据、疑似根因、严重程度和建议的后续检查。 |
| `get_asset_governance_daily_report(instance_date, layer, core_level)` | 返回每日治理巡检报告。 |
| `submit_dlc_sql_query(sql, database_name, data_engine_name, datasource_connection_name)` | 向 DLC 提交一条 `SELECT`/`WITH`、`SHOW TABLES [LIKE pattern]`、`SHOW CREATE TABLE`、`DROP TABLE` 或 `ALTER TABLE` 语句；查询支持包括 `FULL OUTER JOIN` 在内的关联。 |
| `get_dlc_sql_query_result(task_id, next_token, max_results)` | 轮询 DLC SQL 任务并返回一页状态或结果。 |
| `backup_dlc_table_ddl(table_name, database_name, data_engine_name, datasource_connection_name, resource_group_name)` | 对一张 DLC 表执行 `SHOW CREATE TABLE`，返回 DDL 文本及建议的 `.sql` 文件名，供 MCP 客户端保存。 |
| `delete_dlc_tables(tables, confirmation)` | 使用 `DropDMSTable` 删除 DLC DMS 表定义（`DeleteData=false`），再通过实时 `SHOW TABLES LIKE` 检查。必须提供 `confirmation="DELETE TABLE DEFINITIONS"`。 |
| `get_dlc_task_resource_usage(task_instance_id, include_cost, cost_task_id, cost_start_time, cost_end_time, cost_limit)` | 查询指定 DLC `TaskInstanceId` 的引擎 Core 用量曲线，不会映射 WeData `instance_id`；可针对显式传入的 `cost_task_id` 附加 CU 消耗分析。 |

### DLC SQL 查询

配置 `DLC_QUERY_ENGINE`（建议在生产环境显式指定）以及可选的 `DLC_QUERY_DATABASE`、`DLC_QUERY_DATASOURCE` 后，先调用 `submit_dlc_sql_query`，再使用返回的 `task_id` 调用 `get_dlc_sql_query_result`。结果超过一页时，将返回的 `next_token` 传入下一次调用。

该入口默认使用 Spark SQL，支持一条 `SELECT`、`WITH`、`SHOW TABLES [LIKE pattern]`、`SHOW CREATE TABLE`、`DROP TABLE` 或 `ALTER TABLE` 语句；提交前会拒绝多语句。`DROP TABLE` 和 `ALTER TABLE` 可能改变或删除表结构/数据，请谨慎使用。设置 `DLC_QUERY_TASK_TYPE=presto` 可切换为 Presto SQLTask。

### 表 DDL 备份

`backup_dlc_table_ddl` 对单表执行 `SHOW CREATE TABLE`，返回完整 DDL 原文和建议的 `.sql` 文件名，由 MCP 客户端保存到本地。服务端不需要配置本地备份目录，也不负责写入客户端文件系统。该工具仅读取表结构，不修改远端表。

### DLC 任务资源查询

`get_dlc_task_resource_usage` 使用显式传入的 DLC `TaskInstanceId` 调用 `DescribeTaskResourceUsage`，返回引擎侧 Core 用量曲线。不会将 WeData `instance_id` 隐式映射为 DLC 实例 ID。

设置 `include_cost=true` 并传入独立的 `cost_task_id` 时，会额外调用 `DescribeTasksAnalysis`（`task-id` 过滤器，按 `task-time-sum` 排序）返回 CU 资源消耗分析。`cost_task_id` 不会从 `task_instance_id` 推导。统计窗口默认最近 7 天，可用 `cost_start_time`/`cost_end_time`（格式 `yyyy-mm-dd HH:MM:SS`）指定，跨度不得超过 30 天。Core 曲线与 CU 消耗是不同指标，不能互相换算。

项目、成员、任务关系和表详情工具采用与现有资产工具相同的“缓存优先”查询模式。默认先读 SQLite，仅在缓存事实缺失或不完整时实时刷新；设置 `live=true` 可强制从 WeData 刷新所请求的事实。`GetTable` 实时刷新需要真实表 GUID；服务不会根据任务名称推断表名。

资产完整性应通过 `get_sync_health`、`get_asset_coverage` 和 `list_asset_gaps`（`view=coverage`）检查。API 回填成功只说明对应事实已采集，不代表所有表的字段、血缘、质量规则、任务映射、运行实例和数据源关联都已完整。

任务输入/输出映射来自真实 `GetTask` 定义。数据集成节点配置会进行 Base64 解码，SQL 任务会解析返回的 SQL；不会根据任务名称推断输入或输出表。任务实例默认保留最近 7 个日历日，可通过 `DLC_MCP_TASK_RUN_RETENTION_DAYS` 配置。质量规则以项目分页全量列表为准；全量同步成功后会替换过期缓存。

## 开发与测试

运行测试和基础检查：

```bash
python3 -m unittest discover -s tests -v
node --check bin/dlc-mcp.js
npm pack --dry-run
```

测试通过后发布：

```bash
NPM_TOKEN=your-npm-token bash publish-npm.sh
```

