# WeData 项目、任务依赖、表元数据接口设计

日期：2026-07-13

## 背景

项目当前是 WeData-first 的只读 MCP server。用户通过 MCP tools 查询资产、任务、元数据、质量、血缘、数据源、运行实例和治理结论。普通用户不直接接触腾讯云 AK/SK；Live Connector 负责调用腾讯云 API，Asset Store 负责缓存事实，MCP 层负责输出可读 Markdown。

腾讯云文档 https://cloud.tencent.com/document/product/1267/123653 列出 WeData 的项目管理、数据开发、元数据相关接口。本次新增 6 个接口能力：

- 项目管理：`ListProjects`、`GetProject`、`ListProjectMembers`
- 数据开发：`ListDownstreamTasks`、`ListUpstreamTasks`
- 元数据：`GetTable`

## 目标

1. 暴露用户可直接调用的 MCP tools。
2. 内部映射到腾讯云 WeData Action。
3. API 返回事实写入 SQLite，供后续治理画像、项目名展示、Owner 责任链、同步健康等能力复用。
4. MCP 输出保持现有风格：Markdown 摘要 + 关键字段表格。
5. 兼容腾讯云响应字段不完整或多版本差异，保留原始响应片段到 `raw_json`。

## 非目标

- 不直接向用户透传完整腾讯云原始 JSON。
- 不改变 `TencentCloudClient.call(action, payload)` 的 TC3 签名模型。
- 不替代现有 `get_table_profile`。新增 `get_table` 更贴近腾讯云表元数据详情；`get_table_profile` 继续负责治理画像。
- 不实现写操作、授权操作或项目成员变更操作。

## 用户侧 MCP tools

工具名采用项目现有 snake_case 风格，内部映射腾讯云 Action。

| MCP tool | 腾讯云 Action | 主要用途 |
| --- | --- | --- |
| `list_projects` | `ListProjects` | 查看项目列表 |
| `get_project` | `GetProject` | 查看单个项目详情 |
| `list_project_members` | `ListProjectMembers` | 查看项目成员 |
| `list_downstream_tasks` | `ListDownstreamTasks` | 查看任务下游依赖 |
| `list_upstream_tasks` | `ListUpstreamTasks` | 查看任务上游依赖 |
| `get_table` | `GetTable` | 查看单表元数据详情 |

## 架构设计

保持现有分层：

- `dlc_mcp/tencentcloud.py`：继续负责 TC3 签名和通用 API 调用。
- `dlc_mcp/live.py`：新增 live 同步方法：
  - `sync_projects(query="")`
  - `sync_project(project_id)`
  - `sync_project_members(project_id)`
  - `sync_task_relations(task_id, direction, project_id)`
  - `sync_table_detail(table_name="", table_guid="", project_id="")`
- `dlc_mcp/wedata.py`：新增响应归一化，把 WeData 响应转成项目、成员、任务依赖、表详情等统一结构。
- `dlc_mcp/assets.py`：新增 SQLite 表、upsert/list/get 方法，并扩展表元数据字段。
- `dlc_mcp/mcp.py`：注册 6 个 tool，处理缓存优先、live 刷新和 Markdown 输出。
- `tests/`：覆盖 store、归一化、MCP、live 调用和文档清单。

## 默认项目 ID 行为

所有需要 `project_id` 的工具遵循同一规则：

1. 如果参数里传了 `project_id`，使用参数值。
2. 否则使用环境变量 `WEDATA_PROJECT_ID`。
3. 如果两者都没有，返回结构化错误 `missing_project_id`，Markdown 提示用户传参或配置环境变量。

`list_projects` 不需要默认项目 ID。

## SQLite 缓存模型

### `projects`

缓存 `ListProjects` / `GetProject`。

字段：

- `id text primary key`
- `name text not null default ''`
- `display_name text not null default ''`
- `description text not null default ''`
- `owner text not null default ''`
- `status text not null default ''`
- `region text not null default ''`
- `create_time text not null default ''`
- `update_time text not null default ''`
- `raw_json text not null default '{}'`

用途：项目列表、项目详情、项目名展示、后续同步健康和项目级治理范围。

### `project_members`

缓存 `ListProjectMembers`。

字段：

