import json
import os
import sqlite3
import sys

from .assets import AssetStore
from .live import LiveWeData
from .mcp import handle_request


def main():
    _load_env_file(os.environ.get("DLC_MCP_ENV_FILE", "/etc/dlc-mcp/env"))
    db_path = os.environ.get("DLC_MCP_DB", "data/assets.db")
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(db_path)
    store = AssetStore(conn)
    store.init_schema()
    live = LiveWeData(store) if os.environ.get("TENCENTCLOUD_SECRET_ID") and os.environ.get("TENCENTCLOUD_SECRET_KEY") and os.environ.get("WEDATA_PROJECT_ID") else None

    for line in sys.stdin:
        if not line.strip():
            continue
        response = handle_request(store, json.loads(line), live)
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()


def _load_env_file(path):
    if not path or not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


if __name__ == "__main__":
    main()
