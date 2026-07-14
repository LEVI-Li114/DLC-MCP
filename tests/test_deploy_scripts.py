from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DeployScriptsTest(unittest.TestCase):
    def test_sync_cron_installer_runs_managed_sync_at_eight(self):
        script = (ROOT / "deploy" / "install-sync-cron.sh").read_text()

        self.assertIn("0 8 * * *", script)
        self.assertIn("dlc-mcp-wedata-sync", script)
        self.assertIn("deploy/sync-wedata-incremental.sh", script)
        self.assertIn("DLC_MCP_REPO_DIR", script)
        self.assertIn("DLC_MCP_LOG_DIR", script)

    def test_env_example_documents_foundation_sync_config(self):
        env = (ROOT / "deploy" / "env.example").read_text()

        for key in [
            "DLC_MCP_SYNC_DIR",
            "DLC_MCP_PYTHON",
            "WEDATA_PAGE_SIZE",
            "WEDATA_SYNC_TABLE_CATALOG",
            "WEDATA_METADATA_WORKERS",
            "WEDATA_FULL_FIELDS_REQUEST_INTERVAL",
            "WEDATA_FULL_FIELDS_MAX_RETRIES",
            "WEDATA_SYNC_DATA_SOURCES",
            "WEDATA_SYNC_PARTITIONS",
            "WEDATA_PARTITION_ACTION",
            "WEDATA_INSTANCE_TIMEZONE",
            "DLC_MCP_SYNC_HEALTH_CHECK",
            "DLC_MCP_SYNC_GAP_TYPES",
            "DLC_MCP_SYNC_GAP_LIMIT",
            "DLC_MCP_DAILY_NEW_ASSET_STRICT",
            "DLC_MCP_GATEWAY_TOKEN",
        ]:
            self.assertIn(key, env)

        self.assertIn("WEDATA_FULL_FACTS_INSTANCE_LOOKBACK_DAYS=7", env)
        self.assertNotIn("DLC_MCP_MONTHLY_", env)

    def test_incremental_sync_uses_yesterday_window(self):
        script = (ROOT / "deploy" / "sync-wedata-incremental.sh").read_text()

        self.assertIn("YESTERDAY", script)
        self.assertIn("WEDATA_NEW_ASSET_START", script)
        self.assertIn("WEDATA_NEW_ASSET_END", script)
        self.assertIn("WEDATA_SYNC_PARTITIONS", script)
        self.assertIn("DLC_MCP_DAILY_SYNC_PARTITIONS:-1", script)
        self.assertIn("WEDATA_PARTITION_DATE", script)
        self.assertIn("WEDATA_NEW_ASSET_DATE_FIELDS", script)
        self.assertIn("metadata_date_fields", script)
        self.assertIn("metadata_table_limit", script)
        self.assertIn("sync_partitions", script)
        self.assertIn("partition_date", script)
        self.assertIn("elapsed_seconds", script)
        self.assertIn("finished_at", script)
        self.assertIn("sync_status", script)
        self.assertIn("dlc_mcp.sync_wedata", script)

    def test_full_sync_script_runs_facts_and_fields_once(self):
        script = (ROOT / "deploy" / "sync-wedata-full.sh").read_text()

        self.assertIn("dlc_mcp.sync_asset_facts", script)
        self.assertIn("dlc_mcp.sync_table_fields", script)
        self.assertIn("elapsed_seconds", script)
        self.assertIn("finished_at", script)
        self.assertIn("sync_status", script)
        self.assertNotIn("sync_wedata", script)

    def test_sync_script_runs_health_coverage_and_gap_checks(self):
        script = (ROOT / "deploy" / "sync-wedata-incremental.sh").read_text()

        self.assertIn("DLC_MCP_SYNC_HEALTH_CHECK", script)
        self.assertIn("dlc_mcp.check_foundation", script)
        self.assertIn("--gap-types", script)
        self.assertIn("--gap-limit", script)
        self.assertIn("DLC_MCP_SYNC_GAP_TYPES", script)
        self.assertIn("DLC_MCP_SYNC_GAP_LIMIT", script)
        self.assertNotIn("tools/call", script)

    def test_asset_foundation_check_script_runs_without_syncing(self):
        script = (ROOT / "deploy" / "check-asset-foundation.sh").read_text()

        self.assertIn("dlc_mcp.check_foundation", script)
        self.assertIn("--gap-types", script)
        self.assertIn("--gap-limit", script)
        self.assertIn("DLC_MCP_SYNC_GAP_TYPES", script)
        self.assertIn("DLC_MCP_DB", script)
        self.assertNotIn("sync_wedata", script)
        self.assertNotIn("jsonrpc", script.lower())

    def test_only_two_sync_entrypoints_remain(self):
        scripts = sorted(path.name for path in (ROOT / "deploy").glob("sync-*.sh"))

        self.assertEqual(scripts, ["sync-wedata-full.sh", "sync-wedata-incremental.sh"])
