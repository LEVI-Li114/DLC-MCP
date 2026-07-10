import os
import sqlite3
import unittest
from tempfile import TemporaryDirectory

from dlc_mcp.assets import AssetStore
from dlc_mcp.validate_core_assets import main, render_core_asset_validation


class ValidateCoreAssetsTest(unittest.TestCase):
    def _store(self):
        store = AssetStore(sqlite3.connect(":memory:"))
        store.init_schema()
        return store

    def test_render_core_asset_validation_contains_profile_quality_production_and_issues(self):
        store = self._store()
        store.upsert_table({"name": "ads_revenue", "layer": "ads", "owner": "finance"})
        store.upsert_column("ads_revenue", "amount", "decimal", "", 1)
        store.upsert_expert_label({"asset_name": "ads_revenue", "core_level": "P1", "value_tier": "L1", "owner": "finance"})

        report = render_core_asset_validation(store, limit=20)

        self.assertIn("# 核心候选资产端到端验收报告", report)
        self.assertIn("## ads_revenue", report)
        self.assertIn("画像完整度", report)
        self.assertIn("核心判断", report)
        self.assertIn("质量状态", report)
        self.assertIn("生产状态", report)
        self.assertIn("风险解释", report)
        self.assertIn("当前缺口", report)
        self.assertIn("建议动作", report)

    def test_cli_writes_output_file(self):
        with TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "assets.db")
            output_path = os.path.join(tmpdir, "core_asset_validation.md")
            store = AssetStore(sqlite3.connect(db_path))
            store.init_schema()
            store.upsert_table({"name": "ads_revenue", "layer": "ads"})
            store.upsert_expert_label({"asset_name": "ads_revenue", "core_level": "P1", "value_tier": "L1"})

            main(["--db", db_path, "--limit", "20", "--output", output_path])

            self.assertTrue(os.path.exists(output_path))
            text = open(output_path, encoding="utf-8").read()
            self.assertIn("ads_revenue", text)
