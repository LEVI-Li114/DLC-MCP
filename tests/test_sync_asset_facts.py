import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dlc_mcp.assets import AssetStore
from dlc_mcp import sync_asset_facts


class FakeClient:
    def call(self, action, payload):
        if action == "ListTable":
            return {"Response": {"Data": {"Items": [{"Name": "ads_bill_company_1d_di", "Guid": "guid_1"}]}}}
        if action == "ListTasks":
            return {"Response": {"Data": {"Items": [{"TaskId": "task_1", "TaskName": "build_ads_bill_company_1d_di", "OutputTables": ["ads_bill_company_1d_di"]}]}}}
        if action == "ListLineage":
            return {"Response": {"Data": {"Items": [{"Resource": {"ResourceProperties": [{"Name": "TableName", "Value": "ads_downstream"}]}}]}}}
        if action == "ListQualityRules":
            return {"Response": {"Data": {"Items": [{"TableName": "ads_bill_company_1d_di", "Name": "not_null", "Target": "id"}]}}}
        if action == "ListTaskInstances":
            return {"Response": {"Data": {"Items": [{"TaskId": "task_1", "InstanceId": "inst_1", "Status": "COMPLETED"}]}}}
        return {"Response": {"Data": {"Items": []}}}


class SyncAssetFactsTest(unittest.TestCase):
    def test_full_asset_facts_imports_tasks_lineage_quality_and_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "assets.db")
            with patch.dict("os.environ", {"WEDATA_PROJECT_ID": "project", "DLC_MCP_DB": db_path, "DLC_MCP_SYNC_DIR": tmp}), patch.object(sync_asset_facts.TencentCloudClient, "wedata_from_env", return_value=FakeClient()), patch("sys.argv", ["sync_asset_facts", "--request-interval", "0"]):
                sync_asset_facts.main()

            store = AssetStore(sqlite3.connect(db_path))
            self.assertEqual(store.get_task("task_1")["outputs"], ["ads_bill_company_1d_di"])
            self.assertEqual(store.get_quality_status("ads_bill_company_1d_di")["rule_count"], 1)
            self.assertEqual(store.get_task_runs("task_1")["runs"][0]["status"], "COMPLETED")
            report = json.loads((Path(tmp) / "wedata_asset_facts_full_report.json").read_text())
            self.assertEqual(report["failed_count"], 0)


if __name__ == "__main__":
    unittest.main()
