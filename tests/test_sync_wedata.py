import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from dlc_mcp.sync_wedata import _instance_window


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


if __name__ == "__main__":
    unittest.main()
