import unittest

from dlc_mcp.mcp import TOOLS


class DocsTest(unittest.TestCase):
    def test_readme_lists_all_mcp_tools(self):
        with open("README.md", "r", encoding="utf-8") as f:
            readme = f.read()

        for name in TOOLS:
            self.assertIn(f"`{name}", readme)


if __name__ == "__main__":
    unittest.main()
