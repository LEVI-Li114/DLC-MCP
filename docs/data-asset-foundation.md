# DLC-MCP 已有能力与数据资产底座推进计划

> 目标：先打好百应数据资产知识库的数据底座，确保 WeData/DLC 资产数据“全、准、稳、可追溯、可持续刷新”，再继续推进核心资产判断、质量风险解释和 BI 指标口径。

## 1. 背景

根据《百应数据资产知识库与质量监控 Agent OKR 时间线》，当前第 1 阶段目标是：

- 稳定资产采集底座。
- 完成 WeData/DLC 核心资产采集。
- 覆盖表、任务、数据源、字段、血缘、质量规则、运行实例。
- 确认 MCP 工具清单。
- 为后续表资产画像、核心表判断模型、质量监控 Agent 打基础。

当前项目已经具备 MCP Server、HTTP Gateway、npm 接入、SQLite 资产库、WeData 同步脚手架、资产健康和覆盖度工具。下一步不应优先做复杂 Agent，而应先把底层资产数据采集和覆盖缺口治理跑稳。

## 2. 已有能力盘点

### 2.1 MCP Server 框架已完成

已有能力：

- `tools/list`
- `tools/call`
- Markdown 格式化输出

说明：

- MCP 协议处理集中在 `dlc_mcp/mcp.py`。
- 工具列表由 `TOOLS` 统一声明。
- 工具调用后返回结构化 Markdown，便于 Codex 直接展示。

### 2.2 HTTP Gateway 已完成

已有能力：

- `/health`
- `/mcp`
- Bearer token 鉴权

说明：

- HTTP Gateway 入口在 `dlc_mcp/gateway.py`。
- `/health` 用于服务健康检查。
- `/mcp` 用于接收 MCP JSON-RPC 请求。
- 支持 `Authorization: Bearer <token>` 和 `x-dlc-mcp-token`。
- 腾讯云 AK/SK 留在服务端，普通用户只需要 Gateway URL 和 token。

### 2.3 npm 接入已完成

已有能力：

- npm 包：`@levisli/dlc-mcp`
- 安装命令：`install-codex`
- 自动写入 Codex MCP 配置

说明：

- Node CLI 入口在 `bin/dlc-mcp.js`。
- 普通用户可通过以下命令接入：

```bash
DLC_MCP_GATEWAY_TOKEN=your-token npx -y @levisli/dlc-mcp install-codex
```

- 如需指定 Gateway：

```bash
DLC_MCP_GATEWAY_URL=http://64.186.234.87:8787/mcp \
DLC_MCP_GATEWAY_TOKEN=your-token \
  npx -y @levisli/dlc-mcp install-codex
```

### 2.4 SQLite 资产库已有模型

已有模型：

- 表资产
- 字段
- 血缘
- 质量规则
- 任务
- 任务运行实例
- 数据源
- 数据源关联任务
- 专家标签

说明：

- SQLite 数据层集中在 `dlc_mcp/assets.py` 的 `AssetStore`。
- 默认本地数据库为 `data/assets.db`。
- 生产建议数据库为 `/data/dlc-mcp/assets.db`。
- 这些模型已经可以支撑表画像、核心资产判断、质量监控和覆盖缺口分析。

### 2.5 WeData 同步已有脚手架

已有 WeData API 同步能力：

- `ListTasks`
- `ListTable`
- `GetTableColumns`
- `ListLineage`
- `ListQualityRules`
- `ListDataSources`
- `GetDataSourceRelatedTasks`
- `ListTaskInstances`

说明：

- 同步入口在 `dlc_mcp/sync_wedata.py`。
- 部署脚本为 `deploy/sync-wedata-incremental.sh`。
- 同步过程会把原始 WeData JSON dump 保存到同步目录，便于追溯。
- 同步后的结构化数据写入 SQLite 资产库。

### 2.6 已有资产健康和覆盖度工具

已有 MCP 工具：

- `get_sync_health`
- `get_asset_coverage`
- `list_asset_coverage_gaps`

说明：

