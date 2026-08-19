# WeData 依赖重跑与飞书数据写入设计

## 1. 背景与目标

本项目当前通过 MCP 提供 WeData/DLC 资产查询、任务依赖查询和只读 SQL 查询能力。本设计增加两类受控写操作：

1. 根据目标表找到产出任务及全部上游依赖，按依赖层级从上游到目标任务逐层重跑；
2. 在任务重跑完成后查询目标表分区数据，并将表头和数据覆盖写入指定的飞书云文档、多维表格或电子表格。

两类远程副作用都必须显式确认：WeData 重跑需要一次确认，飞书覆盖写入需要独立的第二次确认。

本阶段只支持离线数据集成同步任务和 SQL/离线 ETL 任务。实时、Shell/脚本、工作流编排和无法识别的任务类型只进入计划，不自动执行。

## 2. 已确认的产品规则

### 2.1 分区与时间

- 服务端业务时区固定为 `Asia/Shanghai`，后续可配置化。
- 未指定分区时使用业务时区当天减 1 天。
- 用户显式指定分区时，以显式值为准。
- 执行计划和结果必须展示最终分区参数。
- 已存在的分区允许重跑；MCP 不自行删除分区，由 WeData 任务原有写入语义决定覆盖、更新或追加。
- 计划必须提示已有分区可能被覆盖。

### 2.2 任务发现与执行

- 表名映射必须有真实任务输入/输出证据，不得根据任务名推断表。
- 一个表对应多个产出任务时，先返回候选任务，要求用户选择，不自动选择。
- 递归获取完整上游任务并构建 DAG。
- 检测循环依赖、缺失依赖和无法解析的关系。
- 同一层级任务串行执行，使用稳定排序保证可复现。
- 某任务失败只阻断依赖该任务的下游分支；无关分支继续执行。
- 任务状态包括 `pending`、`submitted`、`running`、`success`、`failed`、`blocked`、`timeout`、`skipped_unsupported`。
- 目标任务成功后立即返回，不等待无关分支。
- 服务端默认最长等待 30 分钟，调用可指定超时时间。
- 第一版计划和执行上下文只保存在当前进程内存中，不持久化到 SQLite；服务重启后计划失效。

### 2.3 查询

- 默认生成 `SELECT *`，绑定最终分区条件。
- 支持用户指定分区、过滤条件或自定义只读 SQL。
- 自定义 SQL 只允许 `SELECT`/`WITH`，沿用现有 DLC SQL 安全校验。
- 无法识别分区字段时，不执行无条件全表查询，要求补充条件或明确授权。
- 查询结果包含列名、行数、列数及有限行预览。

### 2.4 飞书目标与覆盖

- 支持云文档 Docs、多维表格 Bitable、电子表格 Sheets。
- `target_type` 必须由用户明确指定为 `docs`、`bitable` 或 `sheets`；工具校验链接解析类型是否一致。
- 使用企业自建应用服务端凭证，`APP_ID`/`APP_SECRET` 只保留在服务端环境。
- 启动或首次使用时检查三类目标所需权限；权限不足时整体阻止写入，不做部分写入。
- 写入内容只包含表头和数据行，表头使用查询结果列名，不额外写入元信息。
- 每次写入先清理工具管理范围内全部旧数据，再写入最新表头和数据，避免旧行残留。
- 源表最新列结构覆盖目标列结构，支持新增、删除、重命名和列顺序变化。
- 目标不存在时不自动创建。
- 云文档首次写入必须指定已有原生表格块，只覆盖该表格块；不自动创建、不影响表格块外正文。
- 多维表格按源表名匹配既有数据表，缺少同名数据表时停止。
- 电子表格按源表名匹配既有工作表，缺少同名工作表时停止；默认从 `A1` 写入。
- 大结果集按目标类型处理：云文档使用较小行数限制，超限停止；Bitable/Sheets 使用分页和批量写入。

## 3. 总体架构

采用“统一编排工具 + 分层服务模块”方案，保持当前 MCP、Live Connector、Asset Store 的边界。

```text
MCP Tools
  prepare_table_refresh / confirm_table_refresh
  prepare_table_export / confirm_table_export
          |
Orchestration Services
  refresh planner / refresh executor / export planner / export executor
          |
Domain Services
  task resolver / dependency planner / query service / Feishu target service
          |
Live Connectors
  WeData trigger/status APIs / DLC SQL APIs / Feishu APIs
          |
In-memory operation store
  short-lived refresh plans, executions, export plans
```

### 3.1 MCP 工具层

新增四个对外工具：

```text
prepare_table_refresh(table_name, task_id?, partition?, filters?, sql?, timeout_seconds?)
confirm_table_refresh(plan_id)

prepare_table_export(table_name, feishu_url, target_type, partition?, filters?, sql?, document_block_id?, table_id?, sheet_name?, timeout_seconds?)
confirm_table_export(write_plan_id)
```

