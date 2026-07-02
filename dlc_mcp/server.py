import json
import os
import sqlite3
import sys

from .assets import AssetStore
from .mcp import handle_request


def main():
    db_path = os.environ.get("DLC_MCP_DB", "data/assets.db")
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(db_path)
    store = AssetStore(conn)
    store.init_schema()

    for line in sys.stdin:
        if not line.strip():
            continue
        response = handle_request(store, json.loads(line))
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
