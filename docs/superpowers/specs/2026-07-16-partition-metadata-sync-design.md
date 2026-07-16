# Partition Metadata and DLC Partition Sync Design

Date: 2026-07-16

## Context

The useless-table candidate workbook marked `ods_cloud_cost_baidu_day_di` as non-partitioned even though it is a partitioned DLC table. The investigation found two separate facts were being conflated:

1. Whether a table is partitioned.
2. Whether partition statistics have been synced into `table_partitions`.

Current `AssetStore.get_table_partition_profile()` sets `is_partitioned = bool(table_partitions rows)`. When partition sync has no rows for a real partitioned table, the profile reports `is_partitioned=False`, and downstream Excel logic treats missing partition facts as “recently no partitions” and “recently no data”.

The correct model is: partitioning is a table property proven by table metadata or schema; partition rows are operational facts that may be missing, stale, or partially synced.

## Goals

- Determine `is_partitioned` from table metadata/schema, not from the existence of partition fact rows.
- Keep `table_partitions` as concrete partition facts: partition name, date, row count, storage, file count, timestamps.
- Sync partitions through DLC `DescribeTablePartitions` as the authoritative partition API.
- Support full partition sync for all known partitions of partitioned tables.
- Support incremental partition sync for yesterday's partition by default, or an explicit target date.
- Prevent governance and Excel output from treating missing partition facts as proof that a table is non-partitioned or empty.

## Non-goals

- Do not introduce a new schema table in this iteration.
- Do not delete historical partition facts during sync.
- Do not make WeData `ListTablePartitions` the primary path. Existing compatibility and diagnostics remain, but DLC is authoritative for this workflow.
- Do not perform expensive live row counts against business tables.

## Architecture

### Partition metadata helper

Add an internal helper in `dlc_mcp.assets`, tentatively named `_partition_metadata_for_table(table, columns, partition_rows=None)`.

It returns:

```python
{
    "is_partitioned": bool,
    "partition_keys": ["dt"],
    "partition_evidence": ["column:dt"],
    "partition_confidence": "high|medium|low|none",
}
```

Evidence order:

1. Explicit raw metadata fields from `tables.raw_json`, such as `PartitionKeys`, `PartitionColumns`, `Partitions`, `PartitionFields`, `PartitionInfo`, `TablePartition`, or equivalent nested structures.
2. Column-level partition hints in raw column metadata, if available.
3. Common partition columns in the cached schema. Initially support `dt`; keep the helper easy to extend for `ds`, `biz_date`, and `partition_date` later.
4. Existing `table_partitions` rows as supporting evidence only. This can prove a table is partitioned, but absence cannot prove it is not.

### Partition profile response

Update `get_table_partition_profile(table_name, partition_date="")` to fetch table metadata and columns before computing partition status.

Retain existing response fields, but change semantics and add new fields:

```python
{
    "table_name": "ods_cloud_cost_baidu_day_di",
    "partition_date": "",
    "is_partitioned": True,
    "partition_keys": ["dt"],
    "partition_evidence": ["column:dt"],
    "partition_confidence": "medium",
    "partition_fact_available": False,
    "partition_fact_status": "missing",
    "partition_count": 0,
    "latest_partition": None,
    "earliest_partition": None,
    "target_partition": None,
    "recent_partitions": [],
    "total_rows": 0,
    "total_storage_bytes": 0,
    "health_status": "unknown",
    "health_label": "未知",
    "reasons": ["表元数据/字段显示为分区表，但未同步到分区统计事实。"],
    "suggestions": ["运行 DLC 分区同步后再判断分区健康。"],
}
```

`partition_fact_status` values:

- `available`: partition rows exist.
- `missing`: table is partitioned but no partition rows exist.
- `not_partitioned`: metadata/schema does not indicate partitioning and no partition facts exist.
- `unknown`: table metadata is insufficient to prove either side.

`is_partitioned` must no longer equal `bool(all_rows)`.

### Health rules

- If partition facts exist, use current health logic for target/missing/empty/anomalous partitions.
- If `is_partitioned=True` but no partition facts exist, return `health_status="unknown"` and reason about insufficient partition facts.
- If `is_partitioned=False`, do not produce “recently no partition” or “zero-row partition” reasons.
- Missing facts must not contribute evidence that a table is useless.

## DLC partition sync

### Authority

Use DLC `DescribeTablePartitions` as the authoritative sync path. The runtime configuration should set:

```bash
WEDATA_SYNC_PARTITIONS=1
WEDATA_PARTITION_SERVICE=dlc
DLC_API_VERSION=2021-01-25
DLC_CATALOG=DataLakeCatalog
```

