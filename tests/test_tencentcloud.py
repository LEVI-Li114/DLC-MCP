import json
import os
import unittest
from unittest.mock import patch

from dlc_mcp.tencentcloud import TencentCloudClient


class FakeOpener:
    def __init__(self):
        self.request = None

    def __call__(self, request, timeout):
        self.request = request
        return FakeResponse({"Response": {"RequestId": "rid-1", "Items": []}})


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class TencentCloudClientTest(unittest.TestCase):
    def test_calls_wedata_action_with_tc3_headers(self):
        opener = FakeOpener()
        client = TencentCloudClient(
            secret_id="sid",
            secret_key="skey",
            service="wedata",
            version="2025-08-06",
            region="ap-guangzhou",
            opener=opener,
        )

        response = client.call("ListTasks", {"ProjectId": "p1"})

        self.assertEqual(response["Response"]["RequestId"], "rid-1")
        self.assertEqual(opener.request.full_url, "https://wedata.tencentcloudapi.com")
        self.assertEqual(opener.request.headers["X-tc-action"], "ListTasks")
        self.assertEqual(opener.request.headers["X-tc-version"], "2025-08-06")
        self.assertEqual(opener.request.headers["X-tc-region"], "ap-guangzhou")
        self.assertIn("TC3-HMAC-SHA256", opener.request.headers["Authorization"])
        self.assertEqual(json.loads(opener.request.data.decode("utf-8")), {"ProjectId": "p1"})

    def test_builds_dlc_client_from_environment(self):
        with patch.dict(
            os.environ,
            {
                "TENCENTCLOUD_SECRET_ID": "sid",
                "TENCENTCLOUD_SECRET_KEY": "skey",
                "TENCENTCLOUD_REGION": "ap-shanghai",
                "DLC_API_VERSION": "2021-01-25",
            },
            clear=False,
        ):
            client = TencentCloudClient.dlc_from_env()

        self.assertEqual(client.service, "dlc")
        self.assertEqual(client.endpoint, "dlc.tencentcloudapi.com")
        self.assertEqual(client.version, "2021-01-25")
        self.assertEqual(client.region, "ap-shanghai")


if __name__ == "__main__":
    unittest.main()