工具负责参数校验、状态转换、确认边界和用户可读结果，不实现供应商分页或原始 API 解析。

### 3.2 WeData 任务服务

`TableTaskResolver` 根据真实表输入/输出映射发现产出任务。

`TaskDependencyPlanner` 递归调用上游依赖接口，合并关系、去重、检测环路，生成 DAG 和层级。计划节点包含任务 ID、名称、项目、类型、输入输出证据、支持状态和预计影响。

`WeDataExecutionService` 只通过腾讯云官方任务触发 API 提交任务，轮询任务实例状态，并按拓扑层级串行推进。实现前必须验证当前 API 版本、账号权限、任务类型参数、分区参数和终态映射；验证失败时只允许生成计划。

### 3.3 DLC 查询服务

复用现有只读 DLC 查询能力。服务负责将表名、分区和过滤条件转换为安全 SQL，或校验用户自定义 SQL；负责提交、轮询、分页聚合和结果预览。查询结果使用结构化模型：列名、列类型（如可得）、行数据、行数、列数、分页信息。

### 3.4 飞书目标服务

`FeishuTargetService` 负责应用 Token、权限检查、URL 解析、目标类型校验和范围发现：

- Docs：验证文档可写，定位用户提供的已有表格块；
- Bitable：验证应用权限，按源表名定位既有数据表；
- Sheets：验证应用权限，按源表名定位既有工作表并计算工具管理区域。

`FeishuWriter` 按目标类型清理并重写表头及数据，使用批量 API，记录批次和结果，写入后执行可用的结果校验。

### 3.5 临时操作存储

第一版使用进程内存存储短期计划和执行上下文，至少保存：

- 唯一 ID、创建时间、过期时间；
- 目标表、任务、分区、SQL 摘要；
- DAG 节点和层级；
- 确认状态、执行状态和任务实例 ID；
- 飞书目标类型、资源标识、管理范围、查询摘要和写入预览。

需要明确返回 `plan_not_found`、`plan_expired`、`plan_already_executed`、`plan_context_mismatch`。未来多实例、跨会话或审计需求出现时，再将接口替换为 SQLite 或独立任务存储。

## 4. 关键流程

### 4.1 WeData 重跑计划

```text
prepare_table_refresh
  -> 解析表名
  -> 查找产出任务
  -> 多候选则 awaiting_task_selection
  -> 递归获取上游依赖
  -> 构建 DAG、检测环路和缺失关系
  -> 识别任务支持性
  -> 解析 Asia/Shanghai 分区
  -> 检查目标分区存在性并提示覆盖风险
  -> 生成 plan_id
  -> awaiting_confirmation
```

若存在不支持任务、循环依赖或关键依赖缺失，计划可返回但不可确认执行。

### 4.2 WeData 重跑执行

```text
confirm_table_refresh
  -> 校验临时计划
  -> 逐层、同层串行触发任务
  -> 轮询成功/失败/超时
  -> 失败任务阻断其下游，其他分支继续
  -> 目标任务成功即返回
```

结果中返回每个节点状态、实例 ID、开始/结束时间（如可得）、错误信息、阻塞原因、仍在运行的独立分支和目标任务结论。

### 4.3 飞书写入准备

```text
prepare_table_export
  -> 解析目标表
  -> 如未完成刷新，先生成 refresh plan
  -> refresh 确认并成功
  -> 构造/校验只读 SQL
  -> 查询目标分区
  -> 检查限制和预览
  -> 解析并校验飞书目标
  -> 检查应用权限和管理范围
  -> 生成 write_plan_id
  -> awaiting_write_confirmation
```

刷新确认和飞书写入确认必须分开。目标任务未成功时不得生成可执行写入计划。

### 4.4 飞书覆盖写入

```text
confirm_table_export
  -> 校验 write_plan_id 和目标快照
  -> 重新检查权限、目标类型和管理范围
  -> 清理工具管理范围内旧数据
  -> 写入列名
  -> 分页批量写入数据
  -> 校验写入结果
  -> 返回覆盖范围、旧数据量、新数据量和失败批次
```

重新检查用于防止 prepare 与 confirm 之间目标结构、权限或范围变化导致误写。

## 5. 状态与错误模型

计划状态：

```text
awaiting_task_selection
awaiting_confirmation
executing
success
partial_success
failed
blocked
expired
plan_not_found
plan_already_executed
```

写入计划状态：

```text
awaiting_write_confirmation
writing
success
partial_write
failed
expired
```

核心错误码：

```text
table_not_found
multiple_producer_tasks
task_type_unsupported
dependency_cycle
dependency_incomplete
partition_not_identified
wedata_trigger_not_supported
wedata_permission_denied
task_failed
task_timeout
task_blocked
feishu_permission_denied
feishu_target_not_found
feishu_target_type_mismatch
feishu_managed_range_missing
feishu_schema_changed
feishu_partial_write
```

