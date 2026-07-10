# 百应数据资产知识库与质量监控 Agent：项目现状与下一步建议

> 依据：`/Users/leve/Desktop/百应数据资产知识库与质量监控Agent_OKR时间线.xlsx`、当前 DLC-MCP 项目代码与文档、以及服务端已完成真实 WeData 数据拉取这一现状。  
> 日期：2026-07-10

## 1. OKR 目标拆解

目标文档把项目拆成两个主目标：

1. **O1：百应数据资产知识库构建**
   - 完成 WeData/DLC 核心资产采集。
   - 建立可查询、可解释、可持续更新的数据资产知识库。
   - 覆盖表、任务、数据源、字段、血缘、质量规则、运行实例。
   - 支持表资产画像、核心表判断、价值分层、BI 指标口径模板。

2. **O2：数据质量监控 Agent**
   - 覆盖 ods/dim/dwd/dws/ads 各层级。
   - 支持质量规则、运行实例、产出时效、运行状态查询。
   - 能解释缺规则、任务失败、延迟、下游影响等质量风险。
   - 输出团队分工与处理动作。

8 周时间线中，当前最接近的是第 1~2 周交付阶段：

| 周次 | 时间 | 目标 | 当前判断 |
| --- | --- | --- | --- |
| 第 1 周 | 2026-07-06 ~ 2026-07-10 | 稳定资产采集底座 | 已基本完成，服务端已拉到真实数据；仍需治理数据缺口 |
| 第 2 周 | 2026-07-13 ~ 2026-07-17 | 补全资产画像 | 能力已具备，下一步要用真实数据补齐画像完整度 |
| 第 3 周 | 2026-07-20 ~ 2026-07-24 | 核心资产判断模型 V1 | 初版模型已实现，需结合真实数据与专家标注校准 |
| 第 4 周 | 2026-07-27 ~ 2026-07-31 | 数据资产知识库 V1 | MCP 工具已较完整，需补文档、验收问题集和真实样例 |
| 第 5 周 | 2026-08-03 ~ 2026-08-07 | 质量监控 Agent V1 | 质量/运行状态工具已有基础，需提升规则覆盖与 SLA 画像 |
| 第 6 周 | 2026-08-10 ~ 2026-08-14 | 风险解释与下游影响 | 已有生产风险、变更影响雏形，需基于核心表场景强化解释 |
| 第 7 周 | 2026-08-17 ~ 2026-08-21 | BI 指标口径梳理 V1 | 已有指标定义工具雏形，模板与样例仍需沉淀 |
| 第 8 周 | 2026-08-24 ~ 2026-08-28 | 团队落地与验收 | 尚未系统开展 |

## 2. 当前已完成能力

### 2.1 接入与服务层

已完成：

- **MCP Server 框架**
  - 支持 `initialize`、`tools/list`、`tools/call`。
  - 所有工具统一在 `dlc_mcp/mcp.py` 声明。
  - 返回结构化 Markdown，适合 Codex/Agent 直接展示。

- **HTTP Gateway**
  - 支持 `/health` 和 `/mcp`。
  - 支持 Bearer token / `x-dlc-mcp-token` 鉴权。
  - 腾讯云 AK/SK 留在服务端，普通用户只需要 Gateway URL 和 token。

- **npm 用户接入**
  - npm 包：`@levisli/dlc-mcp`。
  - `install-codex` 可自动写入 Codex MCP 配置。
  - README 已给出普通用户接入命令和示例问题。

判断：**接入层已经达到第 1 周“工具清单确认 + 可被 Codex 使用”的要求。**

---

### 2.2 WeData/DLC 数据采集层

已完成同步能力：