- `get_sync_health` 用于查看同步健康状态、资产数量、最新同步信号和当前数据缺口。
- `get_asset_coverage` 用于查看按层级统计的资产覆盖情况。
- `list_asset_coverage_gaps` 用于列出缺字段、缺血缘、缺质量规则、缺任务、缺运行实例等资产覆盖缺口。

这三个工具应成为数据资产底座阶段的主控台。

## 3. 当前阶段主线

当前阶段优先级：

1. 跑稳 WeData 同步。
2. 固化同步配置。
3. 建立同步健康检查。
4. 建立资产覆盖率和缺口清单。

目标不是马上增加更多问答能力，而是让现有工具背后的数据变得可信、稳定、可解释。

## 4. 执行项 1：跑稳 WeData 同步

### 4.1 目标

确保 WeData 同步脚本可以稳定、重复、可观测地同步核心资产数据。

### 4.2 覆盖对象

必须优先覆盖：

| 对象 | 用途 | 优先级 |
| --- | --- | --- |
| 表目录 | 资产入口 | P0 |
| 字段 | 表画像、指标口径 | P0 |
| 任务 | 产出链路、运行状态 | P0 |
| 任务输入输出表 | 表与任务关系 | P0 |
| 数据源 | 来源治理 | P0 |
| 数据源关联任务 | 影响分析 | P0 |
| 血缘 | 上下游依赖 | P0 |
| 质量规则 | 质量监控 | P0 |
| 任务运行实例 | 产出时效、稳定性 | P0 |
| 专家标签 | 核心表人工校准 | P1 |

### 4.3 推荐小样本同步命令

第一轮不要直接全量，建议先小样本跑稳：

```bash
WEDATA_SYNC_TABLE_CATALOG=1 \
WEDATA_SYNC_METADATA=1 \
WEDATA_METADATA_TABLE_LIMIT=50 \
WEDATA_SYNC_DATA_SOURCES=1 \
WEDATA_SYNC_INSTANCES=1 \
WEDATA_INSTANCE_MAX_PAGES=20 \
bash deploy/sync-wedata-incremental.sh
```

如果任务实例量太大，先加关键词限制：

```bash
WEDATA_INSTANCE_KEYWORDS=ads_bill_company_1d_di,dws_360_fin_job_seat_1d_di \
bash deploy/sync-wedata-incremental.sh
```

### 4.4 验收标准

同步完成后至少确认：

- WeData 任务能同步。
- 表目录能同步。
- 字段能同步。
- 数据源能同步。
- 数据源关联任务能同步。
- 任务运行实例能同步。
- raw JSON dump 已保存。
- SQLite 中有结构化资产数据。
- MCP smoke test 可以列出工具并查询资产。

## 5. 执行项 2：固化同步配置

### 5.1 目标

把同步所需环境变量沉淀为标准配置，减少每次手工拼命令导致的不一致。

### 5.2 推荐服务端配置

建议服务端 `/etc/dlc-mcp/env` 至少包含：

```bash
TENCENTCLOUD_SECRET_ID=your-secret-id
TENCENTCLOUD_SECRET_KEY=your-secret-key
TENCENTCLOUD_REGION=ap-guangzhou
WEDATA_VERSION=2025-08-06
WEDATA_PROJECT_ID=your-project-id

DLC_MCP_DB=/data/dlc-mcp/assets.db
DLC_MCP_SYNC_DIR=/data/dlc-mcp/sync

WEDATA_PAGE_SIZE=100
WEDATA_SYNC_TABLE_CATALOG=1
WEDATA_SYNC_METADATA=1
WEDATA_METADATA_TABLE_LIMIT=100
WEDATA_METADATA_TABLES=
WEDATA_METADATA_WORKERS=4

WEDATA_SYNC_DATA_SOURCES=1
WEDATA_SYNC_INSTANCES=1
WEDATA_INSTANCE_LOOKBACK_DAYS=2
WEDATA_INSTANCE_KEYWORDS=
WEDATA_INSTANCE_MAX_PAGES=50
WEDATA_INSTANCE_START=
WEDATA_INSTANCE_END=
WEDATA_INSTANCE_TIMEZONE=UTC+8

DLC_MCP_GATEWAY_HOST=0.0.0.0
DLC_MCP_GATEWAY_PORT=8787
DLC_MCP_GATEWAY_TOKEN=replace-with-random-token
```

