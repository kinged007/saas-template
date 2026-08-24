"""Secret store contract: where one-time credential material is kept.

Some integrations only reveal a secret ONCE, at creation time (e.g. a
generated API token or an OAuth client secret), and never return it again.
This interface stores that material — encrypted at rest, versioned,
workspace-scoped — so callers can persist and later fetch it.

The reference implementation is `DbSecretStore` (encrypted `stored_secrets`
table). A future secret-vault adapter (HashiCorp Vault, AWS Secrets Manager,
...) implements the same interface and is selected via
`SECRET_STORE_DRIVER` — callers never know which backend is used.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class SecretRecord:
    """A decrypted secret entry returned from the store."""

    key: str
    kind: str
    label: str | None
    value: str
    key_id: str | None = None
    meta: dict = field(default_factory=dict)
    created_at: datetime | None = None
    expires_at: datetime | None = None


class SecretStore(ABC):
    """Interface for storing and fetching encrypted secret material."""

    @abstractmethod
    async def put(
        self,
        *,
        workspace_id: str,
        key: str,
        value: str,
        kind: str,
        label: str | None = None,
        key_id: str | None = None,
        meta: dict | None = None,
        expires_at: datetime | None = None,
    ) -> None:
        """Store (or replace) one secret under `key` for the workspace."""

    @abstractmethod
    async def get(self, *, workspace_id: str, key: str) -> SecretRecord | None:
        """Fetch and decrypt one secret."""

    @abstractmethod
    async def delete(self, *, workspace_id: str, key: str) -> None:
        """Remove one secret. Deleting is the ONLY way to destroy material —
        vault backends and the DB table both keep encrypted rows otherwise."""

    @abstractmethod
    async def list_for_workspace(
        self, workspace_id: str, *, prefix: str | None = None
    ) -> list[SecretRecord]:
        """List all secrets for a workspace, optionally filtered by key prefix."""
