import os
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from io import StringIO
from tempfile import TemporaryDirectory
from unittest.mock import patch

from dlc_mcp.sync_wedata import _catalog_table_names, _filter_new_asset_tables, _instance_window, _list_all, _metadata_table_count, _partition_payload, _sync_data_source_tasks, _sync_metadata, _sync_partitions, partition_payload_candidates


class FakeClient:
    def call(self, action, payload):
        return {"Response": {"Data": {"Items": [{"TaskId": payload["Id"]}]}}}


class FakePagedErrorClient:
    def call(self, action, payload):
        if payload["PageNumber"] == 1:
            return {"Response": {"Data": {"Items": [], "TotalPageNumber": 2}}}
        return {"Response": {"Error": {"Code": "RequestLimitExceeded", "Message": "slow down"}}}


class FakeMetadataClient:
    def call(self, action, payload):
        if action == "ListTable":
            return {"Response": {"Data": {"Items": [{"Name": payload["Keyword"], "Guid": payload["Keyword"] + "_guid"}]}}}
        if action == "GetTableColumns":
            return {"Response": {"Data": [{"Name": "id"}]}}
        return {"Response": {"Data": {"Items": []}}}


class FakePartitionClient:
    def call(self, action, payload):
        return {"Response": {"Data": {"Items": [{"PartitionName": "dt=" + payload.get("PartitionDate", "2026-07-08"), "RowCount": 10}]}}}


class FakeCatalogMetadataClient(FakeMetadataClient):
    def call(self, action, payload):
        if action == "ListTable":
            raise AssertionError("catalog table should be reused")
        return super().call(action, payload)


