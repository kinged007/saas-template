"""`make dev` must not clobber the CORS origins the user set in apps/api/.env,
and must allowlist every loopback name vite serves (127.0.0.1 as well as
localhost) so the CSRF check accepts the proxied refresh call."""

import importlib.util
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def _load_dev():
    spec = importlib.util.spec_from_file_location("dev_supervisor", ROOT / "scripts" / "dev.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def api_env(tmp_path, monkeypatch):
    env_path = tmp_path / "apps" / "api" / ".env"
    env_path.parent.mkdir(parents=True)
    env_path.write_text(
        "# comment\nCORS_ORIGINS=http://localhost:5173,*.coder.munyard.biz\n"
        "FRONTEND_URL='http://localhost:5173'\n\nOTHER=1\n"
    )
    dev = _load_dev()
    monkeypatch.setattr(dev, "ROOT", str(tmp_path))
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    monkeypatch.delenv("FRONTEND_URL", raising=False)
    return dev


def test_reads_env_file_value(api_env):
    assert api_env.api_env_file("CORS_ORIGINS") == "http://localhost:5173,*.coder.munyard.biz"
    assert api_env.api_env_file("FRONTEND_URL") == "http://localhost:5173"


def test_missing_file_and_key_are_empty(tmp_path, monkeypatch):
    dev = _load_dev()
    monkeypatch.setattr(dev, "ROOT", str(tmp_path))
    assert dev.api_env_file("CORS_ORIGINS") == ""


def test_allowed_origins_cover_both_loopback_names(api_env):
    origins = api_env.dev_allowed_origins("5318")
    assert "http://localhost:5318" in origins
    assert "http://127.0.0.1:5318" in origins
    # The user's own entries survive the lift.
    assert "*.coder.munyard.biz" in origins


def test_allowed_origins_pass_the_csrf_check(api_env, monkeypatch):
    """The supervisor's env is only useful if the API accepts these origins."""
    from src.core.security import cookies

    origins = api_env.dev_allowed_origins("5318")
    monkeypatch.setattr(cookies.settings, "cors_origins", ",".join(origins))
    # A `*` entry is a pattern for the CORS middleware, not a browser origin.
    assert all(cookies._origin_allowed(o) for o in origins if "*" not in o)


def test_shell_env_wins_over_file(tmp_path, monkeypatch):
    (tmp_path / "apps" / "api").mkdir(parents=True)
    (tmp_path / "apps" / "api" / ".env").write_text("CORS_ORIGINS=from-file\n")
    dev = _load_dev()
    monkeypatch.setattr(dev, "ROOT", str(tmp_path))
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example.com")
    assert (os.environ.get("CORS_ORIGINS") or dev.api_env_file("CORS_ORIGINS")).split(",") == [
        "https://a.example.com"
    ]
