import hashlib
import re
from collections.abc import Mapping

from .query_models import ValidatedQuery


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_LITERAL = re.compile(r"^[A-Za-z0-9_.:/+\-]{1,128}$")
_FIXED_SQL = re.compile(
    r"^SELECT COUNT\(\*\) AS row_count FROM "
    r"`[A-Za-z_][A-Za-z0-9_]*`(?:\.`[A-Za-z_][A-Za-z0-9_]*`){0,2} WHERE "
    r"`[A-Za-z_][A-Za-z0-9_]*` = '[A-Za-z0-9_.:/+\-]+'"
    r"(?: AND `[A-Za-z_][A-Za-z0-9_]*` = '[A-Za-z0-9_.:/+\-]+')*$"
)


class QueryValidationError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        self.safe_message = message
        super().__init__(f"{code}: {message}")


def normalize_table_name(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 192:
        raise QueryValidationError("INVALID_TABLE", "table name is empty or too long")
    parts = value.strip().split(".")
    if not 1 <= len(parts) <= 3 or any(not _IDENTIFIER.fullmatch(part) for part in parts):
        raise QueryValidationError("INVALID_TABLE", "table name is not a valid metadata identifier")
    return ".".join(parts)


def validate_partition(table: dict, partition: Mapping[str, str]) -> dict[str, str]:
    keys = table.get("partition_keys") or []
    if not keys:
        raise QueryValidationError("PARTITION_REQUIRED", "table has no reliable partition-key metadata")
    if not isinstance(partition, Mapping) or not partition:
        raise QueryValidationError("PARTITION_REQUIRED", "all partition keys are required")
    if set(partition) != set(keys):
        raise QueryValidationError("PARTITION_REQUIRED", "partition keys must exactly match table metadata")
    normalized = {}
    for key in sorted(keys):
        if not _IDENTIFIER.fullmatch(str(key)):
            raise QueryValidationError("INVALID_PARTITION", "partition metadata contains an invalid identifier")
        value = partition.get(key)
        if not isinstance(value, str) or not _LITERAL.fullmatch(value):
            raise QueryValidationError("INVALID_PARTITION", f"partition value for {key} is invalid")
        normalized[key] = value
    return normalized


def build_partition_count_sql(table_identifier: str, partition: dict[str, str]) -> str:
    table_identifier = normalize_table_name(table_identifier)
    if not partition:
        raise QueryValidationError("PARTITION_REQUIRED", "at least one partition predicate is required")
    quoted_table = ".".join(f"`{part}`" for part in table_identifier.split("."))
    predicates = []
    for key in sorted(partition):
        if not _IDENTIFIER.fullmatch(key) or not _LITERAL.fullmatch(partition[key]):
            raise QueryValidationError("INVALID_PARTITION", "partition predicate is invalid")
        predicates.append(f"`{key}` = '{partition[key]}'")
    sql = f"SELECT COUNT(*) AS row_count FROM {quoted_table} WHERE " + " AND ".join(predicates)
    validate_generated_sql(sql)
    return sql


def validate_generated_sql(sql: str) -> None:
    if not isinstance(sql, str) or not _FIXED_SQL.fullmatch(sql):
        raise QueryValidationError("SQL_INVALID", "generated SQL does not match the fixed count-query shape")
    lowered = sql.lower()
    forbidden = (";", "--", "/*", " join ", " union ", "select select", " insert ", " update ", " delete ", " drop ", " alter ")
    if any(token in lowered for token in forbidden):
        raise QueryValidationError("SQL_INVALID", "generated SQL contains a forbidden construct")


def make_validated_query(table_identifier: str, partition: dict[str, str], scope: str) -> ValidatedQuery:
    sql = build_partition_count_sql(table_identifier, partition)
    sql_hash = hashlib.sha256(sql.encode("utf-8")).hexdigest()
    partition_key = "&".join(f"{key}={partition[key]}" for key in sorted(partition))
    idempotency_key = hashlib.sha256(f"{scope}:{table_identifier}:{partition_key}".encode("utf-8")).hexdigest()
    return ValidatedQuery(table_identifier, dict(partition), sql, sql_hash, idempotency_key)
