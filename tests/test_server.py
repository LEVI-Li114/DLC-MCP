import os
import tempfile
import unittest

from dlc_mcp.server import _load_env_file


class ServerTest(unittest.TestCase):
    def test_load_env_file_fills_missing_values_only(self):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as f:
            f.write("WEDATA_PROJECT_ID=from_file\n")
            f.write('DLC_MCP_DB="/tmp/assets.db"\n')
            f.flush()

            old_project = os.environ.get("WEDATA_PROJECT_ID")
            old_db = os.environ.get("DLC_MCP_DB")
            try:
                os.environ["WEDATA_PROJECT_ID"] = "existing"
                os.environ.pop("DLC_MCP_DB", None)

                _load_env_file(f.name)

                self.assertEqual(os.environ["WEDATA_PROJECT_ID"], "existing")
                self.assertEqual(os.environ["DLC_MCP_DB"], "/tmp/assets.db")
            finally:
                _restore_env("WEDATA_PROJECT_ID", old_project)
                _restore_env("DLC_MCP_DB", old_db)


def _restore_env(key, value):
    if value is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
