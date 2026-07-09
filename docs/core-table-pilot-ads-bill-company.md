# 核心资产单表试点：ads_bill_company_1d_di

## 1. 试点目标

先以 `ads_bill_company_1d_di` 作为第一张核心候选表，验证完整资产画像链路是否跑通。后续再批量补充 30~50 张核心表。

本试点关注：

- 表是否已同步进资产库。
- 字段是否完整。
- 上下游血缘是否可查。
- 质量规则是否可查。
- 产出/消费任务是否可查。
- 最近运行实例是否可查。
- 数据源关联是否可查。
- `get_table_profile` 是否能返回完整标准表画像。
- `check_foundation` 是否能展示核心候选资产覆盖。

## 2. 候选清单

当前核心候选清单文件：

```text
docs/core-asset-candidates.csv
```

当前仅保留：

```text
ads_bill_company_1d_di
```

导入命令：

```bash
python3 -m dlc_mcp.import_core_candidates docs/core-asset-candidates.csv --env-file /etc/dlc-mcp/env
```

本地开发环境可用：

```bash
python3 -m dlc_mcp.import_core_candidates docs/core-asset-candidates.csv --db data/assets.db
```

## 3. 推荐服务端小样本同步配置

为了优先验证 `ads_bill_company_1d_di`，建议在 `/etc/dlc-mcp/env` 中临时配置：

```bash
WEDATA_SYNC_TABLE_CATALOG=1
WEDATA_SYNC_METADATA=1
WEDATA_METADATA_TABLES=ads_bill_company_1d_di
WEDATA_METADATA_TABLE_LIMIT=1
WEDATA_METADATA_WORKERS=1

WEDATA_SYNC_DATA_SOURCES=1

WEDATA_SYNC_INSTANCES=1
WEDATA_INSTANCE_KEYWORDS=ads_bill_company_1d_di
WEDATA_INSTANCE_MAX_PAGES=20
WEDATA_INSTANCE_LOOKBACK_DAYS=2

DLC_MCP_SYNC_HEALTH_CHECK=1
DLC_MCP_SYNC_GAP_TYPES=fields,lineage,quality,tasks,runs,data_source
DLC_MCP_SYNC_GAP_LIMIT=20
```

说明：

- `WEDATA_METADATA_TABLES` 锁定单表，避免 metadata 同步范围过大。
- `WEDATA_INSTANCE_KEYWORDS` 锁定单表相关任务实例，避免实例同步范围过大。
- `WEDATA_SYNC_DATA_SOURCES=1` 用于补齐数据源和数据源关联任务。

## 4. 执行顺序

### 推荐：一键执行单表试点脚本

脚本会临时覆盖同步范围，只同步和检查 `ads_bill_company_1d_di`：

```bash
cd /opt/dlc-mcp/DLC-MCP
bash deploy/sync-core-table-pilot.sh /etc/dlc-mcp/env
```

如果后续要临时试点其他表，可以通过环境变量覆盖：

```bash
DLC_MCP_CORE_TABLE_PILOT=your_table_name bash deploy/sync-core-table-pilot.sh /etc/dlc-mcp/env
```

### 手动执行步骤

#### Step 1：导入核心候选表

```bash
cd /opt/dlc-mcp/DLC-MCP
python3 -m dlc_mcp.import_core_candidates docs/core-asset-candidates.csv --env-file /etc/dlc-mcp/env
```

#### Step 2：执行单表小样本同步

```bash
cd /opt/dlc-mcp/DLC-MCP
bash deploy/sync-wedata-once.sh /etc/dlc-mcp/env
```

#### Step 3：只检查资产底座

```bash
bash deploy/check-asset-foundation.sh /etc/dlc-mcp/env
```

#### Step 4：查询标准表画像

```bash
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"get_table_profile","arguments":{"table_name":"ads_bill_company_1d_di"}}}' \
  | DLC_MCP_DB=/data/dlc-mcp/assets.db python3 -m dlc_mcp.server
```

如果 Gateway 已启动，也可以在 Codex 里直接问：

```text
用 dlc-mcp 查 ads_bill_company_1d_di 的标准表画像
```

## 5. 验收标准

`check_foundation` 报告中，`ads_bill_company_1d_di` 应达到：

| 检查项 | 期望 |
| --- | --- |
| 已同步 | Y |
| 字段 | `> 0` |
| 质量规则 | `> 0`，如果 WeData 有质量规则 |
| 血缘 | `> 0`，如果 WeData 可返回上下游 |
| 任务 | `> 0` |
| 运行实例 | `> 0`，如果实例同步时间窗口命中 |
| 数据源 | 非空，或明确 WeData 未提供 |

`get_table_profile` 应至少返回：

- 基础信息。
- 字段信息。
- 上下游血缘。
- 相关任务。
- 数据源信息。
- 质量监控。
- 运行状态。
- 核心资产判断。
- 当前缺口。

## 6. 若仍有缺口的排查顺序

### 表未同步

- 检查 `ListTasks` 是否能搜到产出任务。
- 检查 `ListTable` 是否能按 `ads_bill_company_1d_di` 返回表。
- 检查 `WEDATA_PROJECT_ID` 是否正确。

### 缺字段/血缘/质量规则

- 确认 `WEDATA_SYNC_METADATA=1`。
- 确认 `WEDATA_METADATA_TABLES=ads_bill_company_1d_di`。
- 检查 `ListTable` 是否返回 `Guid`。
- 检查 `GetTableColumns`、`ListLineage`、`ListQualityRules` 权限。

### 缺任务/运行实例

- 检查 `ListTasks` 返回的任务 inputs/outputs 是否包含该表。
- 检查 `WEDATA_SYNC_INSTANCES=1`。
- 检查 `WEDATA_INSTANCE_KEYWORDS` 是否过窄。
- 扩大 `WEDATA_INSTANCE_LOOKBACK_DAYS` 或指定 `WEDATA_INSTANCE_START/END`。

### 缺数据源

- 检查 `WEDATA_SYNC_DATA_SOURCES=1`。
- 检查表目录是否返回 `data_source_id`。
- 检查 `ListDataSources` 与 `GetDataSourceRelatedTasks` 是否有权限。