| 对象 | 当前能力 | OKR 对应 |
| --- | --- | --- |
| WeData 任务 | `ListTasks` 分页同步 | O1/KR1、O2/KR2 |
| 表目录 | `ListTable` 同步 | O1/KR1、O1/KR3 |
| 字段 | `GetTableColumns` 同步 | O1/KR1、O1/KR3 |
| 血缘 | `ListLineage` 同步 | O1/KR1、O1/KR3、O2/KR4 |
| 质量规则 | `ListQualityRules` 同步 | O1/KR1、O2/KR1 |
| 数据源 | `ListDataSources` 同步 | O1/KR1、O1/KR3 |
| 数据源关联任务 | `GetDataSourceRelatedTasks` 同步 | O1/KR1、影响分析 |
| 运行实例 | `ListTaskInstances` 同步 | O1/KR1、O2/KR2 |
| 分区事实 | 有表结构与解析能力；WeData `2025-08-06` 下 `ListTablePartitions` 返回 `InvalidAction` | 产出时效补充数据，当前受接口版本限制 |

其他已完成：

- 增量同步脚本：`deploy/sync-wedata-incremental.sh`。
- 全量/批量补数脚本：`deploy/sync-wedata-full.sh`。
- 原始 raw JSON dump 持久化到 `/data/dlc-mcp/sync`，便于追溯。
- 服务端标准环境变量沉淀在 `deploy/env.example` 和相关文档中。
- 已修正任务名误造表的问题，当前缺任务/运行实例的表应按真实映射缺口处理。

判断：**采集链路已经跑通，并且服务端已经拉到真实数据；接下来重点从“能拉到”转为“拉得全、映射准、缺口可解释”。**

---

### 2.3 SQLite 资产事实库

当前 `AssetStore` 已有核心事实模型：

- 表资产：`tables`
- 字段：`columns`
- 血缘：`lineage`
- 质量规则：`quality_rules`
- 任务：`tasks`
- 任务输入/输出表：`task_tables`
- 任务运行实例：`task_runs`
- 数据源：`data_sources`
- 数据源关联任务：`data_source_tasks`
- 分区：`table_partitions`
- 专家标签：`expert_labels`

这些模型已经覆盖 OKR 第 1 周和第 2 周所需的数据底座。

判断：**底层事实表结构已经基本完整，后续主要是补齐真实数据覆盖率和治理口径。**

---

### 2.4 资产查询与画像能力

当前 README 暴露的 MCP 工具已经比较完整，按能力可归类为：

#### 资产检索与基础画像

- `search_assets(query)`
- `list_metadata()`
- `get_table_profile(table_name, live)`
- `list_table_columns(table_name, live)`
- `get_table_lineage(table_name, live)`
- `get_table_tasks(table_name)`

覆盖 OKR：

- O1/KR3：资产画像包含名称、负责人、层级、数据源、字段、上下游、任务、质量、运行状态。
- O1/KR6：支持自然语言问表、字段、质量监控、上下游。

当前判断：**表资产画像能力已实现，下一步要基于服务端真实数据提高画像完整率。**

#### 数据源画像

- `list_data_sources(query, live)`
- `get_data_source(data_source_id, live)`
- `list_data_source_tasks(data_source_id, live)`

覆盖 OKR：

- O1/KR1：数据源采集。
- O1/KR3：资产画像中的数据源维度。

当前判断：**数据源维度已经具备基础查询能力，可用于来源治理和影响分析。**

#### 质量与生产状态

- `get_quality_status(table_name, live)`
- `list_quality_gaps(layer, domain, limit)`
- `get_task_runs(task_id/task_name, instance_date, live)`
- `get_table_production_status(table_name, instance_date, live)`
- `get_table_production_risk_detail(table_name, instance_date, live)`
- `list_table_production_risks(layer, core_level, instance_date, status, limit)`

覆盖 OKR：

- O2/KR1：质量规则查询。
- O2/KR2：任务运行实例查询。
- O2/KR3：按表/任务/数据源聚合质量与产出状态。
- O2/KR4：风险解释。

当前判断：**质量监控 Agent 的底层工具已经具备雏形，但质量规则覆盖和 SLA/时效规则还需要增强。**

#### 核心资产与价值分层

- `is_core_table(table_name)`
- `get_asset_value_profile(table_name, live)`
- `get_expert_label(asset_type, asset_name)`
- `list_expert_review_queue(layer, limit)`

已实现模型：

