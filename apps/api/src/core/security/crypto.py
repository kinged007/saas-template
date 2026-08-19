from __future__ import annotations

import base64

from cryptography.fernet import Fernet, InvalidToken


def _normalize_key(key: str) -> bytes:
    """Normalize an env-provided key to a valid Fernet key (url-safe base64, 32 bytes)."""
    raw = key.strip().encode("utf-8")
    if len(raw) == 32:
        return base64.urlsafe_b64encode(raw)
    if len(raw) < 32:
        return base64.urlsafe_b64encode(raw + b"\x00" * (32 - len(raw)))
    return base64.urlsafe_b64encode(raw[:32])


class SecretCipher:
    """Fernet symmetric encryption for secrets at rest, with VERSIONED envelopes.

    `FERNET_KEYS` holds one or more keys (comma separated); `encrypt_version`
    (env `SECRET_ENCRYPT_VERSION`, 1-based) selects which key encrypts new
    secrets. Every ciphertext carries its version:

        v1.<fernet-token>      # encrypted with FERNET_KEYS[0]
        v2.<fernet-token>      # encrypted with FERNET_KEYS[1]
        ...

    Rotation is additive: keep the old keys in `FERNET_KEYS`, append the new
    key, and bump `SECRET_ENCRYPT_VERSION` to the new key's position. Old
    secrets keep decrypting (their envelope pins the version), new secrets are
    written with the new key, and old versions can be re-encrypted later.

    Legacy plain tokens (no `vN.` prefix — the pre-versioning format used for
    connection secrets) still decrypt by trying every configured key.
    """

    def __init__(self, keys: list[str], encrypt_version: int = 1) -> None:
        if not keys:
            raise ValueError("at least one FERNET_KEYS entry is required")
        self._keys = list(keys)
        self._fernets = [Fernet(_normalize_key(k)) for k in keys]
        if encrypt_version < 1 or encrypt_version > len(keys):
            raise ValueError(
                f"SECRET_ENCRYPT_VERSION {encrypt_version} is out of range "
                f"(FERNET_KEYS has {len(keys)} keys)"
            )
        self._encrypt_version = encrypt_version

    def encrypt(self, plaintext: str) -> str:
        fernet = self._fernets[self._encrypt_version - 1]
        token = fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")
        return f"v{self._encrypt_version}.{token}"

    def decrypt(self, ciphertext: str) -> str:
        if not ciphertext:
            return ""
        token = ciphertext
        candidates: list[int] = []
        if ciphertext.startswith("v") and "." in ciphertext:
            version_raw, _, token = ciphertext.partition(".")
            try:
                version = int(version_raw[1:])
            except ValueError:
                version = 0
            # The envelope pins the exact key used at write time — try it
            # first, then fall back to every configured key (covers legacy
            # envelopes and keys that were reordered after rotation).
            if 1 <= version <= len(self._fernets):
                candidates.append(version - 1)
        candidates.extend(i for i in range(len(self._fernets)) if i not in candidates)
        last_error: Exception | None = None
        for index in candidates:
            try:
                return self._fernets[index].decrypt(token.encode("ascii")).decode("utf-8")
            except (InvalidToken, ValueError) as exc:
                last_error = exc
        raise last_error or ValueError("no key could decrypt the secret")
