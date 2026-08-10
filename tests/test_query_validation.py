import pytest

from dlc_mcp.query_validation import (
    QueryValidationError,
    build_partition_count_sql,
    normalize_table_name,
    validate_generated_sql,
    validate_partition,
)


def test_requires_all_partition_keys():
    with pytest.raises(QueryValidationError, match="PARTITION_REQUIRED"):
        validate_partition({"partition_keys": ["ds", "region"]}, {"ds": "2026-08-10"})


def test_rejects_sql_fragments_in_table_and_partition_values():
    for value in ["orders;drop", "orders--comment", "x' OR 1=1", "${bad}"]:
        with pytest.raises(QueryValidationError):
            normalize_table_name(value)
    with pytest.raises(QueryValidationError):
        validate_partition({"partition_keys": ["ds"]}, {"ds": "x' OR 1=1"})


def test_builds_only_fixed_count_sql():
    sql = build_partition_count_sql("dws_order_detail", {"ds": "2026-08-10"})
    assert sql == "SELECT COUNT(*) AS row_count FROM `dws_order_detail` WHERE `ds` = '2026-08-10'"


def test_partition_order_is_deterministic():
    sql = build_partition_count_sql("dw.orders", {"region": "cn", "ds": "2026-08-10"})
    assert sql.endswith("WHERE `ds` = '2026-08-10' AND `region` = 'cn'")


@pytest.mark.parametrize("sql", [
    "SELECT * FROM t",
    "SELECT COUNT(*) AS row_count FROM `t`",
    "SELECT COUNT(*) AS row_count FROM `t` WHERE `ds` = 'x'; DROP TABLE t",
])
def test_second_pass_rejects_non_fixed_sql(sql):
    with pytest.raises(QueryValidationError):
        validate_generated_sql(sql)