- `expert label > model score > raw metadata` 优先级。
- 分数维度包括业务价值、血缘影响、层级位置、治理成熟度、运行稳定性。
- 输出 `value_tier`、`core_level`、`is_core`、score、原因。

覆盖 OKR：

- O1/KR2：资产分层模型。
- O1/KR4：资产价值分层初版。

当前判断：**核心资产模型 V0/V1 雏形已完成，下一步是用真实服务端数据和专家标注校准。**

#### 治理与风险画像

- `get_table_readiness(table_name, live)`
- `get_table_risk_profile(table_name, live)`
- `get_asset_owner_profile(table_name, live)`
- `get_asset_usage_profile(table_name, live)`
- `get_asset_lifecycle_profile(table_name, live)`
- `get_asset_change_impact(table_name, change_type, live)`
- `get_asset_governance_issue_inventory(layer, core_level, issue_type, limit)`
- `get_asset_governance_daily_report(instance_date, layer, core_level)`

覆盖 OKR：

- O2/KR3：聚合质量与产出时效状态。
- O2/KR4：风险解释。
- O2/KR5：问题对象与责任归属。

新增能力：

- `get_asset_governance_issue_inventory` 会从 SQLite 事实库确定性产出治理问题清单，覆盖 unknown 层、缺质量规则、缺任务映射、缺运行实例、缺数据源、缺 Owner、分区能力不可用、画像不完整等 issue 类型。
- 每个 issue 都包含 `evidence`、`severity`、`suspected_root_cause`、`recommended_next_check`，并把未知责任人统一归到 `unknown owner`，避免由 LLM 猜测事实或 Owner。
- `get_asset_governance_daily_report` 已接入 issue inventory，并新增按 issue type、severity、owner 的汇总、Top governance issues、责任方 buckets，可直接作为每日治理分工入口。

当前判断：**治理工具已经超出第 1~2 周基础要求，具备进入“巡检日报/风险解释/责任分工”的基础。**

#### BI 指标口径

- `get_metric_definition(table_name, live)`

覆盖 OKR：

- O1/KR5：BI 核心指标口径模板。

当前判断：**已有工具入口，但仍需要财务分析、业务分析两个领域的模板与样例沉淀。**

---

### 2.5 健康检查、覆盖率与缺口诊断

已完成：

- `get_sync_health()`：同步健康、资产数量、最新同步信号、当前数据缺口。
- `get_asset_coverage()`：按层级统计字段、质量规则、血缘、任务、数据源覆盖率。
- `list_asset_coverage_gaps(gap_type, layer, limit)`：列出缺字段、缺血缘、缺质量规则、缺任务、缺运行实例、缺数据源等表。
- `get_asset_governance_issue_inventory(layer, core_level, issue_type, limit)`：按治理 issue 类型输出确定性问题清单、证据、严重级别、疑似根因和下一步检查建议。
- `get_asset_governance_daily_report(instance_date, layer, core_level)`：在巡检日报中汇总治理 issue 数量、严重级别、Owner 和责任方 buckets。
- `python3 -m dlc_mcp.check_foundation`：服务端/本地可读 Markdown 检查报告。
- `python3 -m dlc_mcp.diagnose_asset_gaps`：针对服务端巡检缺口做只读诊断。
- `python3 -m dlc_mcp.validate_core_assets --db ... --limit 20 --output ...`：生成核心候选资产端到端验收 Markdown，逐表串联画像完整度、核心判断、质量状态、生产状态、风险解释、当前缺口和建议动作。
- `.claude/skills/data-asset-governance/SKILL.md`：提供面向 Agent 的数据资产治理分析流程，要求先取 deterministic issue evidence，再输出治理方案，禁止编造 issue facts、Owner 或把 absent data 当健康。

最新诊断重点已覆盖：

- 质量规则只有 **62**：明确来自最新服务端资产库巡检，不是本地 demo 数据。
- unknown 层表还有 **2141**：明确来自最新服务端资产库巡检。
- 分区接口：WeData `2025-08-06` 下 `ListTablePartitions` 返回 `InvalidAction`，应判断为 **action 名/版本不支持**，不是参数错误。
- 部分真实表缺任务/运行实例：已不再归因于误造表，而是进入任务表映射、运行窗口、分页、task_id 对齐等真实缺口排查。

