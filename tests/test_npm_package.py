import json
import os
import unittest


class NpmPackageTest(unittest.TestCase):
    def test_package_exposes_mcp_bin(self):
        with open("package.json", "r", encoding="utf-8") as f:
            package = json.load(f)

        self.assertEqual(package["bin"]["dlc-mcp"], "bin/dlc-mcp.js")
        self.assertTrue(os.path.exists("bin/dlc-mcp.js"))

    def test_launcher_has_shared_defaults(self):
        with open("bin/dlc-mcp.js", "r", encoding="utf-8") as f:
            script = f.read()

        self.assertIn('"data-agent-host"', script)
        self.assertIn('"/opt/dlc-mcp"', script)
        self.assertIn('"/data/dlc-mcp/assets.db"', script)
        self.assertIn('"python3"', script)


if __name__ == "__main__":
    unittest.main()
