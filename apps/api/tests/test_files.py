"""File upload → store → authorized download (issue #18 acceptance).

Local driver e2e through the API; S3 driver contract via stubbed transport;
limits + workspace isolation.
"""

from __future__ import annotations

import asyncio
import io
from pathlib import Path

import pytest

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
# sha256(b"img-bytes") — the payload hash the S3 driver signs in the golden vector.
IMG_PAYLOAD_HASH = "94caee2d6a72b4c18ef8bd2d5d2723f2b1be8c4f25fc2f6dbcc98dbcc9187888"


async def _setup(app_client):
    from tests.conftest import create_workspace, login, register_user, ws_headers

    await register_user(app_client, email="files-owner@example.com")
    owner_tokens = await login(app_client, email="files-owner@example.com")
    ws = await create_workspace(app_client, owner_tokens, name="Files WS")
    await register_user(app_client, email="files-other@example.com")
    other_tokens = await login(app_client, email="files-other@example.com")
    other_ws = await create_workspace(app_client, other_tokens, name="Other WS")
    return ws_headers(owner_tokens, ws["id"]), ws_headers(other_tokens, other_ws["id"])


def _png(name="avatar.png"):
    return {"file": (name, io.BytesIO(PNG), "image/png")}


def _stored_files(workspace_id: str) -> list[Path]:
    from src.settings import settings

    root = Path(settings.storage_dir) / workspace_id
    return sorted(p for p in root.rglob("*") if p.is_file()) if root.exists() else []


class _UnboundedStream:
    """File-like with no length, so httpx sends chunked encoding (no Content-Length)."""

    def __init__(self, total: int) -> None:
        self._left = total

    def read(self, size: int = -1) -> bytes:
        if self._left <= 0:
            return b""
        n = min(size if size and size > 0 else 65536, self._left)
        self._left -= n
        return b"\x00" * n


async def test_upload_store_download_roundtrip(app_client):
    owner, _ = await _setup(app_client)
    resp = await app_client.post("/api/v1/files", files=_png(), headers=owner)
    assert resp.status_code == 201, resp.text
    body = resp.json()

    assert body["url"] == f"/api/v1/files/{body['id']}"
    assert body["size_bytes"] == len(PNG)

    got = await app_client.get(f"/api/v1/files/{body['id']}", headers=owner)
    assert got.status_code == 200, got.text
    assert got.content == PNG
    assert got.headers["content-type"] == "image/png"

    listed = await app_client.get("/api/v1/files", headers=owner)
    assert listed.status_code == 200, listed.text
    assert listed.headers["x-total-count"] == "1"


async def test_avatar_upload_sets_profile_avatar(app_client):
    from tests.conftest import auth_headers, login, register_user

    await register_user(app_client, email="avatar-user@example.com")
    tokens = await login(app_client, email="avatar-user@example.com")
    from tests.conftest import create_workspace, ws_headers

    ws = await create_workspace(app_client, tokens, name="Avatar WS")
    headers = ws_headers(tokens, ws["id"])
    up = await app_client.post("/api/v1/files", files=_png(), headers=headers)
    assert up.status_code == 201, up.text
    url = up.json()["url"]
    prof = await app_client.put(
        "/api/v1/me/profile", json={"avatar_url": url}, headers=auth_headers(tokens)
    )
    assert prof.status_code == 200, prof.text


async def test_type_and_size_limits(app_client):
    owner, _ = await _setup(app_client)
    bad = await app_client.post(
        "/api/v1/files",
        files={"file": ("evil.txt", io.BytesIO(b"hi"), "text/plain")},
        headers=owner,
    )
    assert bad.status_code == 415, bad.text
    big = await app_client.post(
        "/api/v1/files",
        files={"file": ("big.png", io.BytesIO(b"\x00" * (5 * 1024 * 1024 + 1)), "image/png")},
        headers=owner,
    )
    assert big.status_code == 413, big.text


async def test_cross_workspace_download_forbidden(app_client):
    owner, other = await _setup(app_client)
    up = await app_client.post("/api/v1/files", files=_png(), headers=owner)
    assert up.status_code == 201, up.text
    # Other workspace member: same file id under their workspace → 404 (no leak).
    got = await app_client.get(f"/api/v1/files/{up.json()['id']}", headers=other)
    assert got.status_code == 404, got.text
    # Unauthenticated (bad token, valid workspace header) → 401.
    bad = {"Authorization": "Bearer bogus", "X-Workspace-ID": owner["X-Workspace-ID"]}
    anon = await app_client.get(f"/api/v1/files/{up.json()['id']}", headers=bad)
    assert anon.status_code == 401, anon.text


