import datetime
import hashlib
import hmac
import json
import os
import urllib.request


class TencentCloudClient:
    def __init__(self, secret_id, secret_key, service, version, region, endpoint=None, opener=None):
        self.secret_id = secret_id
        self.secret_key = secret_key
        self.service = service
        self.version = version
        self.region = region
        self.endpoint = endpoint or f"{service}.tencentcloudapi.com"
        self.opener = opener or urllib.request.urlopen

    @classmethod
    def wedata_from_env(cls):
        missing = [name for name in ("TENCENTCLOUD_SECRET_ID", "TENCENTCLOUD_SECRET_KEY") if not os.environ.get(name)]
        if missing:
            raise RuntimeError("missing environment variables: " + ", ".join(missing))
        return cls(
            secret_id=os.environ["TENCENTCLOUD_SECRET_ID"],
            secret_key=os.environ["TENCENTCLOUD_SECRET_KEY"],
            service="wedata",
            version=os.environ.get("WEDATA_VERSION", "2025-08-06"),
            region=os.environ.get("TENCENTCLOUD_REGION", "ap-guangzhou"),
            endpoint=os.environ.get("WEDATA_ENDPOINT"),
        )

    def call(self, action, payload):
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        now = datetime.datetime.utcnow()
        timestamp = int(now.timestamp())
        date = now.strftime("%Y-%m-%d")
        headers = self._headers(action, body, timestamp, date)
        request = urllib.request.Request(f"https://{self.endpoint}", data=body, headers=headers, method="POST")
        with self.opener(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))

    def _headers(self, action, body, timestamp, date):
        authorization = self._authorization(body, timestamp, date)
        return {
            "Authorization": authorization,
            "Content-Type": "application/json; charset=utf-8",
            "Host": self.endpoint,
            "X-TC-Action": action,
            "X-TC-Version": self.version,
            "X-TC-Timestamp": str(timestamp),
            "X-TC-Region": self.region,
        }

    def _authorization(self, body, timestamp, date):
        algorithm = "TC3-HMAC-SHA256"
        canonical_request = "\n".join(
            [
                "POST",
                "/",
                "",
                f"content-type:application/json; charset=utf-8\nhost:{self.endpoint}\n",
                "content-type;host",
                hashlib.sha256(body).hexdigest(),
            ]
        )
        credential_scope = f"{date}/{self.service}/tc3_request"
        string_to_sign = "\n".join(
            [
                algorithm,
                str(timestamp),
                credential_scope,
                hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
            ]
        )
        secret_date = _hmac(("TC3" + self.secret_key).encode("utf-8"), date)
        secret_service = _hmac(secret_date, self.service)
        secret_signing = _hmac(secret_service, "tc3_request")
        signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"{algorithm} Credential={self.secret_id}/{credential_scope}, SignedHeaders=content-type;host, Signature={signature}"


def _hmac(key, msg):
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()
