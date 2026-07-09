from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DeployScriptsTest(unittest.TestCase):
    def test_sync_cron_installer_runs_managed_sync_at_five(self):
        script = (ROOT / "deploy" / "install-sync-cron.sh").read_text()

        self.assertIn("0 5 * * *", script)
        self.assertIn("dlc-mcp-wedata-sync", script)
        self.assertIn("deploy/sync-wedata-managed.sh", script)
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
            "DLC_MCP_SYNC_MODE",
            "DLC_MCP_DAILY_NEW_ASSET_STRICT",
            "DLC_MCP_MONTHLY_METADATA_TABLE_LIMIT",
            "DLC_MCP_GATEWAY_TOKEN",
        ]:
            self.assertIn(key, env)

    def test_managed_sync_controls_daily_and_monthly_modes(self):
        script = (ROOT / "deploy" / "sync-wedata-managed.sh").read_text()

        self.assertIn("DLC_MCP_SYNC_MODE", script)
        self.assertIn("TOMORROW_DAY", script)
        self.assertIn("MODE=\"monthly\"", script)
        self.assertIn("MODE=\"daily\"", script)
        self.assertIn("WEDATA_NEW_ASSET_START", script)
        self.assertIn("WEDATA_NEW_ASSET_END", script)
        self.assertIn("WEDATA_SYNC_PARTITIONS", script)
        self.assertIn("WEDATA_PARTITION_DATE", script)
        self.assertIn("WEDATA_INSTANCE_START", script)
        self.assertIn("deploy/sync-wedata-once.sh", script)

    def test_full_field_sync_script_is_field_only_and_reports_elapsed_time(self):
        script = (ROOT / "deploy" / "sync-all-table-fields.sh").read_text()

        self.assertIn("dlc_mcp.sync_table_fields", script)
        self.assertIn("elapsed_seconds", script)
        self.assertNotIn("sync_wedata", script)

    def test_full_asset_facts_sync_script_reports_elapsed_time(self):
        script = (ROOT / "deploy" / "sync-all-asset-facts.sh").read_text()

        self.assertIn("dlc_mcp.sync_asset_facts", script)
        self.assertIn("elapsed_seconds", script)

    def test_sync_script_runs_health_coverage_and_gap_checks(self):
        script = (ROOT / "deploy" / "sync-wedata-once.sh").read_text()

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

    def test_core_table_pilot_script_scopes_single_table_sync(self):
        script = (ROOT / "deploy" / "sync-core-table-pilot.sh").read_text()

        self.assertIn("DLC_MCP_CORE_TABLE_PILOT", script)
        self.assertIn("ads_bill_company_1d_di", script)
        self.assertIn("WEDATA_METADATA_TABLES=\"$PILOT_TABLE\"", script)
        self.assertIn("WEDATA_METADATA_TABLE_LIMIT=1", script)
        self.assertIn("WEDATA_METADATA_WORKERS=1", script)
        self.assertIn("WEDATA_INSTANCE_KEYWORDS=\"$PILOT_TABLE\"", script)
        self.assertIn("dlc_mcp.import_core_candidates", script)
        self.assertIn("dlc_mcp.sync_wedata", script)
        self.assertIn("dlc_mcp.check_foundation", script)
        self.assertIn("get_table_profile", script)