async def test_local_driver_traversal_rejected(tmp_path):
    from src.storage.local import LocalFileStorage

    store = LocalFileStorage(tmp_path)
    await store.put(key="ws1/a.png", content=b"x")
    assert (await store.get(key="ws1/a.png")).content == b"x"
    assert await store.get(key="../evil.png") is None
    # A rejected key must not touch anything outside the root.
    await store.delete(key="../evil.png")
    assert list(tmp_path.rglob("*.png")) == [tmp_path / "ws1" / "a.png"]


async def test_s3_driver_roundtrip_stubbed():
    import httpx

    from src.storage.s3 import S3Config, S3FileStorage

    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen[request.method] = bytes(request.content or b"")
        if request.method == "PUT":
            return httpx.Response(200)
        if request.method == "GET":
            if request.url.path.endswith("missing.png"):
                return httpx.Response(404)
            return httpx.Response(200, content=b"img-bytes", headers={"content-type": "image/png"})
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(500)

    store = S3FileStorage(
        S3Config(endpoint="https://s3.example.com", bucket="b", access_key="ak", secret_key="sk"),
        transport=httpx.MockTransport(handler),
    )
    try:
        await store.put(key="ws/f.png", content=b"img-bytes", content_type="image/png")
        assert seen["PUT"] == b"img-bytes"
        obj = await store.get(key="ws/f.png")
        assert obj is not None and obj.content == b"img-bytes"
        assert await store.get(key="ws/missing.png") is None
        await store.delete(key="ws/f.png")
    finally:
        await store.aclose()


async def test_s3_sigv4_signature_matches_golden_vector(monkeypatch):
    """Frozen date and credentials: a wrong canonical request or key derivation
    still signs, but a real S3 rejects the signature."""
    from datetime import UTC, datetime

    import httpx

    from src.storage import s3 as s3_module
    from src.storage.s3 import S3Config, S3FileStorage

    frozen = datetime(2026, 9, 17, 12, 0, 0, tzinfo=UTC)

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen

    monkeypatch.setattr(s3_module, "datetime", _FrozenDatetime)
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["authorization"]
        seen["date"] = request.headers["x-amz-date"]
        seen["payload"] = request.headers["x-amz-content-sha256"]
        return httpx.Response(200)

    store = S3FileStorage(
        S3Config(endpoint="https://s3.example.com", bucket="b", access_key="ak", secret_key="sk"),
        transport=httpx.MockTransport(handler),
    )
    try:
        await store.put(key="ws/f.png", content=b"img-bytes", content_type="image/png")
    finally:
        await store.aclose()
    assert seen["date"] == "20260917T120000Z"
    assert seen["payload"] == IMG_PAYLOAD_HASH
    assert seen["auth"] == (
        "AWS4-HMAC-SHA256 Credential=ak/20260917/us-east-1/s3/aws4_request, "
        "SignedHeaders=content-type;host;x-amz-content-sha256;x-amz-date, "
        "Signature=3420069f689c2ebbb185b5c8064a280226a4796ee90142c9d09c0b40d64fd551"
    )


async def test_s3_rejects_plaintext_endpoint():
    from src.storage.base import StorageError
    from src.storage.s3 import S3Config, S3FileStorage

    with pytest.raises(StorageError):
        S3FileStorage(S3Config(endpoint="http://s3.example.com", bucket="b"))
    loopback = S3FileStorage(S3Config(endpoint="http://localhost:9000", bucket="b"))
    await loopback.aclose()


async def test_s3_error_status_raises_storage_error():
    import httpx

    from src.storage.base import StorageError
    from src.storage.s3 import S3Config, S3FileStorage

    store = S3FileStorage(
        S3Config(endpoint="https://s3.example.com", bucket="b", access_key="ak", secret_key="sk"),
        transport=httpx.MockTransport(lambda request: httpx.Response(500)),
    )
    try:
        with pytest.raises(StorageError):
            await store.put(key="ws/f.png", content=b"img-bytes", content_type="image/png")
    finally:
        await store.aclose()


async def test_factories_reject_unknown_drivers(monkeypatch):
    from src import settings as settings_module
    from src.storage.factory import build_storage

    monkeypatch.setattr(settings_module.settings, "storage_driver", "gcs")
    with pytest.raises(ValueError):
        build_storage()


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


async def test_spoofed_extension_rejected(app_client):
    from tests.conftest import create_workspace, login, register_user, ws_headers

    await register_user(app_client, email="files-spoof@example.com")
    tokens = await login(app_client, email="files-spoof@example.com")
    ws = await create_workspace(app_client, tokens, name="Spoof WS")
    headers = ws_headers(tokens, ws["id"])
    resp = await app_client.post(
        "/api/v1/files",
        files={"file": ("evil.php", io.BytesIO(PNG_BYTES), "image/png")},
        headers=headers,
    )
    assert resp.status_code == 415, resp.text