### 5.3 配置分层建议

- **必填配置**：腾讯云 AK/SK、Region、WeData Project ID、数据库路径。
- **同步范围配置**：是否同步 metadata、data sources、instances。
- **规模控制配置**：分页大小、metadata 表数量、实例最大页数、实例关键词。
- **服务配置**：Gateway host、port、token。

### 5.4 验收标准

- `deploy/env.example` 能表达所有关键配置。
- `deploy/sync-wedata-incremental.sh` 能加载标准配置运行。
- 文档中明确小样本、扩大样本、定时同步三类配置方式。

## 6. 执行项 3：建立同步健康检查

### 6.1 目标

每次同步完成后，能快速判断当前资产库是否健康。

### 6.2 固定检查项

每次同步后至少检查：

```text
1. 总表数
2. 总任务数
3. 总数据源数
4. 字段覆盖表数
5. 血缘覆盖表数
6. 质量规则覆盖表数
7. 任务关联覆盖表数
8. 任务运行实例数量
9. 最新任务运行实例时间
10. 当前主要数据缺口
```

### 6.3 可读检查命令

同步后优先使用资产底座检查 CLI，直接输出 Markdown 摘要，不带 JSON-RPC 外壳：

```bash
python3 -m dlc_mcp.check_foundation \
  --db /data/dlc-mcp/assets.db \
  --gap-types fields,lineage,quality,tasks,runs,data_source \
  --gap-limit 20
```

也可以使用部署脚本读取 `/etc/dlc-mcp/env` 后检查：

```bash
bash deploy/check-asset-foundation.sh /etc/dlc-mcp/env
```

如需验证 MCP 工具本身，仍可通过 MCP 调用：

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"get_sync_health","arguments":{}}}
```

### 6.4 验收标准

- 每次同步后能输出健康摘要。
- 健康摘要能说明同步数量和数据缺口。
- 如果同步失败或关键覆盖为 0，能快速定位到任务、表、字段、血缘、质量、实例中的具体缺口。

## 7. 执行项 4：建立资产覆盖率和缺口清单

### 7.1 目标

从“有没有数据”推进到“哪些资产画像不完整”，用缺口清单驱动后续补数和治理。

### 7.2 覆盖率视角

固定看这些覆盖维度：

| 覆盖维度 | 说明 |
| --- | --- |
| fields / columns | 表是否有字段 |
| lineage | 表是否有上下游血缘 |
| quality_rules | 表是否有质量规则 |
| tasks | 表是否有关联任务 |
| data_sources | 表是否有关联数据源 |
| runs | 表或任务是否有运行实例 |
| owner | 表或任务是否有负责人 |

### 7.3 可读覆盖检查命令

资产覆盖率和缺口清单优先通过同一个资产底座检查 CLI 输出：

```bash
python3 -m dlc_mcp.check_foundation \
  --db /data/dlc-mcp/assets.db \
  --gap-types fields,lineage,quality,tasks,runs,data_source \
  --gap-limit 50
```

缺口类型说明：

| gap_type | 说明 |
| --- | --- |
| `fields` | 缺字段 |
| `lineage` | 缺上游或下游血缘 |
| `quality` | 缺质量规则 |
| `tasks` | 缺任务关联 |
| `runs` | 缺运行实例 |
| `data_source` | 缺数据源关联 |

按需只检查部分缺口：

```bash
python3 -m dlc_mcp.check_foundation \
  --db /data/dlc-mcp/assets.db \
  --gap-types tasks,runs,data_source \
  --gap-limit 20
