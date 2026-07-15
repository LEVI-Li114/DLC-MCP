# 每日巡检人工判断问题展示增强设计

日期：2026-07-15

## 背景

当前资产同步和层级自动修复已经暴露出一类不能仅靠自动规则立即解决的问题：部分资产需要人工判断层级、产出任务映射、运行实例窗口、Owner 责任链或生命周期状态。用户希望每日巡检资产分析报告直接展示这些问题，让用户按严重度和影响面每天处理最高优先级问题，剩余问题滚动进入后续巡检，逐步迭代治理。

## 目标

1. 在 `get_asset_governance_daily_report()` 返回结构中新增人工判断类资产覆盖问题分组。
2. 在 MCP 日报 Markdown 文本中直接展示这些分组，用户无需额外调用 issue inventory。
3. 每日报告按严重度和影响面优先展示当天应处理的问题。
4. 保留已有日报字段和区块，避免破坏现有调用方。
5. 不把质量规则补齐作为本轮人工判断问题的最高优先级，因为用户已确认源端质量规则本身较少。

## 非目标

- 不新增工单状态表。
- 不记录“已解决/未解决”的持久状态。
- 不自动判定短名表的业务层级。
- 不把临时表直接删除或隐藏。
- 不改变 `get_asset_governance_issue_inventory()` 的既有返回结构。

## 新增结构化字段

在 `get_asset_governance_daily_report()` 返回中新增：

```python
manual_review_sections
manual_review_top_items
```

### `manual_review_sections`

按问题类型分组，结构如下：

```json
[
  {
    "key": "layer_manual_mapping",
    "title": "层级待人工判断",
    "description": "表名无法自动推断数仓层级，但存在下游、任务或运行实例，需要人工确认层级或标记为临时/废弃。",
    "owner_bucket": "warehouse_owner",
    "count": 20,
    "items": []
  },
  {
    "key": "producer_mapping_review",
    "title": "产出任务映射待确认",
    "description": "表存在任务关联但没有识别到 output producer，需检查任务 output、SQL INSERT/CREATE 解析和表名标准化。",
    "owner_bucket": "data_platform",
    "count": 20,
    "items": []
  },
  {
    "key": "instance_window_review",
    "title": "运行实例窗口待确认",
    "description": "表已识别 producer 任务但没有匹配运行实例，需确认实例窗口、关键词、分页或任务是否确实未执行。",
    "owner_bucket": "data_platform",
    "count": 20,
    "items": []
  },
  {
    "key": "owner_review",
    "title": "Owner 责任待确认",
    "description": "表 Owner、任务 Owner、数据源 Owner 缺失或不一致，需要人工确认责任链。",
    "owner_bucket": "warehouse_owner",
    "count": 20,
    "items": []
  }
]
```

每个 item 包含可行动证据：

```json
{
  "name": "ods_encrypt_md5_mobile_df",
  "layer": "ods",
  "owner": "tencent",
  "severity": "P1",
  "downstream_count": 30,
  "task_count": 11,
  "producer_task_count": 0,
  "run_count": 0,
  "suspected_root_cause": "producer_missing_gap",
  "recommended_next_check": "Fix producer task mapping before judging task runs; no output task is currently linked to this table.",
  "owner_bucket": "data_platform",
  "daily_action": "确认 output producer 或 SQL INSERT/CREATE 解析。"
}
```

### `manual_review_top_items`

跨分组汇总当天最优先处理的人工判断问题。默认取 Top 10。

排序规则：

1. 严重度：P0 > P1 > P2。
2. 影响面：`downstream_count` 高优先。
3. 可行动性：有 `task_count` / `producer_task_count` / `run_count` 的优先。
4. 层级优先：ads / dws / dwd > dim / ods / mid > unknown / tmp。
5. 问题类型优先：producer 缺失 / 运行实例缺失 > 层级人工判断 > Owner 不一致 > 生命周期观察。

## 分组来源

- `layer_manual_mapping`
  - 来源：`get_asset_governance_issue_inventory()`
  - 条件：`issue_type = unknown_layer` 且 `suspected_root_cause = manual_mapping_needed`