当前判断：**项目已经具备“数据拉取后怎么判断是否可信”的主控台能力；新增 issue inventory 和 core validation report 后，缺口不仅能被列出，还能按严重级别、根因、Owner 和责任方被拆解成治理动作。**

---

## 3. 当前与 OKR 的差距

### 3.1 O1：数据资产知识库构建

| KR | 要求 | 当前状态 | 差距 |
| --- | --- | --- | --- |
| KR1 核心资产采集 | 表、任务、数据源、字段、血缘、质量规则、运行实例 | 已具备同步与入库能力，服务端已拉到真实数据 | 质量规则少、unknown 层多、部分表缺任务/运行实例 |
| KR2 资产分层模型 | 覆盖 ods/dim/dwd/dws/ads，标记核心资产候选 | 已有层级、核心表、价值分层模型 | unknown 层 2141 需要治理；专家标注需补齐 |
| KR3 完整资产画像 | 名称、负责人、层级、数据源、字段、上下游、任务、质量、运行状态 | `get_table_profile` 已实现 | 画像完整率依赖真实数据覆盖，需按缺口补数 |
| KR4 价值分层初版 | 基于层级、血缘、质量、运行、人工标记 | 已实现可解释评分 | 需要真实数据校准权重和阈值 |
| KR5 BI 指标口径 | 财务/业务分析模板 | 有 `get_metric_definition` 入口 | 模板、样例、核心指标清单不足 |
| KR6 MCP/Agent 查询体验 | 自然语言查表/字段/质量/上下游 | MCP 工具完整，npm/Gateway 可用 | 需要验收问题集和真实案例回归 |

### 3.2 O2：数据质量监控 Agent

| KR | 要求 | 当前状态 | 差距 |
| --- | --- | --- | --- |
| KR1 质量规则查询 | 各层级表质量规则数、明细、状态 | `get_quality_status`、`list_quality_gaps`、`get_asset_governance_issue_inventory(issue_type="missing_quality_rules")` 已有 | 质量规则总量 62，覆盖率低；需要字段级覆盖度 |
| KR2 任务运行实例查询 | 查询今天/昨天任务运行情况 | `get_task_runs`、表生产状态、`missing_task_mapping` / `missing_task_runs` issue 清单已实现 | 部分真实表缺运行实例，需要扩大/校准同步窗口 |
| KR3 聚合质量与产出状态 | 按表/任务/数据源聚合风险 | 生产风险、巡检日报、issue summary / severity / owner 汇总已有 | 需要数据源维度风险聚合和 SLA 规则 |
| KR4 风险解释 | 缺规则、失败、延迟、下游影响 | 已有风险画像、生产风险详情、issue suspected root cause 与 recommended next check | 需要更强的核心表影响解释和可执行处理建议 |
| KR5 团队拆解清单 | 平台/数仓/BI/业务 Owner 分工 | Owner/profile 工具、issue responsibility buckets、`data-asset-governance` skill 已有基础 | 需要落地责任矩阵和处理流程 |

## 4. 当前最重要的数据问题

服务端已经拉到真实数据后，当前不应该继续只做工具堆叠，而应优先提升数据可信度。

### 4.1 质量规则覆盖不足

已知：最新服务端巡检中质量规则为 **62**。

判断：

- 对于真实 WeData 表规模，这个数量偏少。
- 需要区分：
  - WeData 源头确实规则少；
  - 同步范围太小；
  - `ListQualityRules` 过滤条件不完整；
  - raw 有规则但解析/表名匹配丢失。

建议：

1. 先用 `diagnose_asset_gaps` 判断 raw 与 DB 是否一致。
2. 对核心候选表输出无质量规则清单。
3. 增加字段级质量覆盖：从“有没有规则”升级到“关键字段是否有规则”。

---