```

MCP 工具仍保留给 Codex/Agent 使用：`get_asset_coverage` 和 `list_asset_coverage_gaps`。

### 7.4 验收标准

- 能按层级看到资产覆盖率。
- 能列出缺字段、缺血缘、缺质量规则、缺任务、缺运行实例的表。
- 能输出 Top 缺口清单。
- 后续可以根据缺口清单反向修同步配置或推动 Owner 补齐数据。

## 8. 本周建议交付物

当前周期：2026-07-06 至 2026-07-10。

本周建议交付：

1. **资产底座能力盘点文档**：本文档。
2. **标准同步配置 V0.1**：固化 `/etc/dlc-mcp/env` 推荐项和 `deploy/env.example`。
3. **同步健康检查 V0.1**：同步后可直接运行 `get_sync_health`。
4. **资产覆盖报告 V0.1**：可直接运行 `get_asset_coverage` 和 `list_asset_coverage_gaps`。
5. **第一批核心资产候选表清单 V0.1**：后续用于表画像和核心表模型验收。

## 9. 下一步执行顺序

建议按以下顺序逐项推进：

### Step 1：验证 WeData 同步链路

- 检查同步脚本和环境变量。
- 小样本跑通任务、表目录、字段、数据源、实例同步。
- 对失败项记录原因。

### Step 2：固化配置

- 对齐 `deploy/env.example` 与实际同步脚本支持的环境变量。
- 增加推荐小样本配置和生产配置说明。
- 降低手工执行差异。

### Step 3：同步后健康检查

- 明确 smoke test 命令。
- 必要时增强部署脚本，在同步后自动执行健康检查。
- 输出同步健康摘要。

### Step 4：资产覆盖率与缺口清单

- 固定输出覆盖率。
- 固定输出缺口清单。
- 把缺口分为同步配置问题、WeData 源数据问题、解析映射问题、治理补录问题。

## 10. 风险与注意事项

1. **不要直接全量跑大实例同步**：`ListTaskInstances` 可能数据量大，应先用 lookback days、keywords、max pages 控制范围。
2. **不要把 AK/SK 放入代码或 npm 包**：腾讯云凭证必须只放服务端 `/etc/dlc-mcp/env`。
3. **不要只看工具是否返回成功**：要看覆盖率和缺口，否则返回成功也可能是空数据。
4. **不要先做复杂 Agent 解释**：底层数据不完整时，解释越自然风险越大。
5. **raw dump 要保留**：便于排查 API 返回、字段映射、SQLite 导入之间的差异。

## 11. 执行记录：本地资产底座检查

执行时间：2026-07-07。

执行命令：

```bash
DLC_MCP_DB=data/assets.db DLC_MCP_SYNC_GAP_LIMIT=10 bash deploy/check-asset-foundation.sh
```

### 11.1 检查结论

本地 `data/assets.db` 当前更接近 seed/demo 数据库，不是完整真实 WeData 同步结果。

MCP smoke test 已通过：

```text
MCP smoke test passed
```

同步健康状态：

```text
partial
```

当前资产数量：

| 资产类型 | 数量 |
| --- | ---: |
| 表资产 | 1 |
| 字段 | 3 |
| 任务 | 0 |
| 任务表映射 | 0 |
| 运行实例 | 0 |
| 数据源 | 0 |
| 数据源关联任务 | 0 |
| 血缘边 | 2 |
| 质量规则 | 2 |
| 专家标注 | 0 |

当前已有覆盖：

- 表资产：`ads_customer_revenue_daily`
- 层级：`ads`
- 字段覆盖：`1/1 (100%)`
- 质量规则覆盖：`1/1 (100%)`
- 上游血缘覆盖：`1/1 (100%)`
- 下游血缘覆盖：`1/1 (100%)`

当前主要缺口：

- 未同步 WeData 任务列表。
- 未同步任务表映射。
- 未同步任务运行实例。
- 未同步数据源。
- 未同步数据源关联任务。

缺口表：

| 表名 | 层级 | 负责人 | 缺口 |
| --- | --- | --- | --- |
| `ads_customer_revenue_daily` | ads | data-finance | 缺相关任务、缺运行实例、缺数据源关联 |

### 11.2 结果判断

本地资产库已能验证 MCP 查询、字段、血缘、质量规则和覆盖缺口工具的可用性，但不能作为真实资产底座验收依据。

下一步应在服务端使用真实 `/etc/dlc-mcp/env` 跑小样本 WeData 同步，优先把以下数量补到非 0：

- `tasks`
- `task_table_mappings`
- `task_runs`
- `data_sources`
- `data_source_tasks`

## 12. 下一轮服务端小样本同步 Runbook

### 12.1 目标

在真实服务端环境中，用受控范围跑通完整采集链路：

```text
ListTasks -> ListTable -> GetTableColumns -> ListLineage -> ListQualityRules -> ListDataSources -> GetDataSourceRelatedTasks -> ListTaskInstances
```

目标不是立刻全量同步，而是先确认任务、数据源、运行实例三条当前缺口链路可用。

### 12.2 推荐服务端配置

建议先在 `/etc/dlc-mcp/env` 使用保守配置：

```bash
DLC_MCP_DB=/data/dlc-mcp/assets.db
DLC_MCP_SYNC_DIR=/data/dlc-mcp/sync
DLC_MCP_PYTHON=python3

