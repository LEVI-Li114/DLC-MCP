from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DeployScriptsTest(unittest.TestCase):
    def test_sync_cron_installer_runs_every_six_hours(self):
        script = (ROOT / "deploy" / "install-sync-cron.sh").read_text()

        self.assertIn("0 */6 * * *", script)
        self.assertIn("dlc-mcp-wedata-sync", script)
        self.assertIn("deploy/sync-wedata-once.sh", script)
        self.assertIn("DLC_MCP_REPO_DIR", script)
        self.assertIn("DLC_MCP_LOG_DIR", script)