async def test_list_rejects_bad_pagination(app_client):
    from tests.conftest import create_workspace, login, register_user, ws_headers

    await register_user(app_client, email="files-badq@example.com")
    tokens = await login(app_client, email="files-badq@example.com")
    ws = await create_workspace(app_client, tokens, name="BadQ WS")
    headers = ws_headers(tokens, ws["id"])
    resp = await app_client.get("/api/v1/files?limit=abc", headers=headers)
    assert resp.status_code == 422, resp.text


async def test_oversize_chunked_upload_is_rejected_without_buffering_whole_body(
    app_client, monkeypatch
):
    """No Content-Length, so the route's bounded read is what rejects the body."""
    from starlette.datastructures import UploadFile

    from src.api.routes import files as files_route
    from tests.conftest import create_workspace, login, register_user, ws_headers

    await register_user(app_client, email="files-big@example.com")
    tokens = await login(app_client, email="files-big@example.com")
    ws = await create_workspace(app_client, tokens, name="Big WS")
    headers = ws_headers(tokens, ws["id"])

    limit = files_route.settings.storage_max_upload_bytes
    pulled = 0
    real_read = UploadFile.read

    async def counting_read(self, size=-1):
        nonlocal pulled
        data = await real_read(self, size)
        pulled += len(data)
        return data

    monkeypatch.setattr(UploadFile, "read", counting_read)

    body = PNG_BYTES + b"\x00" * (limit + 4 * 1024 * 1024)
    resp = await app_client.post(
        "/api/v1/files",
        files={"file": ("big.png", _UnboundedStream(len(body)), "image/png")},
        headers=headers,
    )
    assert resp.status_code == 413, resp.text
    # Bounded read stops one chunk past the cap instead of consuming the body.
    assert pulled <= limit + 1024 * 1024, f"route buffered {pulled} bytes"


async def test_content_length_oversize_rejected_before_body_is_parsed(app_client, monkeypatch):
    """The cap must also fire before Starlette spools the body to a temp file."""
    from starlette.datastructures import UploadFile

    from src.api.routes import files as files_route
    from tests.conftest import create_workspace, login, register_user, ws_headers

    await register_user(app_client, email="files-cl@example.com")
    tokens = await login(app_client, email="files-cl@example.com")
    ws = await create_workspace(app_client, tokens, name="CL WS")
    headers = ws_headers(tokens, ws["id"])

    limit = files_route.settings.storage_max_upload_bytes
    pulled = 0
    real_read = UploadFile.read

    async def counting_read(self, size=-1):
        nonlocal pulled
        data = await real_read(self, size)
        pulled += len(data)
        return data

    monkeypatch.setattr(UploadFile, "read", counting_read)

    body = PNG_BYTES + b"\x00" * (limit + 4 * 1024 * 1024)
    resp = await app_client.post(
        "/api/v1/files",
        files={"file": ("big.png", io.BytesIO(body), "image/png")},
        headers=headers,
    )
    assert resp.status_code == 413, resp.text
    assert pulled == 0, f"the parser spooled {pulled} bytes for a rejected upload"


async def test_upload_rejects_unknown_purpose(tmp_path):
    from src.services.files import FileError, FileService
    from src.storage.local import LocalFileStorage

    class _Session:
        async def execute(self, *args, **kwargs):
            class _Result:
                def scalar_one_or_none(self):
                    return object()

            return _Result()

    service = FileService(_Session(), LocalFileStorage(tmp_path), len(PNG))
    with pytest.raises(FileError, match="unknown purpose"):
        await service.upload(
            workspace_id="ws1",
            owner_user_id="user1",
            filename="avatar.png",
            content_type="image/png",
            content=PNG,
            purpose="invoice",
        )
    assert list(tmp_path.rglob("*")) == []


async def test_delete_account_removes_stored_bytes(app_client):
    from tests.conftest import auth_headers, create_workspace, login, register_user, ws_headers

    await register_user(app_client, email="files-del@example.com")
    tokens = await login(app_client, email="files-del@example.com")
    ws = await create_workspace(app_client, tokens, name="Del WS")
    up = await app_client.post("/api/v1/files", files=_png(), headers=ws_headers(tokens, ws["id"]))
    assert up.status_code == 201, up.text
    assert _stored_files(ws["id"]), "upload never reached the storage dir"

    resp = await app_client.request(
        "DELETE",
        "/api/v1/me",
        json={"confirm": "DELETE", "password": "Password123!"},
        headers=auth_headers(tokens),
    )
    assert resp.status_code == 204, resp.text
    assert _stored_files(ws["id"]) == [], "delete_account left the stored object behind"