WEDATA_PAGE_SIZE=100
WEDATA_SYNC_TABLE_CATALOG=1

WEDATA_SYNC_METADATA=1
WEDATA_METADATA_TABLE_LIMIT=50
WEDATA_METADATA_TABLES=
WEDATA_METADATA_WORKERS=4

WEDATA_SYNC_DATA_SOURCES=1

WEDATA_SYNC_INSTANCES=1
WEDATA_INSTANCE_LOOKBACK_DAYS=2
WEDATA_INSTANCE_KEYWORDS=
WEDATA_INSTANCE_MAX_PAGES=20
WEDATA_INSTANCE_START=
WEDATA_INSTANCE_END=
WEDATA_INSTANCE_TIMEZONE=UTC+8

DLC_MCP_SYNC_HEALTH_CHECK=1
DLC_MCP_SYNC_GAP_TYPES=fields,lineage,quality,tasks,runs,data_source
DLC_MCP_SYNC_GAP_LIMIT=20
```

如果 `ListTaskInstances` 数据量过大或接口耗时，先限制关键词：

```bash
WEDATA_INSTANCE_KEYWORDS=ads_bill_company_1d_di,dws_360_fin_job_seat_1d_di
WEDATA_INSTANCE_MAX_PAGES=20
```

### 12.3 执行命令

在服务端执行：

```bash
cd /opt/dlc-mcp/DLC-MCP
bash deploy/sync-wedata-incremental.sh /etc/dlc-mcp/env
```

如果只想检查当前资产库，不重新同步：

```bash
cd /opt/dlc-mcp/DLC-MCP
bash deploy/check-asset-foundation.sh /etc/dlc-mcp/env
```

### 12.4 验收标准

同步后健康检查中，下列数量应大于 0：

| 指标 | 期望 |
| --- | --- |
| 表资产 | `> 0` |
| 字段 | `> 0` |
| 任务 | `> 0` |
| 任务表映射 | `> 0` |
| 数据源 | `> 0` |
| 数据源关联任务 | `> 0` |
| 运行实例 | `> 0`，如果实例同步已开启 |
| 血缘边 | `> 0`，如果 metadata 表命中 |
| 质量规则 | `> 0`，如果 WeData 有规则且接口权限可用 |

资产覆盖率中重点看：

- ads/dws/dwd 层是否出现真实表。
- `有字段` 覆盖率是否大于 0。
- `有关联任务` 覆盖率是否大于 0。
- `有数据源` 覆盖率是否大于 0。
- `tasks`、`runs`、`data_source` 三类缺口是否下降。

### 12.5 如果仍然缺数据，按以下顺序排查

#### 任务仍为 0

优先检查：

- `WEDATA_PROJECT_ID` 是否是数字项目 ID。
- `ListTasks` 是否能手动返回数据。
- 腾讯云 AK/SK 是否有 WeData 项目权限。

手动验证：

```bash
python3 -m dlc_mcp.call_wedata_api ListTasks '{"ProjectId":"'$WEDATA_PROJECT_ID'","PageNumber":1,"PageSize":10}'
```

#### 数据源仍为 0

优先检查：

- `WEDATA_SYNC_DATA_SOURCES=1` 是否生效。
- `ListDataSources` 是否有权限。
- 返回字段是否和当前解析逻辑匹配。

#### 运行实例仍为 0

优先检查：

- `WEDATA_SYNC_INSTANCES=1` 是否生效。
- 时间窗口是否有真实实例。
- `WEDATA_INSTANCE_KEYWORDS` 是否过滤过严。
- `WEDATA_INSTANCE_MAX_PAGES` 是否太小。

## 13. 核心资产判断模型 V1

### 13.1 判断原则

核心资产判断采用“机器初判 + 人工标注校准”的方式：

```text
表血缘影响 + 上下游任务依赖 + 表层级 + 质量治理 + 运行稳定性 + 业务信号
  -> 机器初判
  -> 人工标注覆盖或加权
  -> 最终核心资产判断