错误响应必须包含可操作的原因、影响范围、已完成动作和下一步建议，不泄露 AK/SK、App Secret、内部文件路径或原始敏感配置。

## 6. 安全与权限

- WeData 触发仅使用官方 API；不使用 SSH、Shell、控制台模拟或客户端直连凭证。
- Tencent Cloud AK/SK 和飞书 App Secret 只存放服务端环境。
- 新增腾讯云 API 时同步更新 `TENCENT_CLOUD_API_CATALOG`。
- MCP 工具的写操作应标记为非只读，并由 MCP Host 决定是否额外提示；业务逻辑仍强制两阶段确认。
- 飞书写入采用应用身份，权限检查失败时不开始清理或写入。
- prepare 阶段只读取和生成计划；confirm 阶段才允许远程副作用。
- confirm 阶段重新校验计划、目标类型、资源标识和管理范围。

## 7. 大数据量和一致性

- 云文档设置较小结果行数上限，超过时返回超限，不执行写入。
- Bitable/Sheets 使用分页查询和批量写入，限制批次大小和请求频率。
- 写入前先清理管理范围，因此批量写入中途失败可能导致范围内部分为空；实现必须返回明确的 `partial_write` 状态、已清理范围、已成功批次和失败批次。
- 第一版不承诺跨 API 的事务回滚；后续可增加临时区域、双写校验或快照恢复能力。
- 目标范围外内容必须保持不变。

## 8. 测试设计

### 8.1 WeData

- 表到任务映射只接受真实输入/输出证据；
- 多产出任务返回候选，不自动选择；
- DAG 多层拓扑排序和稳定顺序；
- 循环依赖和缺失依赖；
- 默认 Asia/Shanghai 当天减一与显式分区；
- 已存在分区提示；
- 支持/不支持任务类型识别；
- 同层串行执行；
- 失败分支隔离和下游阻塞；
- 目标任务成功即返回；
- 超时、计划过期、重复确认和服务进程内存丢失。

### 8.2 DLC 查询

- 默认 `SELECT *` 及分区条件；
- 过滤条件组合；
- 只读 SQL 校验，拒绝 DDL/DML/多语句；
- 分区字段缺失时拒绝无条件全表查询；
- 分页结果聚合和列名保留。

### 8.3 飞书

- Docs/Bitable/Sheets 链接和类型校验；
- 权限不足时阻止写入；
- Docs 指定已有表格块；
- Bitable 按源表名查找数据表；
- Sheets 按源表名查找工作表并从 A1 管理；
- 目标不存在不自动创建；
- 行数减少时清理旧行；
- 列新增、删除、重命名和顺序变化；
- 分页批量写入、部分失败和结果校验；
- prepare 与 confirm 之间范围变化。

### 8.4 MCP 契约与集成

- 新工具 schema、必填参数和错误响应；
- 两阶段确认无法跳过；
- 刷新成功后才能准备导出；
- README 工具清单、架构文档、服务端环境变量和权限说明同步更新；
- API 能力验证在真实凭证环境执行，单元测试使用 mock，不在测试中保存真实凭证。

## 9. 实施阶段

### 阶段 0：能力验证

验证腾讯云官方触发 API、账号权限、两类任务参数、分区传递和终态；验证飞书自建应用 Token、Docs/Bitable/Sheets 权限和写入限制。产出 API 能力报告与权限清单。若验证失败，只实现计划能力和清晰的不可执行错误。

### 阶段 1：依赖计划

实现任务发现、候选选择、上游递归、DAG/环路检测、任务类型判定、默认分区和 `prepare_table_refresh`。

### 阶段 2：任务执行

实现官方 API 适配器、状态轮询、同层串行、分支失败隔离、超时和 `confirm_table_refresh`。

### 阶段 3：查询编排

实现默认/自定义只读 SQL、分区绑定、DLC 分页、行列统计和写入预览。

### 阶段 4：飞书目标服务

实现凭证配置、Token、权限检查、URL 解析、Docs 表格块、Bitable 数据表、Sheets 工作表发现和管理范围。

### 阶段 5：飞书写入

实现三类目标覆盖、列结构更新、分页批量写入、写入预览、`prepare_table_export` 和 `confirm_table_export`。

### 阶段 6：验证和文档

完成单元、集成和 MCP 契约测试，更新 README、架构、部署环境和权限文档，补充真实环境 smoke test 指引。

## 10. 非目标与后续演进

本阶段不包含：

- 实时、Shell、工作流编排等任务自动重跑；
- 自动创建飞书文档表格块、数据表或工作表；
- SQLite 持久化执行计划和跨会话确认；
- WeData 任务自动重试策略；
- 跨 API 原子事务和自动回滚；
- 将元信息混入飞书数据区域；
- 无用户确认的远程写操作。

后续可演进为持久化异步执行、并发度配置、任务重试、写入快照/回滚、OAuth 身份和更多飞书目标类型。
