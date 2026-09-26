"""The product name must come from config, not from source literals.

settings.py is excluded from the scan: it holds the defaults the whole app
falls back to, which is the one place a name is allowed to be written down.
"""

import re
from pathlib import Path

import pytest

from src.events.nats import STREAM_NAME, NatsEventBus
from src.settings import settings, slugify

SRC = Path(__file__).resolve().parents[1] / "src"
PRODUCT_NAME = re.compile(r"saas[- _]?template", re.IGNORECASE)


def test_app_slug_is_kebab():
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", settings.app_slug)


@pytest.mark.parametrize(
    ("value", "expected"), [("Acme Corp", "acme-corp"), ("  Foo_Bar ", "foo-bar"), ("!!!", "")]
)
def test_slugify(value, expected):
    assert slugify(value) == expected


def test_slugs_stay_usable_as_identifiers():
    # Machine names derive from the slug, so it must survive the NATS uppercase
    # form and stay a single path segment.
    assert STREAM_NAME == settings.app_slug.upper().replace("-", "_")
    assert settings.app_slug == Path(settings.app_slug).name


async def test_routes_report_the_configured_name(app_client):
    client = app_client
    assert (await client.get("/")).json()["service"] == settings.app_name
    assert (await client.get("/healthz")).json()["service"] == settings.app_name


def test_openapi_title_is_the_configured_name(app_client):
    assert app_client.app.title == settings.app_name


def test_nats_queue_group_defaults_to_the_slug():
    assert NatsEventBus("nats://localhost:4222")._queue_group == f"{settings.app_slug}-workers"


def test_no_product_name_literals_in_runtime_source():
    offenders = [
        f"{path.relative_to(SRC)}:{i}"
        for path in SRC.rglob("*.py")
        if path.name != "settings.py"
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if PRODUCT_NAME.search(line)
    ]
    assert offenders == [], f"hardcoded product name: {offenders}"
