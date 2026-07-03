import json
import os
import sqlite3
import unittest
from io import BytesIO

from dlc_mcp.assets import AssetStore
from dlc_mcp.gateway import _handler


class GatewayTest(unittest.TestCase):
    def test_gateway_serves_health_and_mcp(self):
        store = AssetStore(sqlite3.connect(":memory:", check_same_thread=False))
        store.init_schema()
        handler = _handler(store, None)

        health = handler.__new__(handler)
        health.path = "/health"
        health._json = lambda data: setattr(health, "data", data)
        handler.do_GET(health)
        self.assertEqual(health.data, {"ok": True})

        body = b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
        mcp = handler.__new__(handler)
        mcp.path = "/mcp"
        mcp.headers = {"content-length": str(len(body))}
        mcp.rfile = BytesIO(body)
        mcp._json = lambda data: setattr(mcp, "data", data)
        handler.do_POST(mcp)
        self.assertEqual(mcp.data["id"], 1)
        self.assertIn("tools", mcp.data["result"])

    def test_gateway_token_rejects_missing_auth(self):
        old_token = os.environ.get("DLC_MCP_GATEWAY_TOKEN")
        try:
            os.environ["DLC_MCP_GATEWAY_TOKEN"] = "secret"
            store = AssetStore(sqlite3.connect(":memory:", check_same_thread=False))
            store.init_schema()
            handler = _handler(store, None)

            body = b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
            mcp = handler.__new__(handler)
            mcp.path = "/mcp"
            mcp.headers = {"content-length": str(len(body))}
            mcp.rfile = BytesIO(body)
            mcp.send_error = lambda code: setattr(mcp, "code", code)

            handler.do_POST(mcp)

            self.assertEqual(mcp.code, 401)
        finally:
            if old_token is None:
                os.environ.pop("DLC_MCP_GATEWAY_TOKEN", None)
            else:
                os.environ["DLC_MCP_GATEWAY_TOKEN"] = old_token


if __name__ == "__main__":
    unittest.main()
