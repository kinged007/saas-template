"""S3-compatible driver over stdlib-signed HTTP (no new dependencies).

PUT/GET/DELETE against <endpoint>/<bucket>/<key> with SigV4 authorization,
issued with httpx (already a dependency). Unit-testable by injecting a
custom httpx transport; production points at S3 or a compatible store.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import quote

import httpx

from src.storage.base import FileStorage, StorageError, StoredObject


@dataclass
class S3Config:
    endpoint: str = ""
    bucket: str = ""
    region: str = "us-east-1"
    access_key: str = ""
    secret_key: str = ""
    timeout_s: float = 10.0


def _sign_v4(
    *,
    secret_key: str,
    region: str,
    service: str,
    amz_date: str,
    date_stamp: str,
    string_to_sign: str,
) -> str:
    def _h(k: bytes, msg: str) -> bytes:
        return hmac.new(k, msg.encode(), hashlib.sha256).digest()

    scope = f"{date_stamp}/{region}/{service}/aws4_request"
    k = _h(("AWS4" + secret_key).encode(), date_stamp)
    k = _h(k, region)
    k = _h(k, service)
    k = _h(k, "aws4_request")
    return hmac.new(k, string_to_sign.encode(), hashlib.sha256).hexdigest() + f"::{scope}"


class S3FileStorage(FileStorage):
    name = "s3"

    def __init__(self, config: S3Config, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.config = config
        self._transport = transport

    def _url(self, key: str) -> str:
        return f"{self.config.endpoint.rstrip('/')}/{self.config.bucket}/{quote(key, safe='/')}"

    def _auth_headers(
        self, *, method: str, key: str, payload_hash: str, content_type: str | None
    ) -> dict[str, str]:
        now = datetime.now(UTC)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")
        host = self._url(key).split("://", 1)[1].split("/", 1)[0]
        headers = {"host": host, "x-amz-date": amz_date, "x-amz-content-sha256": payload_hash}
        if content_type:
            headers["content-type"] = content_type
        signed = ";".join(sorted(headers))
        canonical = "\n".join(
            [
                method,
                f"/{self.config.bucket}/{quote(key, safe='/')}",
                "",
                "".join(f"{k}:{headers[k]}\n" for k in sorted(headers)),
                signed,
                payload_hash,
            ]
        )
        scope = f"{date_stamp}/{self.config.region}/s3/aws4_request"
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        to_sign = f"AWS4-HMAC-SHA256\n{amz_date}\n{scope}\n{digest}"
        sig_with_scope = _sign_v4(
            secret_key=self.config.secret_key,
            region=self.config.region,
            service="s3",
            amz_date=amz_date,
            date_stamp=date_stamp,
            string_to_sign=to_sign,
        )
        signature = sig_with_scope.split("::")[0]
        headers["Authorization"] = (
            f"AWS4-HMAC-SHA256 Credential={self.config.access_key}/{scope}, "
            f"SignedHeaders={signed}, Signature={signature}"
        )
        return headers

    async def _request(self, method: str, key: str, **kwargs) -> httpx.Response:
        try:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=self.config.timeout_s
            ) as client:
                return await client.request(method, self._url(key), **kwargs)
        except StorageError:
            raise
        except Exception as exc:
            raise StorageError(f"s3 {method} failed: {exc}") from exc

    async def put(self, *, key: str, content: bytes, content_type: str | None = None) -> None:
        payload_hash = hashlib.sha256(content).hexdigest()
        headers = self._auth_headers(
            method="PUT", key=key, payload_hash=payload_hash, content_type=content_type
        )
        resp = await self._request("PUT", key, content=content, headers=headers)
        if resp.status_code not in (200, 201, 204):
            raise StorageError(f"s3 put failed: HTTP {resp.status_code}")

    async def get(self, *, key: str) -> StoredObject | None:
        headers = self._auth_headers(
            method="GET", key=key, payload_hash="UNSIGNED-PAYLOAD", content_type=None
        )
        resp = await self._request("GET", key, headers=headers)
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise StorageError(f"s3 get failed: HTTP {resp.status_code}")
        return StoredObject(
            key=key, content=resp.content, content_type=resp.headers.get("content-type")
        )

    async def delete(self, *, key: str) -> None:
        headers = self._auth_headers(
            method="DELETE", key=key, payload_hash="UNSIGNED-PAYLOAD", content_type=None
        )
        resp = await self._request("DELETE", key, headers=headers)
        if resp.status_code not in (200, 202, 204, 404):
            raise StorageError(f"s3 delete failed: HTTP {resp.status_code}")

    async def exists(self, *, key: str) -> bool:
        headers = self._auth_headers(
            method="HEAD", key=key, payload_hash="UNSIGNED-PAYLOAD", content_type=None
        )
        resp = await self._request("HEAD", key, headers=headers)
        if resp.status_code == 200:
            return True
        if resp.status_code == 404:
            return False
        raise StorageError(f"s3 head failed: HTTP {resp.status_code}")
