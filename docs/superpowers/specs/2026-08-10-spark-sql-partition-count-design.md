# Spark SQL 分区行数查询设计

- 日期：2026-08-10
- 状态：已确认设计，待实施计划

## 1. 背景与目标

项目当前通过 MCP 工具访问腾讯云 WeData 的元数据、任务、分区、血缘和治理信息，但没有面向自然语言的 Spark SQL 数据查询能力。本设计增加第一阶段最小闭环：用户指定默认 WeData 项目中的表和完整分区条件后，系统异步提交一个受限的 Spark SQL `COUNT(*)` 查询，并在查询完成后返回行数。

目标是提供可核验、可审计、可限流的只读查询能力，同时保证不修改生产任务、不执行全表扫描、不把任意 SQL 直接提交到 Spark，并尽量不影响整体集群任务执行。

## 2. 范围与非目标

### 2.1 第一阶段范围

- 单一默认 WeData 项目/数据源。
- 只支持分区表的精确分区行数查询。
- 所有查询必须显式指定完整分区条件。
- 由服务端从结构化参数生成固定模板 Spark SQL。
- 通过 WeData 专用一次性查询任务或专用任务模板异步执行。
- 提供两个 MCP 工具：提交查询、查询结果。
- 使用本地 SQLite 短期保存查询状态、任务关联和结果。
- 支持幂等去重、并发/频率限制、任务超时、结果 TTL 和审计字段。

### 2.2 非目标

- 不支持用户提交任意 Spark SQL。
- 不支持 `INSERT`、`UPDATE`、`DELETE`、`DROP`、`ALTER` 或其他 DDL/DML。
- 不支持全表扫描、跨分区范围、`IN`、通配符或多分区查询。
- 不支持多数据源自动匹配。
- 不建设完整的长期查询历史或通用分析平台。

## 3. 选定架构

采用独立查询模块与专用 WeData 资源治理相结合的方案：

```text
自然语言请求
    │
    ▼
MCP 工具层
    │  submit_partition_count_query(table, partition)
    │  get_partition_count_query(query_id)
    ▼
QueryService
    ├─ 校验表名和默认项目
    ├─ 查询元数据并确认分区字段
    ├─ 校验完整分区条件
    ├─ 生成并校验固定 SQL
    ├─ 检查幂等、并发和频率限制
    ├─ 创建 WeData 一次性查询任务
    └─ 查询任务状态并解析结果
       │
       ├──────────────► QueryStore（SQLite 短期状态）
       │
       └──────────────► WeData 专用查询资源组
                          固定队列、低优先级、固定资源上限
```

建议增加以下边界：

- `dlc_mcp/query_models.py`：查询请求、状态、结果、错误数据结构。
- `dlc_mcp/query_validation.py`：表名、分区和固定 SQL 的校验与生成。
- `dlc_mcp/query_service.py`：元数据校验、任务提交、状态同步和结果解析。
- `dlc_mcp/query_store.py`：SQLite 查询状态、幂等记录和 TTL 清理。
- `dlc_mcp/mcp.py`：仅注册 MCP 工具、调用服务并格式化结果。
- WeData 客户端扩展：封装专用查询任务创建、状态读取和结果获取；不将生产任务作为查询任务使用。

## 4. 数据流

### 4.1 提交流程

`submit_partition_count_query` 只接受结构化参数：

```json
{
  "table_name": "dws_order_detail",
  "partition": {"ds": "2026-08-10"}
}
```

服务端步骤：

1. 规范化表名，拒绝 SQL 片段、注释、分号和多语句。
2. 从默认 WeData 项目查询表元数据。
3. 确认表存在、可查询且拥有分区字段。
4. 要求提供全部分区字段；缺少任意字段都返回 `PARTITION_REQUIRED`。
5. 校验分区值的长度、字符集和格式；不允许范围、表达式或通配符。
6. 根据已验证的表标识、分区字段和值生成固定 SQL。
7. 对生成 SQL 做结构二次校验，确保是单表单分区 `COUNT(*)`。
8. 检查幂等键、调用方并发、全局并发和重复提交间隔。
9. 使用专用资源组/队列/低优先级配置创建 WeData 一次性查询任务。
10. 写入 `query_jobs`，返回 `query_id` 和 WeData task ID；不在 MCP 请求中等待 Spark 完成。

