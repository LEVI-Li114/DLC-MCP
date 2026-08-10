import sqlite3

from dlc_mcp.assets import AssetStore
from dlc_mcp.mcp import _call_tool, handle_request


class FakeService:
    def __init__(self):
        self.submissions = []

    def submit_partition_count_query(self, table_name, partition):
        self.submissions.append((table_name, partition))
        return {"query_id": "q-1", "table_name": "dw.orders", "partition": partition, "status": "SUBMITTED", "row_count": None}


def store():
    value = AssetStore(sqlite3.connect(":memory:"))
    value.init_schema()
    return value


def test_query_tools_are_listed_without_arbitrary_sql():
    result = handle_request(store(), {"id": 1, "method": "tools/list"})
    tools = {item["name"]: item for item in result["result"]["tools"]}
    assert "sql" not in tools["submit_partition_count_query"]["inputSchema"]["properties"]
    assert "query_id" in tools["get_partition_count_query"]["inputSchema"]["required"]


def test_submit_tool_delegates_to_query_service():
    service = FakeService()
    request = {"id": 1, "method": "tools/call", "params": {"name": "submit_partition_count_query", "arguments": {"table_name": "orders", "partition": {"ds": "2026-08-10"}}}}
    response = _call_tool(store(), request, query_service=service)
    assert response["result"]["content"][0]["type"] == "text"
    assert service.submissions == [("orders", {"ds": "2026-08-10"})]
