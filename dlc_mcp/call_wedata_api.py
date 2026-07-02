import argparse
import json

from .tencentcloud import TencentCloudClient


def main():
    parser = argparse.ArgumentParser(description="Call a Tencent Cloud WeData API action.")
    parser.add_argument("action")
    parser.add_argument("payload", nargs="?", default="{}")
    args = parser.parse_args()
    response = TencentCloudClient.wedata_from_env().call(args.action, json.loads(args.payload))
    print(json.dumps(response, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
