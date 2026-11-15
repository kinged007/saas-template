"""audit resource_id to native UUID on postgres

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-04 00:00:00.000000

`AuditLogEntry.resource_id` is a StringUUID in the model (native UUID on
postgres) but databases created before that change carry VARCHAR(36). Every
bus-delivered audit write runs the source-event dedupe lookup comparing that
column, and Postgres has no `character varying = uuid` operator — so on an
unmigrated database every audit write fails and the trail silently stops
(SQLite is loosely typed, which is why tests never caught it).

Legacy sentinel rows predate UUID-only resource ids (bulk acknowledge used
resource_id='all'): they are rewritten to their workspace first, matching
what the code writes now.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "audit_log_entries"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return  # CHAR(36) already; sqlite compares loosely either way
    cols = {c["name"]: c for c in sa.inspect(bind).get_columns(_TABLE)}
    from sqlalchemy.dialects.postgresql import UUID as PGUUID

    if isinstance(cols["resource_id"]["type"], PGUUID):
        return
    op.execute(
        f"UPDATE {_TABLE} SET resource_id = workspace_id "
        f"WHERE resource_type = 'notification' AND action = 'notifications.acknowledged' "
        f"AND resource_id = 'all' AND workspace_id IS NOT NULL"
    )
    # Any sentinel left (e.g. NULL-workspace rows) cannot cast to UUID, so
    # remove it before the type change rather than failing the migration.
    op.execute(f"DELETE FROM {_TABLE} WHERE resource_id = 'all'")
    op.execute(f"ALTER TABLE {_TABLE} ALTER COLUMN resource_id TYPE UUID USING resource_id::uuid")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return
    op.execute(
        f"ALTER TABLE {_TABLE} ALTER COLUMN resource_id TYPE VARCHAR(36) USING resource_id::text"
    )