```

### 13.2 机器初判维度

机器模型会输出分维度得分：

| 维度 | 说明 |
| --- | --- |
| `downstream_lineage` | 下游血缘资产数量，代表影响范围 |
| `task_dependency` | 产出任务和消费任务数量，消费任务权重更高 |
| `layer_position` | 表所在层级，ads/dws/dwd/dim/ods 分层加权 |
| `quality_governance` | 质量规则数量，代表治理成熟度 |
| `run_stability` | 最近产出任务实例是否成功 |
| `business_signal` | 财务、账单、收入、客户等业务关键词或领域信号 |
| `usage_heat` | 预留使用热度，目前为 0 |

任务依赖中：

- `consumer_task_count` 表示消费该表的任务数，体现下游生产链路依赖。
- `producer_task_count` 表示产出该表的任务数，体现产出链路。
- 消费任务比产出任务权重更高。

### 13.3 人工标注融合

人工标注来自 `expert_labels`，也就是核心候选清单导入后的数据。

融合规则：

- 如果人工标注明确 `core_level`，最终等级以人工标注为准。
- 如果人工标注只有 `value_tier`，则对机器分进行软加权。
- 最终结果仍保留机器分，便于发现人工和机器判断差异。

### 13.4 输出结构

`get_asset_value_profile` 和 `is_core_table` 会保留兼容字段：

```text
is_core
score
core_level
value_tier
source
```

并新增：

```text
machine     机器初判
manual      人工标注摘要
final       最终判断
confidence  置信度
gaps        当前数据缺口
review_suggestion 复核建议
```

### 13.5 置信度和复核建议

置信度会结合数据缺口和人工标注：

- 缺血缘、缺任务、缺运行实例会降低置信度。
- 有明确人工 `core_level` 时，置信度会提高，但如果关键数据缺口过多仍为 medium。
- 如果机器高分但没有人工标注，会提示补充人工确认。
- 如果人工标注与机器评分差异较大，会提示复核血缘、任务依赖和业务使用场景。

### 13.6 查询方式

MCP 查询：

```text
is_core_table(table_name="ads_bill_company_1d_di")
get_asset_value_profile(table_name="ads_bill_company_1d_di")
```

Codex 可直接问：

```text
ads_bill_company_1d_di 是不是核心表？机器和人工判断依据分别是什么？
```
## 14. 核心资产候选清单 V0.1

### 14.1 目标

用一份轻量 CSV 明确第一批重点验收资产，避免资产底座治理陷入全量无优先级补数。

核心候选清单用于回答：

- 第一批要重点补全画像的表有哪些？
- 哪些核心候选表还没有同步进资产库？
- 哪些核心候选表缺字段、血缘、质量规则、任务、运行实例或数据源？
- 后续核心表判断模型和专家复核应该优先看哪些表？

### 14.2 CSV 模板

模板文件：

```text
docs/core-asset-candidates.csv
```

字段：

```csv
asset_name,layer,domain,owner,use_case,core_level,value_tier,reviewer,reason,metric_definition
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `asset_name` | 表名，必填 |
| `layer` | 表层级，例如 `ads`、`dws`、`dwd` |
| `domain` | 业务领域，例如财务分析、业务分析 |
| `owner` | 资产 Owner |
| `use_case` | 使用场景 |
| `core_level` | 核心等级，例如 `P0`、`P1`、`P2` |
| `value_tier` | 价值分层，例如核心、重要、普通 |
| `reviewer` | 复核人或团队 |
| `reason` | 入选原因 |
| `metric_definition` | 指标口径备注，可先为空 |

