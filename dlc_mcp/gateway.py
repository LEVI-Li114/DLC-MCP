import argparse
import json
import os
import sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer

from .assets import AssetStore
from .live import LiveWeData
from .mcp import handle_request
from .server import _load_env_file


def main():
    _load_env_file(os.environ.get("DLC_MCP_ENV_FILE", "/etc/dlc-mcp/env"))
    parser = argparse.ArgumentParser(description="Run DLC-MCP HTTP gateway.")
    parser.add_argument("--host", default=os.environ.get("DLC_MCP_GATEWAY_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("DLC_MCP_GATEWAY_PORT", "8787")))
    args = parser.parse_args()

    db_path = os.environ.get("DLC_MCP_DB", "data/assets.db")
    store = AssetStore(sqlite3.connect(db_path))
    store.init_schema()
    live = LiveWeData(store) if _has_live_env() else None
    handler = _handler(store, live)
    HTTPServer((args.host, args.port), handler).serve_forever()


def _has_live_env():
    return os.environ.get("TENCENTCLOUD_SECRET_ID") and os.environ.get("TENCENTCLOUD_SECRET_KEY") and os.environ.get("WEDATA_PROJECT_ID")


def _handler(store, live):
    token = os.environ.get("DLC_MCP_GATEWAY_TOKEN", "")

    class GatewayHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/health":
                self.send_error(404)
                return
            self._json({"ok": True})

        def do_POST(self):
            if self.path != "/mcp":
                self.send_error(404)
                return
            if token and not _authorized(self.headers, token):
                self.send_error(401)
                return
            length = int(self.headers.get("content-length") or 0)
            request = json.loads(self.rfile.read(length) or b"{}")
            response = handle_request(store, request, live)
            if response is None:
                self.send_response(204)
                self.end_headers()
                return
            self._json(response)

        def log_message(self, *_args):
            return

        def _json(self, data):
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "application/json; charset=utf-8")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return GatewayHandler


def _authorized(headers, token):
    auth = headers.get("authorization", "")
    return auth == f"Bearer {token}" or headers.get("x-dlc-mcp-token", "") == token


if __name__ == "__main__":
    main()
