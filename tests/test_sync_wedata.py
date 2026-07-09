import os
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from io import StringIO
from tempfile import TemporaryDirectory
from unittest.mock import patch

from dlc_mcp.sync_wedata import _catalog_table_names, _instance_window, _metadata_table_count, _sync_data_source_tasks, _sync_metadata


class FakeClient:
    def call(self, action, payload):
        return {"Response": {"Data": {"Items": [{"TaskId": payload["Id"]}]}}}


class FakeMetadataClient:
    def call(self, action, payload):
        if action == "ListTable":
            return {"Response": {"Data": {"Items": [{"Name": payload["Keyword"], "Guid": payload["Keyword"] + "_guid"}]}}}
        if action == "GetTableColumns":
            return {"Response": {"Data": [{"Name": "id"}]}}
        return {"Response": {"Data": {"Items": []}}}


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


if __name__ == "__main__":
    unittest.main()
