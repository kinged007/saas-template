"""TOTP (RFC 6238) with stdlib only: hmac + base64 + time + secrets.

No pyotp dependency — TOTP is ~20 lines over HMAC-SHA1.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote, urlencode

STEP_SECONDS = 30
DIGITS = 6
WINDOW = 1  # accept ±1 step for clock skew


def generate_secret(num_bytes: int = 20) -> bytes:
    return secrets.token_bytes(num_bytes)


def secret_to_base32(secret: bytes) -> str:
    return base64.b32encode(secret).decode("ascii").rstrip("=")


def secret_from_base32(encoded: str) -> bytes:
    padded = encoded.upper().strip() + "=" * (-len(encoded.strip()) % 8)
    return base64.b32decode(padded)


def otpauth_uri(*, secret_b32: str, email: str, issuer: str) -> str:
    label = f"{quote(issuer, safe='')}:{quote(email, safe='')}"
    query = urlencode(
        {
            "secret": secret_b32,
            "issuer": issuer,
            "algorithm": "SHA1",
            "digits": DIGITS,
            "period": STEP_SECONDS,
        }
    )
    return f"otpauth://totp/{label}?{query}"


def _hotp(secret: bytes, counter: int) -> str:
    mac = hmac.new(secret, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    code = struct.unpack(">I", mac[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(code % 10**DIGITS).zfill(DIGITS)


def current_code(secret: bytes, *, at: float | None = None) -> str:
    counter = int((at if at is not None else time.time()) // STEP_SECONDS)
    return _hotp(secret, counter)


def verify(
    secret: bytes, code: str, *, at: float | None = None, last_counter: int | None = None
) -> int | None:
    """Verify a code; return the matched counter, or None.

    `last_counter` enforces replay protection: counters at or below it are
    rejected even when the code matches.
    """
    code = code.strip().replace(" ", "")
    if len(code) != DIGITS or not code.isdigit():
        return None
    now = int((at if at is not None else time.time()) // STEP_SECONDS)
    for counter in range(now - WINDOW, now + WINDOW + 1):
        if last_counter is not None and counter <= last_counter:
            continue
        if hmac.compare_digest(_hotp(secret, counter), code):
            return counter
    return None


def generate_backup_codes(count: int = 8) -> list[str]:
    return [secrets.token_hex(5) for _ in range(count)]


def hash_backup_code(code: str) -> str:
    return hashlib.sha256(code.strip().lower().encode("utf-8")).hexdigest()
