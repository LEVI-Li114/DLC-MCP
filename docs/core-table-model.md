# Asset Value and Core Table Model

This model answers two questions for every synced table:

- `value_tier`: how important the asset is.
- `core_level`: whether the table must be governed as a core table.

Asset type is intentionally excluded for now.

## Priority

```text
expert label > model score > raw metadata
```

If an expert label has `value_tier` or `core_level`, it wins. The model still keeps facts such as lineage, quality rules, and task runs visible.

## Value Tiers

| Tier | Meaning |
| --- | --- |
| L0 战略核心资产 | Company-level asset. A failure can affect financial settlement, customer bills, executive dashboards, or major decisions. |
| L1 业务核心资产 | Core asset for one business domain. A failure affects key domain reports, analysis, or downstream production tables. |
| L2 重要公共资产 | Reused by multiple downstream tasks or reports, but not yet business-critical. |
| L3 普通业务资产 | Single-purpose or limited-impact asset. |
| L4 低价值/待治理资产 | Temporary, test, backup, deprecated, or low-impact asset. |

## Core Levels

| Level | Meaning |
| --- | --- |
| P0 | Strategic core table. Must have owner, lineage, quality rules, timeliness monitoring, and expert confirmation. |
| P1 | Business core table. Must have owner, lineage, quality rules, and timeliness monitoring. |
| P2 | Important table. Should be reviewed and governed, but not a hard core table yet. |
| 非核心 | Normal table. Basic metadata is enough unless expert review says otherwise. |

## Current Score

The implemented score is intentionally simple and explainable:

| Dimension | Max | Evidence |
| --- | ---: | --- |
| `business_value` | 30 | Domain or table-name keywords such as bill, cost, amount, consume, revenue, pay, refund, order, customer, company. |
| `lineage_impact` | 25 | Downstream dependency count. 10+ gets 25, 5-9 gets 15, 1-4 gets 8. |
| `layer_position` | 15 | dwd/dws/ads get 15, dim gets 10, ods gets 5. |
| `governance_readiness` | 10 | Existing quality rules. |
| `run_stability` | 5 | Latest output task runs have no abnormal status. |
| `usage_heat` | 0 | Reserved. Not scored until query/report logs are integrated. |

Temporary/test/backup tables reduce business value and cap lineage impact.

## Score to Tier

| Score | Tier | Core Level |
| ---: | --- | --- |
| >= 85 | L0 战略核心资产 | P0 |
| 70-84 | L1 业务核心资产 | P1 |
| 50-69 | L2 重要公共资产 | P2 |
| 25-49 | L3 普通业务资产 | 非核心 |
| < 25 | L4 低价值/待治理资产 | 非核心 |

## MCP Usage

Use:

```text
get_table_profile(table_name)
```

The `core` field includes:

- value tier
- core level
- core-table boolean
- total score
- per-dimension score
- evidence
- expert label, if present