class SyncWeDataTest(unittest.TestCase):
    def test_instance_window_uses_explicit_dates(self):
        with patch.dict(
            os.environ,
            {"WEDATA_INSTANCE_START": "2026-07-01 00:00:00", "WEDATA_INSTANCE_END": "2026-07-01 23:59:59"},
        ):
            self.assertEqual(_instance_window(), ("2026-07-01 00:00:00", "2026-07-01 23:59:59"))

    def test_instance_window_defaults_to_two_day_rolling_window(self):
        with patch.dict(os.environ, {}, clear=True):
            start, end = _instance_window()

        today = datetime.now().date()
        yesterday = today - timedelta(days=1)
        self.assertEqual(start, f"{yesterday:%Y-%m-%d} 00:00:00")
        self.assertEqual(end, f"{today:%Y-%m-%d} 23:59:59")

    def test_data_source_task_sync_prints_progress(self):
        data_sources = {"Response": {"Data": {"Items": [{"Id": 1}, {"Id": 2}]}}}
        output = StringIO()

        with redirect_stdout(output):
            related = _sync_data_source_tasks(FakeClient(), data_sources, progress_every=1)

        self.assertEqual(sorted(related), ["1", "2"])
        self.assertIn("synced related tasks for 1/2 data sources", output.getvalue())
        self.assertIn("synced related tasks for 2/2 data sources", output.getvalue())

    def test_list_all_raises_on_later_page_error(self):
        with self.assertRaises(RuntimeError):
            _list_all(FakePagedErrorClient(), "ListTable", {}, 100)

    def test_metadata_table_count_uses_detail_payload_not_catalog(self):
        metadata_dump = {"tables": {"Response": {"Data": {"Items": [{}, {}]}}}}

        self.assertEqual(_metadata_table_count(metadata_dump), 2)

    def test_catalog_table_names_reads_name_variants(self):
        response = {
            "Response": {
                "Data": {
                    "Items": [
                        {"Name": "ads_bill_company_1d_di"},
                        {"TableName": "dws_360_fin_job_seat_1d_di"},
                        {"Name": ""},
                    ]
                }
            }
        }

        self.assertEqual(_catalog_table_names(response), ["ads_bill_company_1d_di", "dws_360_fin_job_seat_1d_di"])

    def test_metadata_sync_prints_progress(self):
        output = StringIO()
        with TemporaryDirectory() as tmpdir, redirect_stdout(output):
            _sync_metadata(FakeMetadataClient(), "project", [f"table_{index}" for index in range(10)], 100, tmpdir)

        self.assertIn("synced metadata for 10/10 tables", output.getvalue())

    def test_metadata_sync_reuses_catalog_table(self):
        with TemporaryDirectory() as tmpdir, redirect_stdout(StringIO()):
            payload = _sync_metadata(
                FakeCatalogMetadataClient(),
                "project",
                ["ads_bill_company_1d_di"],
                100,
                tmpdir,
                {"ads_bill_company_1d_di": {"Name": "ads_bill_company_1d_di", "Guid": "guid_001"}},
            )

        self.assertEqual(payload["tables"]["Response"]["Data"]["Items"][0]["Columns"], [{"Name": "id"}])

    def test_filter_new_asset_tables_uses_catalog_create_time(self):
        tables = {
            "new_table": {"Name": "new_table", "CreateTime": "2026-07-08 10:00:00"},
            "old_table": {"Name": "old_table", "CreateTime": "2026-07-07 10:00:00"},
            "updated_table": {"Name": "updated_table", "CreateTime": "2026-07-01 10:00:00", "UpdateTime": "2026-07-08 11:00:00"},
        }

        names = _filter_new_asset_tables(["new_table", "old_table", "updated_table"], tables, "2026-07-08", "2026-07-08")

        self.assertEqual(names, ["new_table", "updated_table"])

    def test_filter_new_asset_tables_fails_without_time_fields_in_strict_mode(self):
        with patch.dict(os.environ, {"WEDATA_NEW_ASSET_STRICT": "1"}):
            with self.assertRaises(RuntimeError):
                _filter_new_asset_tables(["table_a"], {"table_a": {"Name": "table_a"}}, "2026-07-08", "2026-07-08")

    def test_partition_sync_tags_table_name(self):
        with patch.dict(os.environ, {"WEDATA_PARTITION_DATE": "2026-07-08"}):
            response = _sync_partitions(FakePartitionClient(), "project", ["ads_bill_company_1d_di"], 100, progress_every=0)

        item = response["Response"]["Data"]["Items"][0]
        self.assertEqual(item["QueriedTableName"], "ads_bill_company_1d_di")
        self.assertEqual(item["PartitionName"], "dt=2026-07-08")

    def test_partition_payload_candidates_include_safe_identifier_combinations(self):
        payloads = partition_payload_candidates(
            "project-1",
            {
                "Name": "ads_revenue",
                "Guid": "guid-1",
                "DatabaseName": "ads_mart",
                "DatasourceId": 55975,
            },
        )

        self.assertEqual(
            payloads,
            [
                {"ProjectId": "project-1", "TableName": "ads_revenue"},
                {"ProjectId": "project-1", "TableGuid": "guid-1"},
                {"ProjectId": "project-1", "DatabaseName": "ads_mart", "TableName": "ads_revenue"},
                {"ProjectId": "project-1", "DataSourceId": "55975", "DatabaseName": "ads_mart", "TableName": "ads_revenue"},
            ],
        )

    def test_partition_payload_mode_selects_runtime_payload_shape(self):
        item = {"Guid": "guid-1", "DatabaseName": "ads_mart", "DatasourceId": 55975}

        with patch.dict(os.environ, {"WEDATA_PARTITION_PAYLOAD_MODE": "guid"}):
            self.assertEqual(_partition_payload("project-1", "ads_revenue", item), {"ProjectId": "project-1", "TableGuid": "guid-1"})
        with patch.dict(os.environ, {"WEDATA_PARTITION_PAYLOAD_MODE": "database"}):
            self.assertEqual(_partition_payload("project-1", "ads_revenue", item), {"ProjectId": "project-1", "TableName": "ads_revenue", "DatabaseName": "ads_mart"})
        with patch.dict(os.environ, {"WEDATA_PARTITION_PAYLOAD_MODE": "datasource_database"}):
            self.assertEqual(_partition_payload("project-1", "ads_revenue", item), {"ProjectId": "project-1", "TableName": "ads_revenue", "DataSourceId": 55975, "DatabaseName": "ads_mart"})


if __name__ == "__main__":
    unittest.main()
