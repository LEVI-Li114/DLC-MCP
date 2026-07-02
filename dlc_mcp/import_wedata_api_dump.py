import argparse
import json
import os
import sqlite3

from .assets import AssetStore
from .wedata import import_wedata_snapshot, snapshot_from_api_dump


def main():
    parser = argparse.ArgumentParser(description="Import saved WeData API responses into the asset fact database.")
    parser.add_argument("--tables")
    parser.add_argument("--tasks")
    parser.add_argument("--lineage")
    parser.add_argument("--quality-rules")
    parser.add_argument("--db", default="data/assets.db")
    args = parser.parse_args()

    dump = {
        "tables": _load(args.tables),
        "tasks": _load(args.tasks),
        "lineage": _load(args.lineage),
        "quality_rules": _load(args.quality_rules),
    }
    os.makedirs(os.path.dirname(args.db) or ".", exist_ok=True)
    store = AssetStore(sqlite3.connect(args.db))
    store.init_schema()
    import_wedata_snapshot(store, snapshot_from_api_dump(dump))
    print(args.db)


def _load(path):
    if not path:
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    main()
