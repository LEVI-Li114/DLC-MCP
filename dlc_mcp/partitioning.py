from datetime import date, timedelta


COMMON_PARTITION_COLUMNS = {"dt"}
RAW_PARTITION_FIELDS = (
    "PartitionKeys",
    "PartitionColumns",
    "PartitionFields",
    "Partitions",
    "PartitionInfo",
    "TablePartition",
)
PARTITION_NAME_FIELDS = ("PartitionName", "Partition", "PartitionSpec", "Name", "partition_name")


def partition_metadata_for_table(table, columns, partition_rows=None):
    partition_rows = partition_rows or []
    raw = table.get("raw") or {}
    keys = []
    evidence = []

    for field in RAW_PARTITION_FIELDS:
        for key in _partition_keys_from_raw_value(raw.get(field)):
            if key not in keys:
                keys.append(key)
                evidence.append(f"raw:{field}:{key}")

    if keys:
        return {
            "is_partitioned": True,
            "partition_keys": keys,
            "partition_evidence": evidence,
            "partition_confidence": "high",
        }

    for column in columns or []:
        name = str(column.get("name") or "").strip()
        if name in COMMON_PARTITION_COLUMNS and name not in keys:
            keys.append(name)
            evidence.append(f"column:{name}")

    if keys:
        return {
            "is_partitioned": True,
            "partition_keys": keys,
            "partition_evidence": evidence,
            "partition_confidence": "medium",
        }

    if partition_rows:
        return {
            "is_partitioned": True,
            "partition_keys": [],
            "partition_evidence": ["facts:table_partitions"],
            "partition_confidence": "low",
        }

    return {
        "is_partitioned": False,
        "partition_keys": [],
        "partition_evidence": [],
        "partition_confidence": "none",
    }


def partition_sync_target_date(today=None):
    today = today or date.today()
    return f"{today - timedelta(days=1):%Y-%m-%d}"


def partition_matches_date(item, partition_date):
    if not partition_date:
        return True
    expected = {partition_date, partition_date.replace("-", "")}
    for field in PARTITION_NAME_FIELDS:
        value = str(item.get(field) or "")
        if any(f"dt={candidate}" in value or value == candidate for candidate in expected):
            return True
    return False


def _partition_keys_from_raw_value(value):
    if not value:
        return []
    if isinstance(value, str):
        return [value] if _looks_like_partition_key(value) else []
    if isinstance(value, dict):
        names = []
        for key in ("Name", "ColumnName", "FieldName", "name", "columnName", "fieldName"):
            if _looks_like_partition_key(value.get(key)):
                names.append(str(value[key]))
        for key in RAW_PARTITION_FIELDS + ("Keys", "Columns", "Fields", "items", "Items"):
            names.extend(_partition_keys_from_raw_value(value.get(key)))
        return _dedupe(names)
    if isinstance(value, list):
        names = []
        for item in value:
            names.extend(_partition_keys_from_raw_value(item))
        return _dedupe(names)
    return []


def _looks_like_partition_key(value):
    text = str(value or "").strip()
    return bool(text and text not in {"[]", "{}"})


def _dedupe(values):
    result = []
    seen = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
