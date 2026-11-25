"""Project-owned tables (demo: one workspace-scoped widget table).

Imported as `src.project.models` by the `src/models/__init__.py` seam, so
`Base.metadata` — and therefore Alembic autogenerate — sees project tables
with no per-feature edit to template-owned files.
"""

from __future__ import annotations

import uuid

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base, StringUUID, TimestampMixin
from src.project.permissions import DEMO_CREATE, DEMO_READ  # noqa: F401 (register on import)

__all__ = ["DemoWidget"]


class DemoWidget(Base, TimestampMixin):
    """Demo row: a named thing in a workspace, proving the model seam."""

    __tablename__ = "demo_widgets"

    id: Mapped[str] = mapped_column(
        StringUUID(), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    workspace_id: Mapped[str] = mapped_column(StringUUID(), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
