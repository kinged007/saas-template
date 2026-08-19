"""Secret store factory: selects the backend from `SECRET_STORE_DRIVER`.

The reference backend is the DB table (`db`). Future vault adapters
(HashiCorp Vault, AWS Secrets Manager, ...) implement `SecretStore` and are
registered here — the worker and API only ever depend on the interface.
"""

from __future__ import annotations

from src.core.security.crypto import SecretCipher
from src.secrets.base import SecretStore
from src.secrets.db_store import DbSecretStore
from src.settings import settings

_SECRET_STORE_DRIVERS: dict[str, type] = {
    "db": DbSecretStore,
}


def build_secret_store() -> SecretStore:
    """Build the configured SecretStore backend.

    Uses the global `SessionFactory` (see db.session) so it works
    both inside request handlers and in background workers.
    """
    driver = settings.secret_store_driver
    try:
        store_type = _SECRET_STORE_DRIVERS[driver]
    except KeyError:
        raise ValueError(
            f"unsupported SECRET_STORE_DRIVER: {driver!r} "
            f"(available: {sorted(_SECRET_STORE_DRIVERS)})"
        ) from None
    from src.db.session import SessionFactory

    cipher = SecretCipher(settings.fernet_key_list, encrypt_version=settings.secret_encrypt_version)
    return store_type(SessionFactory, cipher)
