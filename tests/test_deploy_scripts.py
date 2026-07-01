from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DeployScriptsTest(unittest.TestCase):
    def test_sync_cron_installer_runs_every_ten_minutes(self):
        script = (ROOT / "deploy" / "install-sync-cron.sh").read_text()

        self.assertIn("*/10 * * * *", script)
        self.assertIn("dlc-agent-wedata-sync", script)
        self.assertIn("deploy/sync-wedata-once.sh", script)
        self.assertIn("DLC_AGENT_REPO_DIR", script)
        self.assertIn("DLC_AGENT_LOG_DIR", script)