WeData `ListTablePartitions` remains available only for compatibility and diagnostics. Existing `InvalidAction` handling remains: classify it as action/version unsupported, not a payload parameter problem.

### Sync modes

Add `WEDATA_PARTITION_SYNC_MODE`:

- `full`: fetch all partitions returned by DLC for each partitioned table.
- `incremental`: fetch or filter to the target date only.

Default mode should be conservative for scheduled syncs: `incremental`.

### Date selection

For incremental mode:

- If `WEDATA_PARTITION_DATE` is set, use it.
- Otherwise default to yesterday in local date semantics, formatted as `YYYY-MM-DD`.
- Match both `dt=YYYY-MM-DD` and `dt=YYYYMMDD` forms.

For full mode:

- Do not set or require a partition date.
- Accept all partitions returned by DLC.

### Table scope

Partition sync should only call DLC for tables that the metadata helper classifies as partitioned.

The initial candidate set still comes from existing sync sources:

- parsed task outputs,
- table catalog,
- metadata detail results.

Before calling `DescribeTablePartitions`, filter with the metadata helper. If metadata is insufficient for a table, skip it and record a bounded failure or skip reason; do not guess from task names.

### Upsert behavior

- Upsert partition facts into `table_partitions`.
- Never delete historical partition rows as part of this change.
- Record per-table failures in `PartitionFailures` and continue syncing other tables.
- Keep existing pagination behavior for DLC `MixedPartitions`.

## Excel and governance output

Workbook/report generation should use the updated profile semantics:

| Column or evidence | New rule |
| --- | --- |
| `是否分区表` | `profile.is_partitioned` |
| `分区数量` | `profile.partition_count` |
| `分区事实不足` | `profile.is_partitioned and not profile.partition_fact_available` |
| `最近一个月无分区` | Only true when partition facts are available and facts show no recent partitions. Missing facts do not count. |
| `最近一个月分区无数据` | Only true when partition facts are available and facts show zero rows. Missing facts do not count. |
| `判断依据` | Use “分区事实不足” when a partitioned table has no partition facts. Do not write “非分区表” or “最近一个月无分区” from missing facts. |

For `ods_cloud_cost_baidu_day_di`, expected workbook semantics after the change:

```text
是否分区表: True
分区数量: 0 if facts are not synced yet
分区事实不足: 是
最近一个月无分区: 否 or blank while facts are missing
最近一个月分区无数据: 否 or blank while facts are missing
判断依据: 分区事实不足；无质量规则
```

After partition sync succeeds, the same row should reflect actual partition count and recent partition health.

## Error handling

- DLC API failures are recorded per table in `PartitionFailures` and do not abort the entire sync.
- Missing payload fields are recorded as skip/failure evidence.
- Empty incremental result for a date means “target partition not found for this sync”, not deletion.
- Existing WeData `InvalidAction` classification remains unchanged.
- If table metadata is missing, report metadata insufficiency instead of assuming non-partitioned.

## Tests

Add or update tests before implementation:

1. `get_table_partition_profile()` returns `is_partitioned=True` and `partition_fact_available=False` for a table with `dt` column and no `table_partitions` rows.
2. A table without partition metadata, partition columns, or partition facts returns `is_partitioned=False` or `partition_fact_status="not_partitioned"`.
3. Existing partition facts still make `partition_fact_available=True`, preserve `partition_count`, and use existing health checks.
4. Raw metadata with explicit partition keys returns high-confidence partition evidence.
5. DLC full sync does not require `WEDATA_PARTITION_DATE` and keeps all returned partitions.
6. DLC incremental sync defaults to yesterday when `WEDATA_PARTITION_DATE` is absent.
7. DLC incremental sync only keeps partitions matching the target date, supporting both dashed and compact date formats.
8. Partition sync filters out non-partitioned tables before calling DLC.
9. Excel/governance candidate logic does not treat missing partition facts as “recently no partition” or “zero data”.

## Acceptance criteria

- `ods_cloud_cost_baidu_day_di` is reported as partitioned based on metadata/schema even before partition facts are synced.
- Missing partition facts are visible as an insufficiency, not as evidence of non-partitioning or zero data.
- Full DLC partition sync can populate `table_partitions` with all returned partitions.
- Incremental DLC partition sync can update only yesterday's partition by default.
- Existing governance guardrail for WeData `ListTablePartitions InvalidAction` still holds.
- Tests covering partition profile semantics and sync modes pass.
