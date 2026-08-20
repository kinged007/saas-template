"""Tests for the encrypted secret store: versioned encryption (rotation),
DbSecretStore, and basic CRUD operations."""


# ------------------------------------------------------------ crypto


def _cipher(keys: list[str], version: int = 1) -> "object":
    from src.core.security.crypto import SecretCipher

    return SecretCipher(keys, encrypt_version=version)


def test_encrypt_roundtrip_versioned():
    cipher = _cipher(["key-one-000000000000000000000000000000"])
    blob = cipher.encrypt("super-secret-value")
    assert blob.startswith("v1.")
    assert "super-secret-value" not in blob
    assert cipher.decrypt(blob) == "super-secret-value"


def test_legacy_unversioned_token_still_decrypts():
    """Secrets encrypted before versioning (plain fernet tokens) must keep working."""
    from cryptography.fernet import Fernet

    from src.core.security.crypto import _normalize_key

    legacy = (
        Fernet(_normalize_key("legacy-key-0000000000000000000000000000"))
        .encrypt(b"old-secret")
        .decode()
    )
    cipher = _cipher(["legacy-key-0000000000000000000000000000", "extra-key-0000000000000"])
    assert not legacy.startswith("v")
    assert cipher.decrypt(legacy) == "old-secret"


def test_rotation_appends_key_and_bumps_version():
    old_key = "key-a-00000000000000000000000000000000"
    new_key = "key-b-00000000000000000000000000000000"
    before = _cipher([old_key], version=1)
    old_blob = before.encrypt("old-secret")
    assert old_blob.startswith("v1.")

    # rotate: append the new key and bump SECRET_ENCRYPT_VERSION to its slot
    after = _cipher([old_key, new_key], version=2)
    assert after.decrypt(old_blob) == "old-secret"  # old envelope keeps decrypting
    new_blob = after.encrypt("new-secret")
    assert new_blob.startswith("v2.")
    assert after.decrypt(new_blob) == "new-secret"


def test_encrypt_version_out_of_range_raises():
    import pytest

    with pytest.raises(ValueError):
        _cipher(["key-a-00000000000000000000000000000000"], version=2)


# ------------------------------------------------------------ store


async def _store():
    from src.core.security.crypto import SecretCipher
    from src.db.session import SessionFactory
    from src.secrets.db_store import DbSecretStore
    from src.settings import settings

    cipher = SecretCipher(settings.fernet_key_list, encrypt_version=settings.secret_encrypt_version)
    return DbSecretStore(SessionFactory, cipher)


async def test_store_roundtrip_upsert_delete_and_list():
    import uuid

    store = await _store()
    ws_id = str(uuid.uuid4())
    await store.put(
        workspace_id=ws_id,
        key="app:myapp:password_secret:keyid-1",
        value="p@ssw0rd-secret",
        kind="password_secret",
        label="My credential",
        key_id="keyid-1",
        meta={"app_name": "myapp"},
    )
    # ciphertext at rest is versioned and does not contain the plaintext
    from sqlalchemy import select

    from src.db.session import SessionFactory
    from src.models.secret import StoredSecret

    async with SessionFactory() as session:
        row = (
            await session.execute(
                select(StoredSecret).where(
                    StoredSecret.secret_key == "app:myapp:password_secret:keyid-1"
                )
            )
        ).scalar_one()
        assert row.ciphertext.startswith("v1.")
        assert "p@ssw0rd-secret" not in row.ciphertext
        assert row.key_version == 1

    record = await store.get(workspace_id=ws_id, key="app:myapp:password_secret:keyid-1")
    assert record is not None
    assert record.value == "p@ssw0rd-secret"
    assert record.kind == "password_secret"
    assert record.key_id == "keyid-1"
    assert record.meta["app_name"] == "myapp"

    # upsert replaces the value under the same key
    await store.put(
        workspace_id=ws_id,
        key="app:myapp:password_secret:keyid-1",
        value="rotated-secret",
        kind="password_secret",
    )
    record = await store.get(workspace_id=ws_id, key="app:myapp:password_secret:keyid-1")
    assert record.value == "rotated-secret"

    # list with prefix
    await store.put(
        workspace_id=ws_id,
        key="app:myapp:client_secret:0oa-1",
        value="oidc-secret",
        kind="client_secret",
    )
    await store.put(workspace_id=ws_id, key="other:thing", value="x", kind="other")
    listed = await store.list_for_workspace(ws_id, prefix="app:myapp:")
    assert {r.key for r in listed} == {
        "app:myapp:password_secret:keyid-1",
        "app:myapp:client_secret:0oa-1",
    }
    assert {r.value for r in listed} == {"rotated-secret", "oidc-secret"}

    # other workspaces are isolated
    assert await store.list_for_workspace(str(uuid.uuid4()), prefix="app:myapp:") == []

    await store.delete(workspace_id=ws_id, key="app:myapp:password_secret:keyid-1")
    assert await store.get(workspace_id=ws_id, key="app:myapp:password_secret:keyid-1") is None
