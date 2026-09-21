from pathlib import Path

import pytest

from src.settings import Settings


@pytest.fixture(autouse=True)
def _clean_db_env(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("USE_SQLITE", raising=False)


def test_explicit_database_url_wins_over_use_sqlite():
    s = Settings(database_url="x", use_sqlite=True)
    assert s.resolved_database_url == "x"


def test_use_sqlite_resolves_to_per_checkout_dev_db():
    import src.settings as settings_mod

    s = Settings(use_sqlite=True)
    expected = f"sqlite+aiosqlite:///{Path(settings_mod.__file__).resolve().parents[1] / 'dev.db'}"
    assert s.resolved_database_url == expected
    assert s.database_url_sqlite is True


def test_default_falls_back_to_embedded(monkeypatch):
    monkeypatch.setattr("src.db.embedded.embedded_uri", lambda: "postgresql+asyncpg://embedded")
    s = Settings()
    assert s.use_sqlite is False
    assert s.resolved_database_url == "postgresql+asyncpg://embedded"


def test_empty_use_sqlite_string_is_unset():
    s = Settings.model_validate({"use_sqlite": ""})
    assert s.use_sqlite is False


def test_whitespace_use_sqlite_string_is_unset():
    for v in [" ", "   ", "\t\n"]:
        s = Settings.model_validate({"use_sqlite": v})
        assert s.use_sqlite is False