### 14.3 导入命令

本地导入：

```bash
python3 -m dlc_mcp.import_core_candidates docs/core-asset-candidates.csv --db data/assets.db
```

服务端导入：

```bash
cd /opt/dlc-mcp/DLC-MCP
python3 -m dlc_mcp.import_core_candidates docs/core-asset-candidates.csv --db /data/dlc-mcp/assets.db
```

如已在 `/etc/dlc-mcp/env` 中配置 `DLC_MCP_DB`：

```bash
python3 -m dlc_mcp.import_core_candidates docs/core-asset-candidates.csv --env-file /etc/dlc-mcp/env
```

导入后会写入已有 `expert_labels` 表，作为第一批核心候选资产和专家标注来源。

### 14.4 检查候选资产覆盖

导入后执行：

```bash
python3 -m dlc_mcp.check_foundation --db data/assets.db
```

报告会增加：

```text
## 核心候选资产覆盖
```

其中会展示：

- 候选资产数。
- 已同步表覆盖率。
- 字段覆盖率。
- 质量规则覆盖率。
- 血缘覆盖率。
- 任务覆盖率。
- 运行实例覆盖率。
- 每张候选表的当前缺口。

## 15. 通用表资产治理就绪度报告

### 15.1 目标

资产画像和治理就绪度不只服务核心表，而应适用于所有表。后续任何新增表进入资产库后，使用方都可以直接获得该表的完整画像、当前缺口和治理动作建议。

### 15.2 查询方式

CLI：

```bash
python3 -m dlc_mcp.check_table ads_bill_company_1d_di --db /data/dlc-mcp/assets.db
```

MCP：

```text
get_table_readiness(table_name="ads_bill_company_1d_di")
```

Codex 可直接问：

```text
帮我看 ads_bill_company_1d_di 的资产画像完整度和治理缺口
```

### 15.3 报告内容

报告会输出：

- 验收状态：通过 / 部分通过 / 未通过。
- 完整度分数。
- 层级、领域、Owner。
- 核心等级、价值分层、置信度。
- 画像维度检查。
- 当前缺口。
- 治理动作建议。
- 核心/价值判断摘要。

画像维度包括：

| 维度 | 说明 |
| --- | --- |
| 基础信息 | layer/domain/owner/description 等 |
| 字段 | 是否同步字段 |
| 血缘 | 是否有上游或下游 |
| 质量规则 | 是否有质量监控规则 |
| 任务 | 是否有关联任务，展示任务名称、责任人、调度周期、调度时间、调度说明 |
| 运行实例 | 是否有最近运行实例，展示执行状态、开始结束时间、耗时、责任人 |
| 数据源 | 是否关联数据源 |
| 核心/价值判断 | 是否可解释判断价值分层和核心等级 |
| 人工标注 | 是否有人工作为治理补充信息 |

## 16. 表级产出状态

### 16.1 目标

把任务运行实例从“任务视角”提升到“表资产产出状态视角”，回答使用方最关心的问题：

```text
这张表今天产出了没有？成功了吗？谁负责？几点开始结束？耗时多久？
```

### 16.2 查询方式

MCP：

```text
get_table_production_status(table_name="ads_bill_company_1d_di", instance_date="2026-07-08")
```

`instance_date` 可选：

- 不传：返回最近一次产出实例。
- 传 `YYYY-MM-DD`：返回该日期的产出实例。

### 16.3 状态语义

报告会保留 WeData 原始实例状态，同时输出归一化状态：

| 归一化状态 | 含义 |
| --- | --- |
| `success` | 成功 |
| `failed` | 失败 |
| `running` | 执行中 |
| `not_run` | 未执行或无匹配实例 |
| `partial_success` | 多个产出任务中部分成功 |
| `unknown` | 未识别的 WeData 状态 |

### 16.4 输出内容

包括：

- 汇总状态。
- 产出任务数。
- 产出任务名称、责任人、调度时间。
- 最近实例原始状态和归一化状态。
- 开始时间、结束时间、耗时。
- 判断依据。
- 建议动作。
