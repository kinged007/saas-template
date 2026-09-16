"""Notification preferences, immediate email fallback, digests, unsubscribe."""

from __future__ import annotations


async def _me(client, tokens) -> dict:
    resp = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _prefs(client, tokens) -> dict:
    resp = await client.get(
        "/api/v1/notifications/preferences",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_preference_defaults_to_inapp(app_client):
    from tests.conftest import register_user

    tokens = await register_user(app_client, "pref1@example.com")
    assert await _prefs(app_client, tokens) == {"channels": {}, "digest_enabled": False}


async def test_put_preferences_roundtrip_and_validation(app_client):
    from tests.conftest import register_user

    tokens = await register_user(app_client, "pref2@example.com")
    resp = await app_client.put(
        "/api/v1/notifications/preferences",
        json={"channels": {"member_role_changed": "email"}, "digest_enabled": True},
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "channels": {"member_role_changed": "email"},
        "digest_enabled": True,
    }
    bad = await app_client.put(
        "/api/v1/notifications/preferences",
        json={"channels": {"member_role_changed": "carrier-pigeon"}},
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert bad.status_code == 422, bad.text


async def test_email_channel_sends_and_off_suppresses_row(app_client, monkeypatch):
    from sqlalchemy import func, select

    import src.email.factory as factory
    from src.db.session import SessionFactory
    from src.models.core import Notification
    from src.services.notifications import NotificationService
    from tests.conftest import register_user

    sent: list = []

    async def _send(msg):
        sent.append(msg)
        return True

    monkeypatch.setattr(factory, "send_email", _send)

    email_user = await register_user(app_client, "pref3@example.com")
    off_user = await register_user(app_client, "pref4@example.com")
    email_me = await _me(app_client, email_user)
    off_me = await _me(app_client, off_user)

    async with SessionFactory() as session:
        await NotificationService(session).upsert_channels(
            email_me["id"], {"member_role_changed": "email"}
        )
        await NotificationService(session).upsert_channels(
            off_me["id"], {"member_role_changed": "off"}
        )

    import src.workflows as workflows

    async with SessionFactory() as session:
        await workflows._create_notification(
            session,
            None,
            user_id=email_me["id"],
            workspace_id="0" * 32,
            type="member_role_changed",
            title="Your role changed",
            body="editor to viewer",
            metadata={},
        )
        await workflows._create_notification(
            session,
            None,
            user_id=off_me["id"],
            workspace_id="0" * 32,
            type="member_role_changed",
            title="Your role changed",
            body="editor to viewer",
            metadata={},
        )

    async with SessionFactory() as session:
        counts = (
            await session.execute(
                select(Notification.user_id, func.count())
                .where(Notification.type == "member_role_changed")
                .group_by(Notification.user_id)
            )
        ).all()
    by_user = dict(counts)
    assert by_user.get(email_me["id"]) == 1
    assert off_me["id"] not in by_user
    assert len(sent) == 1
    assert sent[0].to == "pref3@example.com"
    assert "unsubscribe?token=" in sent[0].text_body


async def test_digest_sends_unread_summary_when_enabled(app_client, monkeypatch):
    import src.email.factory as factory
    from src.db.session import SessionFactory
    from src.jobs.builtin import notifications_daily_digest
    from src.jobs.registry import JobContext
    from src.models.core import Notification
    from src.services.notifications import NotificationService
    from tests.conftest import register_user

    sent: list = []

    async def _send(msg):
        sent.append(msg)
        return True

    monkeypatch.setattr(factory, "send_email", _send)

    on_user = await register_user(app_client, "pref5@example.com")
    off_user = await register_user(app_client, "pref6@example.com")
    on_me = await _me(app_client, on_user)
    off_me = await _me(app_client, off_user)

    async with SessionFactory() as session:
        svc = NotificationService(session)
        await svc.upsert_channels(on_me["id"], {"member_joined": "in-app"})
        await svc.set_digest(on_me["id"], True)
        session.add_all(
            [
                Notification(
                    user_id=on_me["id"],
                    workspace_id="0" * 32,
                    type="member_joined",
                    title="A joined",
                    body="a",
                    payload={},
                ),
                Notification(
                    user_id=on_me["id"],
                    workspace_id="0" * 32,
                    type="member_joined",
                    title="B joined",
                    body="b",
                    payload={},
                ),
                Notification(
                    user_id=on_me["id"],
                    workspace_id="0" * 32,
                    type="conversation_message",
                    title="chat",
                    body="hi",
                    payload={},
                ),
                Notification(
                    user_id=off_me["id"],
                    workspace_id="0" * 32,
                    type="member_joined",
                    title="C joined",
                    body="c",
                    payload={},
                ),
            ]
        )
        await session.commit()

    await notifications_daily_digest(
        JobContext(
            run_id="r" * 32, job_key="notifications.daily_digest", workspace_id=None, params={}
        )
    )
    assert len(sent) == 1
    assert sent[0].to == "pref5@example.com"
    assert "A joined" in sent[0].text_body and "B joined" in sent[0].text_body
    assert "chat" not in sent[0].text_body


async def test_unsubscribe_token_disables_email(app_client):
    from sqlalchemy import select

    from src.db.session import SessionFactory
    from src.models.core import NotificationPreference
    from src.services.notifications import NotificationService
    from tests.conftest import register_user

    user = await register_user(app_client, "pref7@example.com")
    me = await _me(app_client, user)
    other = await register_user(app_client, "pref8@example.com")
    other_me = await _me(app_client, other)

    async with SessionFactory() as session:
        svc = NotificationService(session)
        await svc.upsert_channels(me["id"], {"member_joined": "email"})
        await svc.upsert_channels(other_me["id"], {"member_joined": "email"})
        token = await svc.token_for(me["id"], "member_joined")

    resp = await app_client.get(
        f"/api/v1/notifications/unsubscribe?token={token}&type=member_joined"
    )
    assert resp.status_code == 200, resp.text
    assert await _prefs(app_client, user) == {
        "channels": {"member_joined": "in-app"},
        "digest_enabled": False,
    }
    # Other user's rows untouched.
    async with SessionFactory() as session:
        row = (
            await session.execute(
                select(NotificationPreference).where(
                    NotificationPreference.user_id == other_me["id"],
                    NotificationPreference.type == "member_joined",
                )
            )
        ).scalar_one()
        assert row.channel == "email"

    bad = await app_client.get("/api/v1/notifications/unsubscribe?token=nope&type=all")
    assert bad.status_code == 404, bad.text
