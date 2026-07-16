import unittest
from datetime import date

from dlc_mcp.partitioning import (
    partition_matches_date,
    partition_metadata_for_table,
    partition_sync_target_date,
)


class PartitioningTest(unittest.TestCase):
    def test_dt_column_proves_partitioned_table_without_partition_facts(self):
        metadata = partition_metadata_for_table(
            {"name": "ods_cloud_cost_baidu_day_di", "raw": {}},
            [{"name": "dt", "type": "string"}, {"name": "id", "type": "bigint"}],
            [],
        )

        self.assertTrue(metadata["is_partitioned"])
        self.assertEqual(metadata["partition_keys"], ["dt"])
        self.assertIn("column:dt", metadata["partition_evidence"])
        self.assertEqual(metadata["partition_confidence"], "medium")

    def test_raw_partition_keys_are_high_confidence_evidence(self):
        metadata = partition_metadata_for_table(
            {"name": "ads_revenue", "raw": {"PartitionKeys": [{"Name": "biz_date"}]}},
            [{"name": "biz_date", "type": "string"}],
            [],
        )

        self.assertTrue(metadata["is_partitioned"])
        self.assertEqual(metadata["partition_keys"], ["biz_date"])
        self.assertIn("raw:PartitionKeys:biz_date", metadata["partition_evidence"])
        self.assertEqual(metadata["partition_confidence"], "high")

    def test_table_without_partition_metadata_columns_or_facts_is_not_partitioned(self):
        metadata = partition_metadata_for_table(
            {"name": "dim_customer", "raw": {}},
            [{"name": "customer_id", "type": "string"}],
            [],
        )

        self.assertFalse(metadata["is_partitioned"])
        self.assertEqual(metadata["partition_keys"], [])
        self.assertEqual(metadata["partition_evidence"], [])
        self.assertEqual(metadata["partition_confidence"], "none")

    def test_existing_partition_rows_are_supporting_evidence(self):
        metadata = partition_metadata_for_table(
            {"name": "ads_revenue", "raw": {}},
            [{"name": "id", "type": "bigint"}],
            [{"partition_name": "dt=20260715"}],
        )

        self.assertTrue(metadata["is_partitioned"])
        self.assertEqual(metadata["partition_keys"], [])
        self.assertIn("facts:table_partitions", metadata["partition_evidence"])
        self.assertEqual(metadata["partition_confidence"], "low")

    def test_incremental_target_date_defaults_to_yesterday(self):
        self.assertEqual(partition_sync_target_date(date(2026, 7, 16)), "2026-07-15")

    def test_partition_date_matching_supports_dashed_and_compact_dt(self):
        self.assertTrue(partition_matches_date({"Partition": "dt=20260715"}, "2026-07-15"))
        self.assertTrue(partition_matches_date({"PartitionName": "dt=2026-07-15"}, "2026-07-15"))
        self.assertFalse(partition_matches_date({"Partition": "dt=20260714"}, "2026-07-15"))


if __name__ == "__main__":
    unittest.main()
