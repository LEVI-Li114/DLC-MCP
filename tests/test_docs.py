import unittest

from dlc_mcp.mcp import TOOLS


class DocsTest(unittest.TestCase):
    def test_readme_lists_all_mcp_tools(self):
        with open("README.md", "r", encoding="utf-8") as f:
            readme = f.read()

        for name in TOOLS:
            self.assertIn(f"`{name}", readme)

    def test_readme_links_architecture_doc(self):
        with open("README.md", "r", encoding="utf-8") as f:
            readme = f.read()

        self.assertIn("docs/architecture.md", readme)

    def test_architecture_doc_defines_project_layers(self):
        with open("docs/architecture.md", "r", encoding="utf-8") as f:
            architecture = f.read()

        for phrase in (
            "MCP Tools layer",
            "Live Connector layer",
            "Asset Store layer",
            "Sync Jobs / Admin Ops layer",
            "Do not bypass MCP tools",
            "SQLite is not the source of truth",
        ):
            self.assertIn(phrase, architecture)

    def test_architecture_doc_requires_cloud_api_catalog(self):
        with open("docs/architecture.md", "r", encoding="utf-8") as f:
            architecture = f.read()

        self.assertIn("cloud_api_catalog", architecture)
        self.assertIn("TENCENT_CLOUD_API_CATALOG", architecture)
        self.assertIn("Do not add an API call without cataloging", architecture)

    def test_agents_file_keeps_query_and_ops_boundary(self):
        with open("AGENTS.md", "r", encoding="utf-8") as f:
            agents = f.read()

        self.assertIn("查数据：走 `dlc-mcp` MCP server", agents)
        self.assertIn("部署、补数、重启、查日志：走 `ssh`", agents)
        self.assertIn("普通数据查询不要绕过 MCP tools", agents)


if __name__ == "__main__":
    unittest.main()
