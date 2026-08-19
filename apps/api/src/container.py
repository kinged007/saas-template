"""Application container: shared singletons (event bus, cipher, realtime).

Routers/services must use these singletons — creating a new event bus per
request would break pub/sub delivery.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.core.cache import TtlCache
from src.core.security.crypto import SecretCipher
from src.events.bus import EventBus
from src.events.factory import build_event_bus
from src.realtime.manager import ConnectionManager
from src.secrets.base import SecretStore
from src.secrets.factory import build_secret_store
from src.settings import settings

PROVIDER_CACHE_TTL_SECONDS = 300.0


@dataclass
class Container:
    bus: EventBus = field(default_factory=build_event_bus)
    cipher: SecretCipher = field(
        default_factory=lambda: SecretCipher(
            settings.fernet_key_list, encrypt_version=settings.secret_encrypt_version
        )
    )
    secret_store: SecretStore = field(default_factory=build_secret_store)
    connection_manager: ConnectionManager = field(default_factory=ConnectionManager)
    cache: TtlCache = field(
        default_factory=lambda: TtlCache(ttl_seconds=PROVIDER_CACHE_TTL_SECONDS)
    )
