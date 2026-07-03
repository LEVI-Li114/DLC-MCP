import json
import os
import unittest


class NpmPackageTest(unittest.TestCase):
    def test_package_exposes_mcp_bin(self):
        with open("package.json", "r", encoding="utf-8") as f:
            package = json.load(f)

        self.assertEqual(package["bin"]["dlc-mcp"], "bin/dlc-mcp.js")
        self.assertEqual(package["version"], "0.1.1")
        self.assertNotIn("private", package)
        self.assertEqual(package["publishConfig"]["access"], "public")
        self.assertTrue(os.path.exists("bin/dlc-mcp.js"))

    def test_launcher_has_gateway_defaults(self):
        with open("bin/dlc-mcp.js", "r", encoding="utf-8") as f:
            script = f.read()

        self.assertIn('"http://64.186.234.87:8787/mcp"', script)
        self.assertNotIn("DLC_MCP_SSH_HOST", script)
        self.assertNotIn("DLC_MCP_REMOTE_DIR", script)
        self.assertNotIn("spawn(\"ssh\"", script)

    def test_launcher_supports_http_gateway(self):
        with open("bin/dlc-mcp.js", "r", encoding="utf-8") as f:
            script = f.read()

        self.assertIn("DLC_MCP_GATEWAY_URL", script)
        self.assertIn("DLC_MCP_GATEWAY_TOKEN", script)
        self.assertIn("headers.authorization", script)
        self.assertIn("fetch(url", script)
        self.assertIn("[mcp_servers.dlc-mcp.env]", script)


if __name__ == "__main__":
    unittest.main()
