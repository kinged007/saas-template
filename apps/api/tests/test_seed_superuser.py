"""Issue #62: dev seed must not create a second superuser.

When SUPERADMIN_EMAIL names a real address, the bootstrap account (granted
superuser by AuthService.register) is the superuser — the unconditional
admin@example.com promotion must be skipped. Gate: settings.superadmin_email.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src import seed as seed_mod


@pytest.fixture
def _stub_seed_deps(monkeypatch):
    """Replace the seed's DB-touching collaborators with in-memory stubs."""
    admin = SimpleNamespace(email="admin@example.com", is_superuser=False)

    async def fake_get_by_email(self, email):
        return admin if email == "admin@example.com" else SimpleNamespace(email=email)

    monkeypatch.setattr(
        seed_mod.AuthService, "register", AsyncMock(side_effect=RuntimeError("no-op"))
    )
    monkeypatch.setattr(seed_mod.AuthService, "get_by_email", fake_get_by_email)
    monkeypatch.setattr(
        seed_mod.WorkspaceService,
        "sync_system_role_permissions",
        AsyncMock(return_value=0),
    )
    return admin


async def test_seed_promotion_block_matches_source():
    import inspect

    src = inspect.getsource(seed_mod.main)
    assert "settings.superadmin_email.strip()" in src


async def test_seed_main_skips_promotion_with_superadmin_set(monkeypatch, _stub_seed_deps):
    """End-to-end through seed.main with DB-heavy tail stubbed out."""
    from sqlalchemy import select  # noqa: F401  (kept for parity with seed internals)

    monkeypatch.setattr(seed_mod.settings, "superadmin_email", "boss@example.com", raising=False)

    class _Result:
        def scalar_one_or_none(self):
            return None

    class _Session:
        async def execute(self, *a, **k):
            return _Result()

        def add(self, *a, **k):
            pass

        async def commit(self):
            pass

    class _CM:
        async def __aenter__(self):
            return _Session()

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(seed_mod, "SessionFactory", lambda: _CM())
    monkeypatch.setattr(
        seed_mod.WorkspaceService, "create_workspace", AsyncMock(side_effect=RuntimeError("stop"))
    )
    with patch("builtins.print"):
        with pytest.raises(RuntimeError, match="stop"):
            await seed_mod.main()
    assert _stub_seed_deps.is_superuser is False


async def test_seed_main_promotes_with_superadmin_unset(monkeypatch, _stub_seed_deps):
    monkeypatch.setattr(seed_mod.settings, "superadmin_email", "", raising=False)

    class _Result:
        def scalar_one_or_none(self):
            return None

    class _Session:
        async def execute(self, *a, **k):
            return _Result()

        def add(self, *a, **k):
            pass

        async def commit(self):
            pass

    class _CM:
        async def __aenter__(self):
            return _Session()

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(seed_mod, "SessionFactory", lambda: _CM())
    monkeypatch.setattr(
        seed_mod.WorkspaceService, "create_workspace", AsyncMock(side_effect=RuntimeError("stop"))
    )
    with patch("builtins.print"):
        with pytest.raises(RuntimeError, match="stop"):
            await seed_mod.main()
    assert _stub_seed_deps.is_superuser is True
