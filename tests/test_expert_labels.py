import json
import os
import sqlite3
import tempfile
import unittest

from dlc_mcp.assets import AssetStore
from dlc_mcp.import_expert_labels import _load_labels


class ExpertLabelsTest(unittest.TestCase):
    def test_loads_json_labels(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump({"labels": [{"asset_name": "dwd_sms_bill", "core_level": "P0"}]}, f)
            path = f.name
        try:
            self.assertEqual(_load_labels(path)[0]["asset_name"], "dwd_sms_bill")
        finally:
            os.unlink(path)

    def test_store_reads_expert_label(self):
        store = AssetStore(sqlite3.connect(":memory:"))
        store.init_schema()
        store.upsert_expert_label({"asset_name": "dwd_sms_bill", "core_level": "P0"})

        self.assertEqual(store.get_expert_label("table", "dwd_sms_bill")["core_level"], "P0")


if __name__ == "__main__":
    unittest.main()
