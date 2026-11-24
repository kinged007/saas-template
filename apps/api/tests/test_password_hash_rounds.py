"""PASSWORD_HASH_ROUNDS: configurable bcrypt cost factor."""

import pytest
from pydantic import ValidationError

from src.core.security.password import PasswordHasher
from src.settings import Settings, settings


def test_default_rounds_is_12():
    assert settings.password_hash_rounds == 12
    assert Settings().password_hash_rounds == 12


def test_hash_and_verify_roundtrip():
    hashed = PasswordHasher.hash("correct horse")
    assert hashed != "correct horse"
    assert PasswordHasher.verify("correct horse", hashed) is True
    assert PasswordHasher.verify("wrong horse", hashed) is False


def test_malformed_hash_never_verifies():
    assert PasswordHasher.verify("anything", "not-a-hash") is False


def test_rounds_setting_controls_cost(monkeypatch):
    monkeypatch.setattr(settings, "password_hash_rounds", 4)
    hashed = PasswordHasher.hash("fast cost")
    assert hashed.startswith("$2b$04$")
    assert PasswordHasher.verify("fast cost", hashed) is True


def test_rounds_out_of_range_rejected():
    with pytest.raises(ValidationError):
        Settings(password_hash_rounds=3)
    with pytest.raises(ValidationError):
        Settings(password_hash_rounds=32)
