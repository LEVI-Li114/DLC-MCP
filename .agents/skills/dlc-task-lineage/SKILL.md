---
name: dlc-task-lineage
description: Resolve data-source synchronization tasks, their actual output tables, first-level downstream task dependencies, downstream output tables, fields, and SQL DDL through native dlc-mcp evidence. Use for requests about task downstream relationships, task-to-table mappings, data-source inventories, or DDL exports where task names must never be used to infer tables.
---

# DLC Task Lineage

## Preconditions

- Use only native `dlc-mcp` MCP tools for asset queries.
- Do not use shell, `curl`, SSH, Gateway HTTP, or direct SQLite access.
- If native `dlc-mcp` tools are unavailable, stop and report the MCP loading problem.
- Interpret "downstream" as first-level downstream tasks. Use table lineage only when the user explicitly asks for downstream tables or table lineage.

## Evidence Workflow

Follow this order without skipping steps:

1. Resolve each synchronization task's output tables from its actual task definition, synchronization configuration, or ProcessLineage evidence.
2. Resolve first-level downstream tasks from the task-dependency API.
3. Resolve each downstream task's output tables from its actual task definition or configuration.
4. Query every resolved output table's fields and generate SQL DDL.
5. When a synchronization task has no downstream task, explicitly fall back to that synchronization task's verified output tables and export their DDL.
6. When any required evidence is absent, return `unresolved` or `missing_fields`. Never infer a table from a task name.

## Evidence Rules

- Accept task-table mappings only when the relation includes task definition, synchronization configuration, ProcessLineage, or a stored mapping produced from one of those sources.
- Use `list_task_relations(direction="downstream")` or equivalent dependency evidence for first-level downstream tasks. Do not substitute downstream table lineage.
- Treat a task search result without output-table fields as incomplete evidence.
- Do not apply naming rules such as `m2c_ods_xxx -> ods_xxx`, `task_name == table_name`, prefix removal, suffix removal, or fuzzy matching.
- Do not combine facts from incompatible refreshes when a snapshot or observation time is available.

## Result Contract

Return one record per task-to-output-table path with:

- synchronization task ID and name
- verified synchronization output table
- first-level downstream task ID and name, or `null`
- verified downstream output table, or the synchronization output table when the no-downstream fallback applies
- fields and SQL DDL
- `status`: `resolved`, `unresolved`, or `missing_fields`
- evidence source and observation time when available
- explicit gaps and the failed workflow step

Deduplicate repeated API evidence without collapsing distinct downstream tasks that produce the same table.

## Failure Behavior

- Return `unresolved` when a task exists but its actual output table cannot be established.
- Return `missing_fields` when a table is established but fields required for DDL are absent.
- Do not silently replace missing facts with cached task-name guesses.
- State which tool or evidence field was missing and stop that path's resolution.

## Example

For `m2c_ods_crm_account_df`, establish the source output from task evidence, then query its first-level downstream task. If the dependency result is `mid_crm_account_df`, independently resolve that task's output table. Return `mid_crm_account_df` and its DDL only after the output mapping and fields are verified.
