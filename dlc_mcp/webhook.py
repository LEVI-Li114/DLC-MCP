import argparse
import json
import os
import re
import sqlite3
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer

from .assets import AssetStore
from .server import _load_env_file


def handle_alarm(store, payload):
    content = "\n".join(str(payload.get(key) or "") for key in ("Content", "AlarmInfo"))
    task_name = _extract_labeled(content, ("任务名称", "任务名", "TaskName"))
    alert_id = str(uuid.uuid4())
    recipient = payload.get("UserName") or ""
    store.enqueue_wedata_alert(alert_id, payload, task_name, recipient)
    return {"status": "accepted", "alert_id": alert_id, "task_name": task_name, "alert_recipient": recipient}


def _extract_labeled(text, labels):
    for label in labels:
        match = re.search(rf"(?:{re.escape(label)})\s*[:：=]\s*([^\r\n,，;；]+)", text, re.IGNORECASE)
        if match:
            value = match.group(1).strip().strip(" '\"“”")
            task_match = re.search(r"(?<![\w.-])(?:dwd|dws|dim|ods|ads|mid)_[A-Za-z0-9_]+", value, re.IGNORECASE)
            return task_match.group(0) if task_match else value
    match = re.search(r"(?<![\w.-])(?:dwd|dws|dim|ods|ads|mid)_[A-Za-z0-9_]+", text, re.IGNORECASE)
    return match.group(0) if match else ""


def _handler(store):
    token = os.environ.get("WEDATA_WEBHOOK_TOKEN", "")

    class WebhookHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/health":
                self.send_error(404)
                return
            self._json(200, {"ok": True})

        def do_POST(self):
            if self.path != "/wedata/alarm":
                self.send_error(404)
                return
            if token and self.headers.get("authorization", "") != f"Bearer {token}":
                self.send_error(401)
                return
            try:
                length = int(self.headers.get("content-length") or 0)
                payload = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(payload, dict):
                    raise ValueError("JSON body must be an object")
                self._json(202, handle_alarm(store, payload))
            except json.JSONDecodeError as exc:
                self._json(400, {"status": "invalid_request", "error": str(exc)})
            except ValueError as exc:
                self._json(400, {"status": "invalid_request", "error": str(exc)})
            except Exception as exc:
                self._json(502, {"status": "processing_failed", "error": str(exc)})

        def _json(self, status, data):
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", "application/json; charset=utf-8")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            return

    return WebhookHandler


def main():
    _load_env_file(os.environ.get("DLC_MCP_ENV_FILE", "/etc/dlc-mcp/env"))
    parser = argparse.ArgumentParser(description="Run the WeData alarm webhook receiver.")
    parser.add_argument("--host", default=os.environ.get("WEDATA_WEBHOOK_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("WEDATA_WEBHOOK_PORT", "8788")))
    args = parser.parse_args()
    db_path = os.environ.get("DLC_MCP_DB", "data/assets.db")
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    store = AssetStore(sqlite3.connect(db_path))
    store.init_schema()
    HTTPServer((args.host, args.port), _handler(store)).serve_forever()


if __name__ == "__main__":
    main()