### 4.2 unknown 层表过多

已知：最新服务端巡检中 unknown 层表为 **2141**。

判断：

- 这是核心资产分层和价值判断的最大阻塞之一。
- 如果 raw `ListTable` 中有库名、目录、路径、数据源、表名前缀，则多数可以通过规则修复。
- 如果 raw 本身缺少层级/库信息，则需要补接口或人工规则映射。

建议：

1. 抽样 unknown 表 raw 字段。
2. 建立层级推断优先级：显式字段 > 库名/路径 > 表名前缀 > 人工映射。
3. 将 unknown 表分成：可自动修复、需接口补充、需人工确认三类。

---

### 4.3 分区接口受版本限制

已知：WeData `2025-08-06` 下 `ListTablePartitions` 返回 `InvalidAction`。

判断：

- 这不是参数错误。
- 当前版本/action 不支持该接口。
- 不应继续在 `ProjectId/TableName/TableGuid/DatabaseName/DataSourceId` 参数组合上反复尝试。

建议：

1. 在报告中明确标注：分区接口当前不可用，原因是 action 名/版本不支持。
2. 暂停把分区数据作为近期 P0 验收项。
3. 如确实需要分区事实，改走替代来源：DLC 元数据接口、SQL `SHOW PARTITIONS`、表存储元数据或其他腾讯云可用 action。
4. 在找到替代接口前，产出时效优先使用任务运行实例判断。

---

### 4.4 部分真实表缺任务/运行实例

判断：

- 这已经不是“任务名误造表”问题。
- 现在应按真实表缺映射/缺实例处理。

可能原因：

- 任务输入输出字段解析不足。
- SQL 中表名解析不足。
- `db.table` 与 `table` 表名规范化不一致。
- `ListTaskInstances` 时间窗口太短。
- `WEDATA_INSTANCE_MAX_PAGES` 截断。
- task_id 与实例中的 id 对齐存在差异。

建议：

1. 对缺任务表抽样 20 张，回查 raw task 是否包含这些表名。
2. 对有任务但无运行实例的表，扩大 7 天窗口验证。
3. 输出“缺任务映射”和“缺运行实例”两张清单，分别推动修解析和调同步范围。

## 5. 下一步建议

### P0：先把真实数据底座治理到可信

目标：把第 1 周“采集底座稳定”从“能拉到数据”升级到“数据可信、缺口可解释”。

建议执行：

1. 在服务端跑诊断：

```bash
cd /opt/dlc-mcp/DLC-MCP
python3 -m dlc_mcp.diagnose_asset_gaps \
  --db /data/dlc-mcp/assets.db \
  --sync-dir /data/dlc-mcp/sync \
  --report-source "latest service asset inspection" \
  --quality-rule-count 62 \
  --unknown-layer-count 2141 \
  --sample-limit 50
```

2. 固定每日资产底座检查：

```bash
bash deploy/check-asset-foundation.sh /etc/dlc-mcp/env
```

3. 用 issue inventory 固定输出确定性治理清单：

```bash
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"get_asset_governance_issue_inventory","arguments":{"limit":100}}}' \
  | DLC_MCP_DB=/data/dlc-mcp/assets.db python3 -m dlc_mcp.server
```

重点按 `issue_type` 拆分：

- `unknown_layer`：层级未知。
- `missing_quality_rules`：缺质量规则。
- `missing_task_mapping`：缺任务映射。
- `missing_task_runs`：有任务但缺运行实例。
- `missing_data_source`：缺数据源关联。
- `missing_owner`：缺责任人。
- `partition_unsupported`：分区事实受 action/version 限制。
- `profile_incomplete`：画像不完整。

4. 输出四张治理清单：
   - unknown 层表清单。
   - 无质量规则核心/高影响表清单。
   - 缺任务映射表清单。
   - 有任务但缺运行实例表清单。

5. 对每类缺口标注根因：
   - 同步范围问题。
   - API/action/版本问题。
   - 解析映射问题。
   - WeData 源头治理缺失。
   - 需要 Owner 人工确认。

验收标准：

