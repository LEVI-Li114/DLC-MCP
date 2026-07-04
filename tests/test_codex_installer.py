import os
import subprocess
import tempfile
import unittest
from pathlib import Path


class CodexInstallerTest(unittest.TestCase):
    def test_install_codex_appends_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            config = home / ".codex" / "config.toml"

            self.run_installer(home)
            self.run_installer(home)

            text = config.read_text(encoding="utf-8")
            self.assertEqual(text.count("[mcp_servers.dlc-mcp]"), 1)
            self.assertIn('command = "npx"', text)
            self.assertIn('args = ["-y", "@levisli/dlc-mcp"]', text)
            self.assertIn('type = "stdio"', text)

    def test_install_codex_replaces_existing_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            config = home / ".codex" / "config.toml"
            config.parent.mkdir()
            config.write_text(
                '[mcp_servers.dlc-mcp]\ncommand = "old"\n\n[mcp_servers.other]\ncommand = "ok"\n',
                encoding="utf-8",
            )

            self.run_installer(home)

            text = config.read_text(encoding="utf-8")
            self.assertNotIn('command = "old"', text)
            self.assertIn("[mcp_servers.other]", text)
            self.assertEqual(text.count("[mcp_servers.dlc-mcp]"), 1)

    def run_installer(self, home):
        result = subprocess.run(
            ["node", "bin/dlc-mcp.js", "install-codex"],
            cwd=Path(__file__).resolve().parents[1],
            env={**os.environ, "HOME": str(home)},
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
