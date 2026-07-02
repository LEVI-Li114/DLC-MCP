import argparse

from .wedata import import_snapshot_file


def main():
    parser = argparse.ArgumentParser(description="Import a WeData JSON snapshot into the asset fact database.")
    parser.add_argument("snapshot")
    parser.add_argument("--db", default="data/assets.db")
    args = parser.parse_args()
    print(import_snapshot_file(args.db, args.snapshot))


if __name__ == "__main__":
    main()
