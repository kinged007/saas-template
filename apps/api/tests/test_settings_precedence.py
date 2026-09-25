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


def test_branding_settings_drive_runtime_identifiers():
    s = Settings(
        _env_file=None,
        app_name="My Product",
        app_slug="my-product",
        seed_email_domain="test.invalid",
        seed_workspace_names="First, Second",
    )

    assert s.api_name == "My Product API"
    assert s.service_name == "my-product-api"
    assert s.refresh_cookie_name == "my_product_refresh"
    assert s.nats_stream_name_effective == "MY_PRODUCT"
    assert s.nats_consumer_prefix_effective == "mp"
    assert s.seed_workspace_specs == [
        {"name": "First", "slug": "first", "description": "Demo workspace"},
        {"name": "Second", "slug": "second", "description": "Second demo workspace"},
    ]


def test_default_identifiers_preserve_existing_names(monkeypatch):
    monkeypatch.delenv("APP_SLUG", raising=False)
    monkeypatch.delenv("APP_NAME", raising=False)
    s = Settings(_env_file=None)

    assert s.app_slug == "saas-template"
    assert s.refresh_cookie_name == "st_refresh"
    assert s.nats_stream_name_effective == "SAAS_TEMPLATE"
    assert s.nats_consumer_prefix_effective == "st"


def test_app_slug_rejects_non_dns_identifiers():
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        Settings(_env_file=None, app_slug="Not A Slug")


def test_app_name_env_derives_default_slug(monkeypatch):
    monkeypatch.delenv("APP_SLUG", raising=False)
    monkeypatch.setenv("APP_NAME", "My Product")

    s = Settings(_env_file=None)

    assert s.app_slug == "my-product"
