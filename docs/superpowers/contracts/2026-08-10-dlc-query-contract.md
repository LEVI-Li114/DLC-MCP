# DLC Spark SQL Partition Count Contract

## Decision

The query execution boundary uses the public Tencent Cloud DLC API version `2021-01-25`. WeData remains the source of validated project/table metadata, but it is not used to execute SQL because its public SQL-exploration API does not expose a complete documented result contract.

Only generated, exact-partition `COUNT(*)` queries are allowed. Production WeData task APIs are never called.

## Operations

| Concept | DLC Action | Request fields | Response paths |
| --- | --- | --- | --- |
| submit | `CreateTasks` | `Tasks.TaskType=SparkSQLTask`, Base64 `Tasks.SQL`, `Tasks.FailureTolerance=Terminate`, `DatabaseName`, `DatasourceConnectionName`, `ResourceGroupName`, optional `DataEngineName` | `Response.TaskIdSet[0]` |
| status | `DescribeMCPTask` | `TaskId` | `Response.TaskInfo.State`, `Response.TaskInfo.OutputMessage` |
| result | `DescribeMCPTaskResult` | `TaskId` | `Response.TaskInfo.State`, `ResultSchema`, `ResultSet` |
| cancel | `CancelTask` | `TaskId` | successful API acknowledgement |

Official references:

- CreateTasks: https://cloud.tencent.com/document/api/1342/59274
- DescribeMCPTask: https://cloud.tencent.com/document/product/1342/134617
- DescribeMCPTaskResult: https://cloud.tencent.com/document/product/1342/134616
- CancelTask: https://cloud.tencent.com/document/api/1342/58476

## Status mapping

| DLC state | Local state |
| --- | --- |
| `0` | `SUBMITTED` |
| `1` | `RUNNING` |
| `2` | `SUCCEEDED` |
| `3` | `RUNNING` |
| `4` | `SUBMITTED` |
| `-1` | `FAILED` |
| `-3` | `CANCELLED` |

Unknown states are not guessed and return `STATUS_UNAVAILABLE`.

## Result contract

The result must have exactly one schema column named `row_count`, exactly one data row, and one non-negative integer value. Any other shape is `RESULT_INVALID`; no count is manufactured.

## Isolation and lifecycle

- `DLC_QUERY_RESOURCE_GROUP` is mandatory when submission is enabled.
- The service rejects tables outside `DLC_QUERY_DATABASE` and, when available, outside `WEDATA_PROJECT_ID`.
- Maximum concurrency defaults to two.
- Maximum runtime defaults to 300 seconds. Expired running tasks are cancelled using only their recorded DLC task ID.
- A transport timeout during submission becomes `SUBMISSION_UNCERTAIN` and is never blindly resubmitted.
- Only SQL hashes, partition values, task IDs, state, and numeric results are stored. Raw SQL and credentials are not persisted.