- unknown 层表从 2141 按原因拆分完成。
- 质量规则 62 的来源判断清楚：源头少、同步少、还是解析丢。
- 分区明确不再作为参数问题阻塞。
- 真实表缺任务/运行实例能分清缺映射还是缺实例。
- 每类缺口都能在 issue inventory 中看到 evidence、severity、suspected root cause、recommended next check 和 owner / `unknown owner`。
- 巡检日报能输出 issue summary、Top governance issues 和 responsibility buckets，作为每日治理分工入口。

---

### P1：补全第 2 周资产画像

目标：让任意核心表能返回完整画像。

建议执行：

1. 对核心候选表优先补齐：字段、任务、血缘、质量规则、运行实例、数据源。
2. 用 `get_table_profile` 做 20 个真实核心表样例验收。
3. 用 `python3 -m dlc_mcp.validate_core_assets --db /data/dlc-mcp/assets.db --limit 20 --output ...` 生成核心候选资产端到端验收报告。
4. 将表画像分为：
   - 基础信息：名称、层级、库、Owner、描述。
   - 结构信息：字段、分区可用性。
   - 生产链路：任务、输入输出、运行实例。
   - 治理信息：质量规则、Owner、生命周期、issue inventory 当前缺口。
   - 价值信息：核心等级、价值分层、下游影响。

验收标准：

- 20 个核心表样例中，大部分能返回完整画像。
- 每个画像能明确列出缺口，而不是静默为空。
- 核心候选资产验收报告逐表包含画像完整度、核心判断、质量状态、生产状态、风险解释、当前缺口和建议动作。

---

### P2：核心资产判断模型 V1 校准

目标：把当前可解释评分模型变成可验收的核心资产模型。

建议执行：

1. 导入/补齐专家标签。
2. 使用真实数据校准当前评分维度：
   - 层级。
   - 下游血缘。
   - 任务依赖。
   - 质量规则。
   - 运行稳定性。
   - 业务关键词。
3. 输出核心候选 Review Queue。
4. 明确 P0/P1/P2/非核心 与 L0~L4 的对应关系。

验收标准：

- `is_core_table` 能解释核心判断原因。
- `get_asset_value_profile` 能给出分数、证据和缺口。
- 高分但缺人工标注的表能进入 review queue。

---

### P3：质量监控 Agent V1

目标：从“能查规则/实例”升级到“能解释质量和产出风险”。

建议执行：

1. 增加质量规则覆盖度能力：
   - 表级：有没有规则。
   - 字段级：关键字段有没有规则。
   - 状态级：最近一次质量状态。
2. 增加 SLA/时效画像：
   - 产出任务是否按时。
   - 最近实例是否成功。
   - 今日/昨日是否缺跑。
3. 强化风险解释：
   - 缺质量规则。
   - 任务失败。
   - 任务延迟。
   - 核心表下游影响。
4. 用 `get_asset_governance_daily_report` 做每日巡检入口。
   - 日报包含 `issue_summary_by_type`、`issue_summary_by_severity`、`issue_summary_by_owner`、`top_governance_issues` 和 `responsibility_buckets`。
   - 质量、任务、Owner、数据源等缺口优先从 deterministic issue inventory 取证，不由 LLM 猜测。
5. 使用 `data-asset-governance` skill 将 issue evidence 转为治理方案：
   - P0/P1/P2 分级。
   - 按数据平台、数仓 Owner、BI Owner、业务 Owner、unknown owner 拆分责任。
   - 每个建议动作必须引用 issue evidence。

验收标准：

- 能回答“今天哪些核心表有风险”。
- 能说明“为什么有风险”。
- 能给出“应该找谁处理”。
- 输出治理方案时，每条建议都能追溯到 issue evidence；不能把缺数据当健康，也不能编造 Owner。

---

### P4：BI 指标口径模板

目标：对齐第 7 周 BI 指标口径梳理。

建议执行：

1. 先覆盖两个领域：财务分析、业务分析。
2. 建立指标模板：
   - 指标名称。
   - 业务定义。
   - 计算口径。
   - 依赖表。
   - 依赖字段。
   - Owner。
   - 使用场景。
   - 质量规则要求。
