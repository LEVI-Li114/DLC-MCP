import csv
import os
import sqlite3
import tempfile
import unittest

from dlc_mcp.assets import AssetStore
from dlc_mcp.check_foundation import render_foundation_report
from dlc_mcp.import_core_candidates import import_core_candidates, load_core_candidates


class CoreCandidatesTest(unittest.TestCase):
    def test_loads_core_candidate_csv_as_expert_labels(self):
        path = _write_candidates(
            [
                {
                    "asset_name": "ads_bill_company_1d_di",
                    "layer": "ads",
                    "domain": "财务分析",
                    "owner": "data-finance",
                    "use_case": "账单公司维度分析",
                    "core_level": "P1",
                    "value_tier": "核心",
                    "reviewer": "data-team",
                    "reason": "财务分析核心看板依赖",
                    "metric_definition": "公司账单指标口径",
                }
            ]
        )
        try:
            labels = load_core_candidates(path)
        finally:
            os.unlink(path)

        self.assertEqual(labels[0]["asset_type"], "table")
        self.assertEqual(labels[0]["asset_name"], "ads_bill_company_1d_di")
        self.assertEqual(labels[0]["core_level"], "P1")
        self.assertEqual(labels[0]["value_tier"], "核心")
        self.assertIn("layer=ads", labels[0]["reason"])

    def test_imports_candidates_and_reports_candidate_coverage(self):
        store = AssetStore(sqlite3.connect(":memory:"))
        store.init_schema()
        store.upsert_table({"name": "ads_bill_company_1d_di", "layer": "ads", "domain": "finance", "owner": "data-finance"})
        store.upsert_column("ads_bill_company_1d_di", "company_id", "string", "Company ID", 1)
        store.upsert_quality_rule({"table_name": "ads_bill_company_1d_di", "rule_name": "company_id_not_null"})
        store.upsert_task({"id": "task_001", "name": "ads_bill_company_1d_di", "outputs": ["ads_bill_company_1d_di"]})
        path = _write_candidates(
            [
                {"asset_name": "ads_bill_company_1d_di", "layer": "ads", "domain": "财务分析", "owner": "data-finance", "core_level": "P1", "value_tier": "核心"},
                {"asset_name": "dws_missing_candidate", "layer": "dws", "domain": "业务分析", "owner": "data-business", "core_level": "P2", "value_tier": "重要"},
            ]
        )
        try:
            self.assertEqual(import_core_candidates(store, path), 2)
        finally:
            os.unlink(path)

        candidates = store.list_core_candidates()["results"]
        self.assertEqual([candidate["name"] for candidate in candidates], ["ads_bill_company_1d_di", "dws_missing_candidate"])
        self.assertEqual(candidates[0]["table_synced"], 1)
        self.assertEqual(candidates[1]["table_synced"], 0)
        self.assertIn("表未同步", candidates[1]["gaps"])

        report = render_foundation_report(store, "demo.db", ["tasks"], 10)
        self.assertIn("## 核心候选资产覆盖", report)
        self.assertIn("候选资产数：**2**", report)
        self.assertIn("已同步表：**1/2 (50%)**", report)
        self.assertIn("dws_missing_candidate", report)
        self.assertIn("表未同步", report)


def _write_candidates(rows):
    fd, path = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    fields = ["asset_name", "layer", "domain", "owner", "use_case", "core_level", "value_tier", "reviewer", "reason", "metric_definition"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return path


if __name__ == "__main__":
    unittest.main()