SQL 逻辑固定为：

```sql
SELECT COUNT(*) AS row_count
FROM `validated_table`
WHERE `validated_partition_column` = 'validated_partition_value'
```

实现应优先使用 WeData/Spark 支持的参数绑定或安全转义；不能把未经验证的用户字符串直接拼接到 SQL 中。

### 4.2 状态查询流程

`get_partition_count_query(query_id)` 只读取调用方可见记录，并以 WeData 任务状态作为执行事实来源：

- `SUBMITTED` / `RUNNING`：读取并同步 WeData 状态。
- `SUCCEEDED`：仅接受单行、单列、数值型 `row_count`。
- `FAILED`、`CANCELLED`、`TIMEOUT`：返回稳定错误码和脱敏错误信息。
- 本地记录过期：返回 `QUERY_EXPIRED`，不继续查询。
- 网络错误：标记或保留状态未知，不把网络失败误判为 Spark 失败，也不盲目重复创建任务。

状态机：

```text
SUBMITTED → RUNNING → SUCCEEDED
                    ├→ FAILED
                    ├→ CANCELLED
                    └→ TIMEOUT
```

只允许合法状态迁移，成功结果格式异常时返回 `RESULT_INVALID`，不能伪造行数。

## 5. 可靠性、安全与集群保护

### 5.1 SQL 与输入安全

- 表标识必须来自默认项目元数据的匹配结果。
- 分区字段必须来自元数据分区字段列表。
- 分区值进行长度、字符集和格式校验，并安全转义/参数化。
- 禁止任意 SQL、子查询、多表、函数注入、注释、分号和多语句。
- MCP schema 不提供 `sql` 字段。
- 不记录凭证、签名或敏感请求头；错误信息需要脱敏。

### 5.2 分区策略

- 所有查询都必须提供完整分区条件。
- 分区表有多个分区字段时必须全部提供。
- 只允许单个精确分区值，不允许范围、`IN`、通配符或跨分区查询。
- 可以基于可靠的分区事实提前返回 `PARTITION_NOT_FOUND`；事实不完整时由 Spark 返回真实执行错误。

### 5.3 集群保护

查询任务必须使用独立配置：

- 专用资源组/队列。
- 固定低优先级。
- 单查询最大执行时间。
- 单查询 driver/executor 资源上限。
- 调用方并发上限和全局并发上限。
- 同一表/分区最短重复提交间隔。
- 自动超时和仅针对查询任务的取消机制。
- 查询结果与本地状态 TTL。

同一 `default_project + table + normalized_partition` 在短时间内提交时返回现有 `query_id`，避免重复扫描。提交失败仅在明确确认 WeData 未创建任务时允许重试。任何取消操作只使用查询任务 ID，不操作生产任务。

### 5.4 错误码

使用稳定、脱敏的错误分类：

- `INVALID_TABLE`
- `TABLE_NOT_QUERYABLE`
- `PARTITION_REQUIRED`
- `PARTITION_INVALID`
- `PARTITION_NOT_FOUND`
- `QUERY_QUOTA_EXCEEDED`
- `QUERY_SUBMIT_FAILED`
- `QUERY_RUNNING`
- `QUERY_FAILED`
- `QUERY_TIMEOUT`
- `RESULT_INVALID`
- `QUERY_EXPIRED`
- `QUERY_ACCESS_DENIED`

## 6. MCP 工具契约

### 6.1 提交工具

工具名：`submit_partition_count_query`

输入：

```json
{
  "table_name": "dws_order_detail",
  "partition": {"ds": "2026-08-10"}
}
```

