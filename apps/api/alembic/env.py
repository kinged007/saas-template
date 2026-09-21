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
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # compare_type would flag every legacy VARCHAR-vs-String spelling
        # and every StringUUID-vs-VARCHAR reflection as drift, even though
        # the live schema is correct — real type changes ship as explicit
        # migrations, reviewed by a human (see docs/MIGRATIONS.md).
        # compare_server_default stays off for the same reason: restored
        # JSON/text defaults render as '[]'::json vs text('[]') noise.
        compare_type=False,
        compare_server_default=False,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(settings.resolved_database_url, pool_pre_ping=True)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
        # In async mode `context.begin_transaction()` does not always auto-commit
        # on `engine.dispose()` — explicitly commit so migrations are visible to
        # other connections (fixes fresh DB where `alembic upgrade head` would
        # otherwise appear to run but leave no tables).
        try:
            await connection.commit()
        except Exception:
            pass
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
