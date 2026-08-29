"""Regression tests for websocket authentication session handling.

WebSockets stay open for a long time. The socket route must release the DB
session (and its pool connection) right after authenticating — otherwise the
connection pool exhausts after ~15 open sockets and every API request fails
with `QueuePool limit reached`.
"""

import pytest


async def _make_user() -> str:
    from src.db.session import SessionFactory
    from src.services.auth import AuthService

    async with SessionFactory() as session:
        user = await AuthService(session).register(
            email="ws@example.com", password="Password123!", display_name="WS Tester"
        )
        return user.id


async def test_websocket_token_auth_releases_db_session():
    from src.api.deps import authenticate_websocket_token
    from src.core.security.tokens import create_access_token
    from src.db.session import SessionFactory, engine

    user_id = await _make_user()
    token = create_access_token(user_id)

    async with SessionFactory() as db:
        user = await authenticate_websocket_token(db, token)
        assert user is not None and user.id == user_id
    # the critical part: once the auth session closes, its pool connection is
    # returned before the socket loop starts, so ~15+ open sockets can never
    # exhaust the pool
    assert engine.sync_engine.pool.checkedout() == 0


async def test_websocket_token_auth_rejects_missing_or_invalid_token():
    from src.api.deps import authenticate_websocket_token
    from src.db.session import SessionFactory

    async with SessionFactory() as db:
        assert await authenticate_websocket_token(db, None) is None
        assert await authenticate_websocket_token(db, "not-a-real-token") is None