3. 将 `get_metric_definition` 输出与模板对齐。

验收标准：

- 每个核心指标能追溯到表、字段、Owner、口径。
- 至少沉淀 5~10 个真实指标样例。

---

### P5：团队落地与验收

目标：把工具变成可持续使用的团队流程。

建议执行：

1. 建立验收问题集，例如：
   - `ads_bill_company_1d_di 是不是核心表？为什么？`
   - `某表有没有质量规则？缺哪些关键字段监控？`
   - `昨天哪些核心表任务失败或没跑？`
   - `某数据源影响哪些任务和表？`
   - `某表变更会影响哪些下游？`
2. 建立责任矩阵：
   - 数据平台：同步链路、接口权限、运行稳定。
   - 数仓：表 Owner、血缘、任务映射、质量规则配置。
   - BI：指标口径、报表依赖、使用场景。
   - 业务 Owner：核心等级确认、治理优先级。
3. 完善使用手册和常见问题。

验收标准：

- 每类问题都有 Owner 和处理动作。
- Agent 回答可被真实业务问题验证。

## 6. 建议近期执行顺序

我建议接下来按这个顺序推进：

1. **先做数据缺口诊断日报**
   - 固定输出质量规则 62、unknown 2141、分区 InvalidAction、缺任务/运行实例的根因分类。

2. **修 unknown 层和表名规范化**
   - 这是核心资产模型和资产画像最基础的维度。

3. **补质量规则覆盖判断**
   - 先区分是源头没有规则，还是同步/解析没有拿全。

4. **补任务/运行实例覆盖**
   - 对真实表按缺映射、缺实例、窗口不足分类治理。

5. **挑 20 张核心候选表做端到端验收**
   - 每张表跑：画像、核心判断、质量状态、生产状态、风险解释、当前治理缺口。
   - 使用 `python3 -m dlc_mcp.validate_core_assets --db /data/dlc-mcp/assets.db --limit 20 --output ...` 固化验收报告。

6. **用 issue inventory 驱动每日治理方案**
   - 每日从 `get_asset_governance_issue_inventory` 和 `get_asset_governance_daily_report` 取证。
   - 用 `data-asset-governance` skill 输出 `# 数据资产治理方案`，按 P0/P1/P2 和责任方拆解。

7. **进入核心资产模型校准和质量监控 Agent V1**
   - 在数据可信后，再增强解释和 Agent 体验。

## 7. 总体结论

当前项目已经完成了从 0 到 1 的关键底座：

- MCP/Gateway/npm 接入已完成。
- WeData 真实数据采集链路已跑通。
- SQLite 资产事实库模型已覆盖 OKR P0 对象。
- 表画像、质量、任务、运行实例、数据源、核心判断、风险解释等 MCP 工具已经形成体系。
- 新增 deterministic governance issue inventory，可把 unknown 层、缺规则、缺任务映射、缺运行实例、缺数据源、缺 Owner、分区不可用、画像不完整等问题按证据、严重级别、根因和下一步检查输出。
- 巡检日报已从风险列表升级为可分工的治理日报，包含 issue summary、Top issues、Owner 汇总和责任方 buckets。
- 新增核心候选资产端到端验收报告 CLI，可用于 20 张核心候选表的画像/质量/生产/风险/缺口抽检。
- 新增 `data-asset-governance` skill，可将确定性 issue evidence 转成治理方案，并约束 Agent 不编造事实或责任人。
- 服务端已经拉到真实数据，项目进入“真实数据治理与验收”阶段。

下一步不建议继续优先新增大量工具，而应优先完成：

1. **真实数据缺口治理**；
2. **基于 issue inventory 的每日治理分工**；
3. **核心表样例端到端验收**；
4. **核心资产模型校准**；
5. **质量监控 Agent 的风险解释闭环**。

这样才能从“工具可用”推进到 OKR 要求的“资产知识库可信、质量监控可解释、团队可以落地使用”。