成功返回至少包含：

```json
{
  "query_id": "q_01J...",
  "status": "SUBMITTED",
  "table_name": "dws_order_detail",
  "partition": {"ds": "2026-08-10"},
  "wedata_task_id": "123456789",
  "submitted_at": "2026-08-10T12:00:00Z",
  "expires_at": "2026-08-10T13:00:00Z"
}
```

### 6.2 结果工具

工具名：`get_partition_count_query`

输入：

```json
{"query_id": "q_01J..."}
```

成功返回至少包含：

```json
{
  "query_id": "q_01J...",
  "status": "SUCCEEDED",
  "table_name": "dws_order_detail",
  "partition": {"ds": "2026-08-10"},
  "row_count": 12345678,
  "wedata_task_id": "123456789",
  "started_at": "2026-08-10T12:00:08Z",
  "finished_at": "2026-08-10T12:01:12Z",
  "sql_template_version": "partition-count-v1"
}
```

运行中返回 `RUNNING` 和 task ID；失败返回稳定 `error_code`、脱敏消息、task ID 和 `retryable`。

## 7. SQLite 状态模型

独立增加 `query_jobs` 表，不混入资产事实表：

```text
query_jobs
-----------
query_id
idempotency_key
table_name
partition_json
validated_table_identifier
generated_sql_hash
wedata_task_id
status
row_count
error_code
error_message
created_at
submitted_at
started_at
finished_at
expires_at
last_checked_at
```

要求：

- 默认只保存 SQL hash；若确有审计要求，保存脱敏 SQL。
- 幂等键由默认项目、规范化表和规范化分区计算。
- 结果和错误信息按 TTL 清理。
- 时间统一使用 UTC。
- schema migration 幂等并向后兼容。
- 本地状态库不可用时拒绝新提交，避免任务关联丢失。

## 8. 测试与验收

### 8.1 单元测试

覆盖表名规范化、非法输入、完整分区校验、注入防护、固定 SQL 生成与二次校验、状态迁移、幂等键、结果解析、错误脱敏和 TTL。

### 8.2 服务层测试

使用 fake WeData client 验证：只有元数据和资源策略通过才创建任务；缺分区、未知表、超配额均不创建任务；任务创建后正确写入状态；网络超时不重复创建；状态同步和非法结果处理正确；生产任务不会被查询逻辑更新或取消。

### 8.3 MCP 契约测试

验证工具注册、输入 schema 不接受任意 SQL、成功/运行中/失败/过期响应稳定、错误不泄露凭证，并可被自然语言层直接解释。

### 8.4 集成验收

在非生产项目或专用资源组完成：提交已知分区并校验可信行数；确认资源组、队列和优先级；验证缺分区、错误分区、非法表名、重复请求；观察生产任务不受影响；验证超时、失败和 TTL 清理。

## 9. 分阶段上线

### 阶段 0：dry-run

只生成并返回校验后的 SQL 和资源配置，不提交 WeData，用于验证元数据、分区规则和 SQL 模板。

### 阶段 1：测试项目

仅允许测试项目和测试资源组，低并发、短 TTL、严格配额，完成集成验收。

### 阶段 2：生产灰度

仅对白名单表和调用方开放，采集成功率、耗时、资源消耗和失败原因；观察期稳定后再扩大范围。

## 10. 未决实现前提

实现前必须从现有 WeData API 封装或配置中确认：

1. 创建一次性查询任务或专用模板的准确 API action 和参数。
2. 查询任务如何绑定专用资源组、队列、优先级和资源上限。
3. 任务状态读取接口和成功结果读取方式。
4. 默认项目 ID、专用查询资源组和调用方身份配置。
5. 是否存在可靠的分区元数据查询能力。

若当前腾讯云 API 不支持直接创建一次性任务，应先实现 `QueryExecutor` 抽象并接入专用查询模板，不能退化为直接提交生产任务。