- `producer_mapping_review`
  - 来源：`get_asset_governance_issue_inventory()`
  - 条件：`issue_type in {missing_task_mapping, missing_task_runs}` 且 `suspected_root_cause in {producer_mapping_gap, producer_missing_gap}`

- `instance_window_review`
  - 来源：`get_asset_governance_issue_inventory()`
  - 条件：`issue_type = missing_task_runs` 且 `suspected_root_cause = instance_window_gap`

- `owner_review`
  - 来源：现有 `owner_gaps`
  - 条件：表 Owner、任务 Owner、数据源 Owner 缺失或不一致

## Markdown 展示

在每日巡检 Markdown 中，在“资产画像缺口”之后、“质量规则缺口”之前新增：

```markdown
**今日优先人工判断问题**

| 优先级 | 问题类型 | 表名 | 影响证据 | 责任方 | 今日动作 |
| --- | --- | --- | --- | --- | --- |
| P1 | 产出任务映射缺失 | ods_encrypt_md5_mobile_df | 下游30，任务11，产出任务0，运行实例0 | 数据平台/数仓Owner | 确认 output producer 或 SQL INSERT/CREATE 解析 |
| P1 | 层级待判断 | company | 下游60，任务0，产出任务0，运行实例0 | 数仓Owner/业务Owner | 确认为 dim/ods/临时/废弃 |
```

随后展示按类型分组的详细区块：

```markdown
**需要人工判断的资产覆盖问题**

**层级待人工判断**
| 表名 | 层级 | Owner | 下游 | 任务 | 产出任务 | 运行实例 | 建议 |
| --- | --- | --- | --- | --- | --- | --- | --- |

**产出任务映射待确认**
| 表名 | 层级 | Owner | 下游 | 任务 | 产出任务 | 运行实例 | 建议 |
| --- | --- | --- | --- | --- | --- | --- | --- |

**运行实例窗口待确认**
| 表名 | 层级 | Owner | 下游 | 任务 | 产出任务 | 运行实例 | 建议 |
| --- | --- | --- | --- | --- | --- | --- | --- |

**Owner 责任待确认**
| 表名 | 层级 | Owner | 候选责任人 | 缺口 |
| --- | --- | --- | --- | --- |
```

Markdown 每组默认展示 10 条；结构化 JSON 每组保留 20 条。

## Top actions 调整

`top_actions` 中新增人工判断类动作，且优先级高于质量规则补齐：

```text
人工确认 4 类资产覆盖问题，优先处理产出任务映射和层级未知：ods_encrypt_md5_mobile_df、company。
```

质量规则缺口仍保留在质量规则区块，但不作为本轮人工判断类覆盖问题的最高优先级。

## 滚动治理机制

不新增状态表。日报基于当前事实库自然滚动：

- 如果当天修复了 layer，第二天该资产不再出现在 `unknown_layer`。
- 如果修复了 producer mapping，第二天该资产不再是 `producer_missing_gap`。
- 如果补到了 run，第二天该资产不再是 `instance_window_gap`。
- 如果仍未解决，它继续出现在日报里，直到事实发生变化。

## 测试计划

1. 单元测试 `get_asset_governance_daily_report()` 返回 `manual_review_sections` 和 `manual_review_top_items`。
2. 构造 unknown layer、producer missing、instance window、owner gap 四类数据，验证分组正确。
3. 验证 top items 按严重度、下游数和问题类型排序。
4. 验证 `top_actions` 中人工判断动作排在质量规则动作之前。
5. 验证 MCP Markdown 输出包含“今日优先人工判断问题”和“需要人工判断的资产覆盖问题”。
6. 验证已有日报字段仍存在：production_risks、coverage_gaps、quality_gaps、owner_gaps、lifecycle_watch、expert_review_queue。

## 验收标准

- 用户调用每日巡检报告时，能直接看到人工判断类资产覆盖问题。
- 报告能明确区分层级待判断、产出任务映射待确认、运行实例窗口待确认、Owner 责任待确认。
- 每条问题有表名、影响证据、责任方和下一步动作。
- 每日优先列表聚焦最高严重度和最大影响面的问题。
- 质量规则缺口仍展示，但不压过人工判断类覆盖问题。
- 不破坏现有 MCP 工具调用和已有字段。