- `project_id text not null`
- `member_id text not null`
- `member_name text not null default ''`
- `display_name text not null default ''`
- `role_name text not null default ''`
- `role_id text not null default ''`
- `member_type text not null default ''`
- `join_time text not null default ''`
- `raw_json text not null default '{}'`
- 主键：`(project_id, member_id, role_id)`

用途：项目成员列表、Owner 责任链补充、后续权限和责任人分析。

### `task_relations`

缓存 `ListUpstreamTasks` / `ListDownstreamTasks`。

字段：

- `project_id text not null`
- `task_id text not null`
- `related_task_id text not null`
- `direction text not null`，取值 `upstream` 或 `downstream`
- `task_name text not null default ''`
- `related_task_name text not null default ''`
- `dependency_type text not null default ''`
- `owner text not null default ''`
- `status text not null default ''`
- `raw_json text not null default '{}'`
- 主键：`(project_id, task_id, related_task_id, direction)`

任务依赖不一定等同于表级血缘，因此单独建表，避免污染 `task_tables`。相关任务如果响应中包含足够信息，也同步 upsert 到 `tasks`，方便 `search_tasks` 复用。

### `tables` 扩展

`GetTable` 结果继续写入现有 `tables`。扩展字段：

- `project_id text not null default ''`
- `table_type text not null default ''`
- `catalog_name text not null default ''`
- `schema_name text not null default ''`
- `raw_json text not null default '{}'`

初始化 schema 时使用兼容旧库的 `alter table ... add column` 防护逻辑。

## Tool 行为

### `list_projects`

参数：

- `query?: string`
- `live?: boolean`

行为：先读 SQLite；如果 `live=true` 或缓存为空，调用 `ListProjects` 写入 `projects` 后再读缓存。`query` 对项目 ID、名称、负责人、状态做本地过滤。

输出：项目数，以及项目 ID、名称、负责人、状态、区域、创建时间、更新时间表格。

### `get_project`

参数：

- `project_id?: string`
- `live?: boolean`

行为：`project_id` 缺省使用 `WEDATA_PROJECT_ID`。先读 SQLite；如果 `live=true` 或未命中，调用 `GetProject` 写入 `projects` 后再读缓存。

输出：项目 ID、名称、描述、负责人、状态、区域、创建/更新时间。

### `list_project_members`

参数：

- `project_id?: string`
- `live?: boolean`

行为：`project_id` 缺省使用 `WEDATA_PROJECT_ID`。先读 SQLite；如果 `live=true` 或缓存为空，调用 `ListProjectMembers` 并替换该项目成员缓存。

输出：项目 ID、成员数，以及成员 ID、名称、展示名、角色、成员类型、加入时间表格。

### `list_downstream_tasks`

参数：

- `task_id: string`
- `project_id?: string`
- `live?: boolean`

行为：`project_id` 缺省使用 `WEDATA_PROJECT_ID`。先读 `task_relations` 中 `direction='downstream'`；如果 `live=true` 或缓存为空，调用 `ListDownstreamTasks` 写入 `task_relations` 后再读缓存。

输出：查询任务 ID、下游任务数，以及下游 TaskId、任务名、依赖类型、负责人、状态表格。

### `list_upstream_tasks`

参数同 `list_downstream_tasks`，但 `direction='upstream'`，调用 `ListUpstreamTasks`。

输出：查询任务 ID、上游任务数，以及上游 TaskId、任务名、依赖类型、负责人、状态表格。

### `get_table`

参数：

- `table_name?: string`
- `table_guid?: string`
- `live?: boolean`

约束：`table_name` 和 `table_guid` 至少传一个。`GetTable` 使用表 GUID 或表名查询，不传 `ProjectId`。

行为：

1. 先读 SQLite `tables`。
2. 如果 `live=true` 且能构造 `GetTable` 请求，调用 `GetTable`，写入 `tables` 和响应中可能存在的字段列表。
3. 如果只传 `table_name` 且缓存中有 `source_guid`，使用该 GUID 调 live。
4. 如果只传 `table_name`、要求 live、但缓存没有 GUID，返回 `table_guid_required`，提示传 `table_guid` 或先用 `get_table_profile(live=true)` 补齐。
5. 再读缓存并输出。

