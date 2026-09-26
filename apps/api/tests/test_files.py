"""File upload → store → authorized download (issue #18 acceptance).

Local driver e2e through the API; S3 driver contract via stubbed transport;
limits + workspace isolation.
"""

from __future__ import annotations

import io

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


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
    assert got.status_code in (403, 404), got.text
    # Unauthenticated (bad token, valid workspace header) → 401.
    bad = {"Authorization": "Bearer bogus", "X-Workspace-ID": owner["X-Workspace-ID"]}
    anon = await app_client.get(f"/api/v1/files/{up.json()['id']}", headers=bad)
    assert anon.status_code == 401, anon.text


async def test_local_driver_traversal_rejected():
    from src.storage.local import LocalFileStorage

    store = LocalFileStorage("/tmp/saas-template-storage-test")
    await store.put(key="ws1/a.png", content=b"x")
    assert await store.exists(key="ws1/a.png")
    assert not await store.exists(key="../evil.png")
    assert await store.get(key="../evil.png") is None


async def test_s3_driver_roundtrip_stubbed():
    import httpx

    from src.storage.s3 import S3Config, S3FileStorage

    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen[request.method] = bytes(request.content or b"")
        if request.method == "PUT":
            return httpx.Response(200)
        if request.method == "GET":
            return httpx.Response(200, content=b"img-bytes", headers={"content-type": "image/png"})
        if request.method == "HEAD":
            return httpx.Response(200)
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(500)

    store = S3FileStorage(
        S3Config(endpoint="https://s3.example.com", bucket="b", access_key="ak", secret_key="sk"),
        transport=httpx.MockTransport(handler),
    )
    await store.put(key="ws/f.png", content=b"img-bytes", content_type="image/png")
    assert seen["PUT"] == b"img-bytes"
    obj = await store.get(key="ws/f.png")
    assert obj is not None and obj.content == b"img-bytes"
    assert await store.exists(key="ws/f.png")
    await store.delete(key="ws/f.png")


async def test_factories_reject_unknown_drivers(monkeypatch):
    import pytest

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


async def test_oversize_upload_is_rejected_without_buffering_whole_body(app_client, monkeypatch):
    """413 must fire while reading, not after the entire body is buffered."""
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
        files={"file": ("big.png", io.BytesIO(body), "image/png")},
        headers=headers,
    )
    assert resp.status_code == 413, resp.text
    # Bounded read stops one chunk past the cap instead of consuming the body.
    assert pulled <= limit + 1024 * 1024, f"route buffered {pulled} bytes"
