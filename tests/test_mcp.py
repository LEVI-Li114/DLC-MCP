import sqlite3
import unittest

from dlc_agent.assets import AssetStore
from dlc_agent.mcp import handle_request


class McpTest(unittest.TestCase):
    def setUp(self):
        conn = sqlite3.connect(":memory:")
        self.store = AssetStore(conn)
        self.store.init_schema()
        self.store.upsert_table(
            {
                "name": "dim_customer",
                "database": "dw",
                "layer": "dim",
                "domain": "customer",
                "owner": "data-customer",
                "description": "Customer dimension",
            }
        )
        self.store.upsert_column("dim_customer", "customer_id", "string", "Customer ID", 1)
        self.store.upsert_task(
            {
                "id": "task_001",
                "name": "build_dim_customer",
                "task_type": "32",
                "cycle": "DAY",
                "owner": "100043939904",
                "status": "Y11",
                "outputs": ["dim_customer"],
            }
        )
        self.store.upsert_task_run(
            {
                "task_id": "task_001",
                "instance_id": "inst_001",
                "instance_date": "2026-07-01",
                "start_time": "2026-07-01 08:00:00",
                "end_time": "2026-07-01 08:05:00",
                "duration_seconds": 300,
                "status": "success",
            }
        )
        self.store.upsert_data_source(
            {
                "id": "ds_001",
                "name": "mysql_prod",
                "type": "mysql",
                "owner": "data-platform",
                "description": "Production MySQL",
                "config": {"host": "mysql.internal", "database": "crm"},
            }
        )

    def test_lists_tools(self):
        response = handle_request(self.store, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

        self.assertEqual(response["id"], 1)
        self.assertIn("get_table_profile", [tool["name"] for tool in response["result"]["tools"]])
        self.assertIn("search_tasks", [tool["name"] for tool in response["result"]["tools"]])
        self.assertIn("list_data_sources", [tool["name"] for tool in response["result"]["tools"]])
        self.assertIn("list_metadata", [tool["name"] for tool in response["result"]["tools"]])

    def test_calls_table_profile_tool(self):
        response = handle_request(
            self.store,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "get_table_profile", "arguments": {"table_name": "dim_customer"}},
            },
        )

        self.assertEqual(response["result"]["content"][0]["type"], "text")
        self.assertIn("dim_customer", response["result"]["content"][0]["text"])

    def test_calls_search_tasks_tool(self):
        response = handle_request(
            self.store,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "search_tasks", "arguments": {"query": "customer"}},
            },
        )

        self.assertIn("build_dim_customer", response["result"]["content"][0]["text"])

    def test_calls_get_task_runs_tool(self):
        response = handle_request(
            self.store,
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "get_task_runs", "arguments": {"task_id": "task_001"}},
            },
        )

        self.assertIn("duration_seconds", response["result"]["content"][0]["text"])

    def test_calls_get_task_runs_by_name_and_date(self):
        response = handle_request(
            self.store,
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {
                    "name": "get_task_runs",
                    "arguments": {"task_name": "build_dim_customer", "instance_date": "2026-07-01"},
                },
            },
        )

        text = response["result"]["content"][0]["text"]
        self.assertIn("build_dim_customer", text)
        self.assertIn("duration_seconds", text)

    def test_calls_data_source_tools(self):
        response = handle_request(
            self.store,
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {"name": "get_data_source", "arguments": {"data_source_id": "ds_001"}},
            },
        )

        self.assertIn("mysql.internal", response["result"]["content"][0]["text"])

    def test_calls_metadata_tool(self):
        response = handle_request(
            self.store,
            {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "list_metadata", "arguments": {}}},
        )

        self.assertIn("dim_customer", response["result"]["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
