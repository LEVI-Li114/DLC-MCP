# Spark SQL Partition Count Rollout

## Gate 1: local and fake-client verification

Run `pytest -q`. Confirm the MCP submit schema contains no `sql` field and all query tests pass.

## Gate 2: test project

1. Create or select a dedicated low-impact DLC resource group.
2. Use a read-only sub-account with access only to the allowed database/tables and the four documented query actions.
3. Configure the query variables with `DLC_QUERY_ENABLED=0` and restart the service.
4. Verify `tools/list` exposes the three query tools but submission reports `query_service_unavailable`.
5. Set `DLC_QUERY_ENABLED=1`, restart, and submit a small known partition.
6. Poll the returned `query_id`; compare the result with a separately verified count.
7. Test cancellation and a deliberately short maximum runtime.

## Gate 3: production gray

- Start with one database, one dedicated resource group, concurrency `1`, and runtime at most 300 seconds.
- Allow only exact partitions with validated metadata keys.
- Treat every accepted submission as a new DLC task, including repeated requests for the same table and partition.
- Monitor DLC queue time, execution time, scanned bytes, failure count, cancellation count, and production resource-group health.
- Raise concurrency only after several days without production-task impact.

## Rollback

Set `DLC_QUERY_ENABLED=0` and restart the MCP service. This prevents new submissions. Existing query tasks may be cancelled only through their recorded query IDs; rollback never cancels or modifies WeData production tasks.

## Smoke request

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"submit_partition_count_query","arguments":{"table_name":"orders","partition":{"ds":"2026-08-10"}}}}
```

Use the returned `query_id` with `get_partition_count_query`. Do not pass raw SQL through any user-facing path.
