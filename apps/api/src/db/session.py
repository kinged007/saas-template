from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.settings import settings

# Busy-wait (instead of failing immediately) when another connection holds a
# write lock — the in-process migration worker writes from a second session.
# NOTE: do NOT switch the journal to WAL here; WAL makes readers non-blocking,
# which silently changes reader-after-writer semantics relied on by tests and
# callers that expect a fresh read to see committed writes.
_connect_args = {"timeout": 30} if settings.resolved_database_url.startswith("sqlite") else {}

engine = create_async_engine(
    settings.resolved_database_url,
    echo=settings.debug,
    pool_pre_ping=True,
    connect_args=_connect_args,
)

SessionFactory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionFactory() as session:
        yield session
