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


def test_cors_wildcard_entry_becomes_origin_regex():
    import re

    s = Settings(cors_origins="http://localhost:5173,*.coder.munyard.biz")
    assert s.cors_origin_list == ["http://localhost:5173"]
    pattern = s.cors_origin_regex
    assert pattern and re.fullmatch(pattern, "https://a.coder.munyard.biz")
    assert pattern and re.fullmatch(pattern, "http://a.b.coder.munyard.biz:8443")
    for origin in ("https://coder.munyard.biz", "https://a.coder.munyard.biz.evil.com"):
        assert not re.fullmatch(pattern or "", origin)


def test_cors_port_wildcard():
    import re

    pattern = Settings(cors_origins="http://localhost:*").cors_origin_regex
    assert pattern and re.fullmatch(pattern, "http://localhost:5273")
    assert pattern and re.fullmatch(pattern, "http://localhost:8000")
    # the entry pins the scheme and requires the port the `*` stands for
    assert not re.fullmatch(pattern or "", "https://localhost:5273")
    assert not re.fullmatch(pattern or "", "http://localhost")
    assert not re.fullmatch(pattern or "", "http://notlocalhost:5273")


def test_cors_entry_scheme_is_honoured():
    import re

    pattern = Settings(cors_origins="https://*.example.com").cors_origin_regex
    assert pattern and re.fullmatch(pattern, "https://a.example.com")
    assert not re.fullmatch(pattern or "", "http://a.example.com")


def test_cors_without_wildcard_has_no_regex():
    assert Settings(cors_origins="http://localhost:5173").cors_origin_regex is None


def test_frontend_url_uses_first_concrete_entry():
    s = Settings(frontend_url="https://*.coder.munyard.biz,http://localhost:5173")
    assert s.frontend_url == "http://localhost:5173"
    assert (
        Settings(frontend_url="https://app.example.com").frontend_url == "https://app.example.com"
    )


def test_frontend_url_all_wildcards_falls_back_to_default():
    s = Settings(frontend_url="http://localhost:*,*.coder.munyard.biz")
    assert s.frontend_url == "http://localhost:5173"