输出：表基础信息，包括表名、GUID、库/Schema/Catalog、数据源、Owner、类型、描述；如果响应含字段，显示字段数或摘要，字段明细仍推荐 `list_table_columns`。

## 字段兼容策略

腾讯云概览页没有给完整 schema。归一化层沿用项目现有兼容策略：

- `_items(response)` 兼容：
  - `Response.Data.Items`
  - `Response.Data.List`
  - `Response.Data.Rows`
  - `Response.Data.Records`
  - `Response.Data` 直接是数组
- `_get(item, ...)` 从多个候选字段名读取同一语义字段。
- 详情接口兼容：
  - `Response.Data`
  - `Response.Project`
  - `Response.Table`
  - `Response` 内直接有业务字段
- 未归一化但有价值的字段存入 `raw_json`。

## 错误处理

新增结构化错误：

- `missing_project_id`：需要项目 ID，但参数和 `WEDATA_PROJECT_ID` 都没有。
- `missing_table_identity`：`get_table` 未传 `table_name` 或 `table_guid`。
- `table_guid_required`：要求 live 查询 `GetTable`，但只有表名且缓存中没有 GUID。
- `project_not_found`
- `project_members_not_found`
- `task_relations_not_found`
- `table_not_found`

Live API 如果返回 `Response.Error`，沿用当前 `_list_all` 行为抛出 `RuntimeError`。如果实现过程中发现异常会让 MCP 请求崩溃，则做小范围增强：捕获 `RuntimeError` 并返回 `live_api_error`。

## API catalog 更新

在 `TENCENT_CLOUD_API_CATALOG` 登记：

- `ListProjects`：项目管理相关接口，查看项目详情列表。
- `GetProject`：项目管理相关接口，查看项目详情。
- `ListProjectMembers`：项目管理相关接口，查看项目成员列表。
- `ListDownstreamTasks`：数据开发相关接口，查看下游任务列表。
- `ListUpstreamTasks`：数据开发相关接口，查看上游任务列表。
- `GetTable`：元数据相关接口，获取表详情。

所有条目使用用户提供的腾讯云文档 URL 作为 `source_url`。

## 测试策略

### `tests/test_assets.py`

- schema 初始化包含新表和新字段。
- `upsert_project` / `list_projects` / `get_project`。
- `replace_project_members` / `list_project_members`。
- `replace_task_relations` / `list_task_relations`。
- `upsert_table` 保存 `project_id`、`table_type`、`catalog_name`、`schema_name`、`raw_json`。

### `tests/test_wedata_import.py`

- 模拟 `ListProjects`、`GetProject`、`ListProjectMembers`、`ListUpstreamTasks`、`ListDownstreamTasks`、`GetTable` 响应，验证归一化和导入。
- 覆盖字段名多版本兼容。

### `tests/test_mcp.py`

- `tools/list` 包含 6 个新 tool。
- 每个 tool 返回 Markdown 标题和核心表格内容。
- 缺参数时返回可读错误。

### live / 腾讯云调用测试

- fake client 验证调用的 Action 名正确。
- 验证 `project_id` 默认来自 `WEDATA_PROJECT_ID`。
- 验证 `live=true` 会调用 API 并写入缓存。

### 文档测试

- README Tools 表包含 6 个新增工具。
- 如其他文档有工具清单，也同步更新。

验证命令：

```bash
python3 -m unittest discover -s tests -v
node --check bin/dlc-mcp.js
npm pack --dry-run
```

## 实施顺序

1. 更新腾讯云 API catalog。
2. 扩展 SQLite schema 和 AssetStore 方法。
3. 扩展 WeData 响应归一化与导入。
4. 扩展 Live Connector。
5. 新增 MCP tools 和 Markdown 格式化。
6. 更新 README 和相关文档。
7. 补测试并运行验证命令。

## 通过标准

- 6 个新工具出现在 `tools/list`。
- 新工具默认返回 Markdown 摘要和表格。
- `live=true` 能通过 fake client 调用正确 Tencent Cloud Action。
- 项目、项目成员、任务依赖、表详情事实能缓存进 SQLite。
- 缺少 `project_id` 或表身份时返回可读错误。
- README 工具清单更新。
- 单元测试和 Node 检查通过。
