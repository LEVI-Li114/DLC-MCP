import argparse
import csv
import os
import sqlite3
from datetime import date

from .assets import AssetStore
from .server import _load_env_file


FIELDS = ["asset_name", "layer", "domain", "owner", "use_case", "core_level", "value_tier", "reviewer", "reason", "metric_definition"]


def main():
    parser = argparse.ArgumentParser(description="Import core asset candidates into the DLC-MCP expert label table.")
    parser.add_argument("path", help="CSV file with core asset candidates.")
    parser.add_argument("--db", default="", help="SQLite asset database path. Defaults to DLC_MCP_DB or data/assets.db.")
    parser.add_argument("--env-file", default=os.environ.get("DLC_MCP_ENV_FILE", "/etc/dlc-mcp/env"), help="Optional env file to load before importing.")
    args = parser.parse_args()

    if args.env_file and os.path.exists(args.env_file):
        _load_env_file(args.env_file)
    db_path = args.db or os.environ.get("DLC_MCP_DB", "data/assets.db")
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)

    store = AssetStore(sqlite3.connect(db_path))
    store.init_schema()
    count = import_core_candidates(store, args.path)
    print(f"imported {count} core asset candidates into {db_path}")


def import_core_candidates(store, path):
    count = 0
    for item in load_core_candidates(path):
        store.upsert_expert_label(item)
        count += 1
    return count


def load_core_candidates(path):
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return [_candidate_to_label(row) for row in rows if (row.get("asset_name") or "").strip()]


def _candidate_to_label(row):
    item = {key: (row.get(key) or "").strip() for key in FIELDS}
    return {
        "asset_type": "table",
        "asset_name": item["asset_name"],
        "core_level": item["core_level"],
        "value_tier": item["value_tier"],
        "domain": item["domain"],
        "use_case": item["use_case"],
        "metric_definition": item["metric_definition"],
        "owner": item["owner"],
        "reviewer": item["reviewer"],
        "reason": _reason_with_layer(item["reason"], item["layer"]),
        "updated_at": date.today().isoformat(),
    }


def _reason_with_layer(reason, layer):
    if not layer:
        return reason
    if reason:
        return f"{reason}; layer={layer}"
    return f"layer={layer}"


if __name__ == "__main__":
    main()
