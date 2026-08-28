from __future__ import annotations

import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context

# Ensure the api/ directory is on sys.path so `src` is importable.
_API_ROOT = str(Path(__file__).resolve().parents[1])
if _API_ROOT not in sys.path:
    sys.path.insert(0, _API_ROOT)

from src import models  # noqa: E402,F401  (register models with metadata)
from src.db.base import Base  # noqa: E402
from src.settings import settings  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.resolved_database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    # If the database was created via Base.metadata.create_all (e.g. embedded
    # postgres dev DB or tests that used create_all) the alembic_version table
    # may be missing while the schema already exists. In that case a plain
    # `alembic upgrade head` would try to re-create `users` and fail with
    # DuplicateTableError. Detect this situation and stamp the DB to the
    # appropriate head instead of re-running all migrations.
    try:
        from sqlalchemy import inspect, text as sa_text

        inspector = inspect(connection)
        has_version = inspector.has_table("alembic_version")
        has_users = inspector.has_table("users")
        if not has_version and has_users:
            has_conversations = inspector.has_table("conversations")
            # Determine the revision to stamp: if the new tables already exist
            # the DB is effectively at head; otherwise stamp to 0004 so the
            # next run will apply 0005 normally.
            from alembic.script import ScriptDirectory

            script = ScriptDirectory.from_config(context.config)
            head = script.get_current_head()
            # Fallback to latest known if script lookup fails (offline generation).
            if head is None:
                head = "0005"
            target = head if has_conversations else "0004"
            # The inspection queries above may have left an implicit transaction
            # open (SQLAlchemy 2.0 autobegin). Close it before starting our
            # explicit stamp transaction.
            if connection.in_transaction():
                connection.rollback()
            with connection.begin():
                connection.execute(
                    sa_text(
                        "CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL, CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
                    )
                )
                # Clear any stale rows then insert target.
                connection.execute(sa_text("DELETE FROM alembic_version"))
                connection.execute(
                    sa_text("INSERT INTO alembic_version (version_num) VALUES (:v)"),
                    {"v": target},
                )
            # If we stamped to head we are done; otherwise the subsequent
            # context.run_migrations() will correctly apply the remaining
            # migrations (e.g. 0005).
            if target == head:
                return
    except Exception:
        # Never block migrations on a stamp failure; fall through to normal
        # Alembic flow which will surface the real error.
        pass

    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(settings.resolved_database_url, pool_pre_ping=True)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
        # Ensure any transaction started by context.begin_transaction() is
        # committed. In some async contexts the transaction may not auto-commit
        # on dispose, leaving tables invisible to other connections.
        try:
            await connection.commit()
        except Exception:
            pass
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