async def test_delete_workspace_removes_stored_bytes(app_client):
    from tests.conftest import create_workspace, login, register_user, ws_headers

    await register_user(app_client, email="files-wsdel@example.com")
    tokens = await login(app_client, email="files-wsdel@example.com")
    ws = await create_workspace(app_client, tokens, name="WS Del")
    headers = ws_headers(tokens, ws["id"])
    up = await app_client.post("/api/v1/files", files=_png(), headers=headers)
    assert up.status_code == 201, up.text
    assert _stored_files(ws["id"]), "upload never reached the storage dir"

    resp = await app_client.delete(f"/api/v1/workspaces/{ws['id']}", headers=headers)
    assert resp.status_code == 204, resp.text
    assert _stored_files(ws["id"]) == [], "delete_workspace left the stored object behind"


async def test_s3_signs_the_endpoint_path_prefix():
    """A path-prefixed endpoint must sign the path it actually sends on the wire."""
    import httpx

    from src.storage.s3 import S3Config, S3FileStorage

    async def _sign(endpoint: str) -> tuple[str, str]:
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["path"] = request.url.path
            seen["host"] = request.headers["host"]
            seen["auth"] = request.headers["authorization"]
            return httpx.Response(200)

        store = S3FileStorage(
            S3Config(endpoint=endpoint, bucket="b", access_key="ak", secret_key="sk"),
            transport=httpx.MockTransport(handler),
        )
        try:
            await store.put(key="ws/f.png", content=b"img-bytes", content_type="image/png")
        finally:
            await store.aclose()
        return seen["path"], seen["auth"]

    path, prefixed = await _sign("https://gateway.example.com/s3")
    assert path == "/s3/b/ws/f.png"
    assert "SignedHeaders=content-type;host" in prefixed
    # A canonical URI without the prefix would sign the same bytes as the
    # unprefixed endpoint, and a real S3 would answer SignatureDoesNotMatch.
    assert prefixed != (await _sign("https://gateway.example.com"))[1]


async def test_empty_upload_rejected(app_client):
    owner, _ = await _setup(app_client)
    resp = await app_client.post(
        "/api/v1/files",
        files={"file": ("empty.png", io.BytesIO(b""), "image/png")},
        headers=owner,
    )
    assert resp.status_code == 400, resp.text


async def test_upload_at_size_limit_accepted(app_client, monkeypatch):
    from src import settings as settings_module
    from tests.conftest import create_workspace, login, register_user, ws_headers

    await register_user(app_client, email="files-edge@example.com")
    tokens = await login(app_client, email="files-edge@example.com")
    ws = await create_workspace(app_client, tokens, name="Edge WS")
    headers = ws_headers(tokens, ws["id"])
    monkeypatch.setattr(settings_module.settings, "storage_max_upload_bytes", len(PNG))
    resp = await app_client.post("/api/v1/files", files=_png(), headers=headers)
    assert resp.status_code == 201, resp.text
    assert resp.json()["size_bytes"] == len(PNG)


async def test_upload_forbidden_for_non_member(app_client):
    owner, other = await _setup(app_client)
    resp = await app_client.post(
        "/api/v1/files",
        files=_png(),
        headers={**other, "X-Workspace-ID": owner["X-Workspace-ID"]},
    )
    assert resp.status_code == 403, resp.text


async def test_orphan_bytes_removed_when_metadata_insert_fails(tmp_path):
    """A failed insert must not leave the stored object behind."""
    from src.services.files import FileService
    from src.storage.local import LocalFileStorage

    class _FailingSession:
        def add(self, row) -> None:
            self.row = row

        async def execute(self, *args, **kwargs):
            class _Result:
                def scalar_one_or_none(self):
                    return object()

            return _Result()

        async def commit(self) -> None:
            raise RuntimeError("db down")

    service = FileService(_FailingSession(), LocalFileStorage(tmp_path), len(PNG))
    with pytest.raises(RuntimeError, match="db down"):
        await service.upload(
            workspace_id="ws1",
            owner_user_id="user1",
            filename="avatar.png",
            content_type="image/png",
            content=PNG,
        )
    assert [p for p in tmp_path.rglob("*") if p.is_file()] == []


async def test_download_publishes_audit_event(app_client):
    from sqlalchemy import select

    from src.db.session import SessionFactory
    from src.models.audit import AuditLogEntry

    owner, _ = await _setup(app_client)
    up = await app_client.post("/api/v1/files", files=_png(), headers=owner)
    assert up.status_code == 201, up.text
    got = await app_client.get(f"/api/v1/files/{up.json()['id']}", headers=owner)
    assert got.status_code == 200, got.text

    async def _actions() -> list[str]:
        async with SessionFactory() as session:
            rows = await session.execute(select(AuditLogEntry.action))
            return list(rows.scalars())

    for _ in range(100):
        if "file.downloaded" in await _actions():
            break
        await asyncio.sleep(0.05)
    assert "file.downloaded" in await _actions()
