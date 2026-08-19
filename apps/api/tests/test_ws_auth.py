"""Regression tests for websocket authentication session handling.

WebSockets stay open for a long time. websocket_auth must release the DB
session (and its pool connection) right after authenticating — otherwise the
connection pool exhausts after ~15 open sockets and every API request fails
with `QueuePool limit reached`.
"""

from types import SimpleNamespace

import pytest
from fastapi import WebSocketException


async def _make_user() -> str:
    from src.db.session import SessionFactory
    from src.services.auth import AuthService

    async with SessionFactory() as session:
        user = await AuthService(session).register(
            email="ws@example.com", password="Password123!", display_name="WS Tester"
        )
        return user.id


async def test_websocket_auth_releases_db_session():
    from src.api.deps import websocket_auth
    from src.core.security.tokens import create_access_token
    from src.db.session import SessionFactory, engine

    user_id = await _make_user()
    token = create_access_token(user_id)
    ws = SimpleNamespace(query_params={"token": token})

    async with SessionFactory() as db:
        user = await websocket_auth(ws, db)
        assert user.id == user_id
        # the critical part: the session's pool connection is returned before
        # the socket loop starts, so ~15+ open sockets can never exhaust the pool
        assert engine.sync_engine.pool.checkedout() == 0
        assert not db.in_transaction()


async def test_websocket_auth_rejects_missing_or_invalid_token():
    from src.api.deps import websocket_auth
    from src.db.session import SessionFactory

    async with SessionFactory() as db:
        with pytest.raises(WebSocketException):
            await websocket_auth(SimpleNamespace(query_params={}), db)
        with pytest.raises(WebSocketException):
            await websocket_auth(SimpleNamespace(query_params={"token": "not-a-real-token"}), db)
