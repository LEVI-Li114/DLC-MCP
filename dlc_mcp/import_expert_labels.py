import argparse
import csv
import json
import os
import sqlite3

from .assets import AssetStore


def main():
    parser = argparse.ArgumentParser(description="Import expert asset labels into the MCP database.")
    parser.add_argument("path")
    parser.add_argument("--db", default="data/assets.db")
    args = parser.parse_args()

    os.makedirs(os.path.dirname(args.db) or ".", exist_ok=True)
    store = AssetStore(sqlite3.connect(args.db))
    store.init_schema()
    count = 0
    for item in _load_labels(args.path):
        store.upsert_expert_label(item)
        count += 1
    print(f"imported {count} expert labels into {args.db}")


def _load_labels(path):
    if path.endswith(".csv"):
        with open(path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("labels", data) if isinstance(data, dict) else data


if __name__ == "__main__":
    main()
