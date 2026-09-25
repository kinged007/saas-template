"""Workspace delete cascade: no orphaned rows, registry enforced for new models.

Template convention: every table with a non-nullable `workspace_id` column
needs a WORKSPACE_CASCADE entry (or an EXEMPT entry with justification); the
registry test fails CI otherwise so future models cannot be silently missed.
AuditLogEntry is the one exemption (append-only compliance trail).
"""

from __future__ import annotations

from sqlalchemy import func, select

from src.db.base import Base
from src.db.cascade import EXEMPT_WORKSPACE_MODELS, WORKSPACE_CASCADE
from src.db.session import SessionFactory
from src.models.api_key import ApiKey
from src.models.audit import AuditLogEntry
from src.models.conversation import Conversation, ConversationParticipant, Message
from src.models.core import Invitation, Notification
from src.models.jobs import JobDefinition, JobLogEntry, JobRun, JobTrigger
from src.models.secret import StoredSecret
from src.models.webhook import WebhookDelivery, WebhookSubscription
from src.models.workspace import Role, User, Workspace, WorkspaceMember
from src.services.workspaces import WorkspaceService
from tests.bus_doubles import RecordingBus
from tests.conftest import auth_headers, create_workspace, register_user, ws_headers


def test_cascade_registry_covers_all_workspace_models():
    direct = {
        m.class_.__tablename__
        for m in Base.registry.mappers
        if hasattr(m.class_, "__tablename__") and "workspace_id" in m.class_.__table__.c
    }
    non_null = {
        m.class_.__tablename__
        for m in Base.registry.mappers
        if hasattr(m.class_, "__tablename__")
        and "workspace_id" in m.class_.__table__.c
        and m.class_.__table__.c["workspace_id"].nullable is False
    }
    covered = {m.__tablename__ for m in WORKSPACE_CASCADE}
    exempt = {m.__tablename__ for m in EXEMPT_WORKSPACE_MODELS}
    assert non_null - covered - exempt == set(), (
        f"workspace-scoped tables missing from WORKSPACE_CASCADE: "
        f"{sorted(non_null - covered - exempt)}"
    )
    assert direct - covered - exempt == set(), (
        f"workspace-scoped tables missing from WORKSPACE_CASCADE: "
        f"{sorted(direct - covered - exempt)}"
    )
    assert covered - direct == set(), (
        f"stale registry entries (no workspace_id column): {sorted(covered - direct)}"
    )


async def _counts(session, workspace_id: str) -> dict:
    async def n(model, col="workspace_id"):
        return (
            await session.execute(
                select(func.count()).select_from(model).where(getattr(model, col) == workspace_id)
            )
        ).scalar_one()

    out = {
        "api_keys": await n(ApiKey),
        "invitations": await n(Invitation),
        "secrets": await n(StoredSecret),
        "notifications": await n(Notification),
        "subscriptions": await n(WebhookSubscription),
        "deliveries": await n(WebhookDelivery),
        "members": await n(WorkspaceMember),
        "roles": await n(Role),
        "definitions": await n(JobDefinition),
        "conversations": await n(Conversation),
    }
    conv_ids = (
        (
            await session.execute(
                select(Conversation.id).where(Conversation.workspace_id == workspace_id)
            )
        )
        .scalars()
        .all()
    )
    out["messages"] = (
        (await session.execute(select(func.count()).select_from(Message))).scalar_one()
        if not conv_ids
        else (
            await session.execute(
                select(func.count())
                .select_from(Message)
                .where(Message.conversation_id.in_(conv_ids))
            )
        ).scalar_one()
    )
    out["participants"] = (
        (
            await session.execute(select(func.count()).select_from(ConversationParticipant))
        ).scalar_one()
        if not conv_ids
        else (
            await session.execute(
                select(func.count())
                .select_from(ConversationParticipant)
                .where(ConversationParticipant.conversation_id.in_(conv_ids))
            )
        ).scalar_one()
    )
    def_ids = (
        (
            await session.execute(
                select(JobDefinition.id).where(JobDefinition.workspace_id == workspace_id)
            )
        )
        .scalars()
        .all()
    )
    out["runs"] = (
        await session.execute(
            select(func.count()).select_from(JobRun).where(JobRun.workspace_id == workspace_id)
        )
    ).scalar_one() + (
        (
            await session.execute(
                select(func.count()).select_from(JobRun).where(JobRun.definition_id.in_(def_ids))
            )
        ).scalar_one()
        if def_ids
        else 0
    )
    out["logs"] = (
        await session.execute(
            select(func.count())
            .select_from(JobLogEntry)
            .join(JobRun, JobRun.id == JobLogEntry.run_id)
            .where(
                (JobRun.workspace_id == workspace_id)
                | (JobRun.definition_id.in_(def_ids) if def_ids else JobRun.definition_id.is_(None))
            )
        )
    ).scalar_one()
    out["audit"] = await n(AuditLogEntry)
    return out


async def _seed_workspace(session, workspace_id: str, owner: User, editor_role_id: str):
    from datetime import timedelta

    from src.core.dates import now_utc
    from src.models.conversation import Conversation
    from src.models.webhook import WebhookSubscription
    from src.services.api_keys import ApiKeyService

    await ApiKeyService(session).create_api_key(
        workspace_id=workspace_id, name="k", permissions=["*"], actor=owner
    )
    session.add(
        Invitation(
            workspace_id=workspace_id,
            email="pending@example.com",
            role_id=editor_role_id,
            invited_by_user_id=owner.id,
            token="tok-seed",
            status="pending",
            expires_at=now_utc() + timedelta(hours=1),
        )
    )
    session.add(Notification(workspace_id=workspace_id, user_id=owner.id, type="t", title="hi"))
    session.add(
        WebhookSubscription(workspace_id=workspace_id, url="https://example.com/h", events=[])
    )
    await session.flush()
    subs = (
        (
            await session.execute(
                select(WebhookSubscription).where(WebhookSubscription.workspace_id == workspace_id)
            )
        )
        .scalars()
        .all()
    )
    session.add(
        WebhookDelivery(
            subscription_id=subs[0].id,
            workspace_id=workspace_id,
            event_type="member.joined",
            subject="s",
            payload={},
        )
    )
    conv = Conversation(workspace_id=workspace_id, created_by_user_id=owner.id, title="c")
    session.add(conv)
    await session.flush()
    session.add(
        Message(conversation_id=conv.id, sender_type="user", sender_id=owner.id, body="hello")
    )
    session.add(
        ConversationParticipant(
            conversation_id=conv.id,
            participant_type="user",
            participant_id=owner.id,
            user_id=owner.id,
            joined_at=now_utc(),
        )
    )
    await session.flush()


async def test_delete_removes_all_workspace_rows(app_client):
    from src.services.auth import AuthService

    client = app_client
    owner_tokens = await register_user(client, "cascade-owner@example.com")
    await register_user(client, "cascade-member@example.com")
    owner_id = (await client.get("/api/v1/auth/me", headers=auth_headers(owner_tokens))).json()[
        "id"
    ]
    ws = await create_workspace(client, owner_tokens, name="Cascade WS")

    async with SessionFactory() as session:
        svc = WorkspaceService(session)
        roles = await svc.list_roles(ws["id"])
        editor = next(r for r in roles if r.name == "editor")
        member_user = await AuthService(session).get_by_email("cascade-member@example.com")
        session.add(
            WorkspaceMember(
                workspace_id=ws["id"], user_id=member_user.id, role_id=editor.id, status="active"
            )
        )
        await session.commit()
        owner = await AuthService(session).get_user(owner_id)
        await _seed_workspace(session, ws["id"], owner, editor.id)
        # Workspace-scoped job definition + run + log
        from src.core.dates import now_utc
        from src.jobs.registry import register_builtin_jobs
        from src.services.jobs import JobService

        register_builtin_jobs()
        await JobService(session).sync_definitions(workspace_ids=[ws["id"]])
        defn = (
            await session.execute(
                select(JobDefinition).where(
                    JobDefinition.workspace_id == ws["id"],
                    JobDefinition.key == "invitations.expire_stale",
                )
            )
        ).scalar_one()
        run = JobRun(definition_id=defn.id, workspace_id=ws["id"], scheduled_at=now_utc())
        session.add(run)
        await session.flush()
        session.add(JobLogEntry(run_id=run.id, seq=0, ts=now_utc(), level="INFO", message="x"))
        await session.commit()
        before = await _counts(session, ws["id"])
    assert before["members"] >= 2 and before["roles"] >= 4 and before["api_keys"] == 1
    assert before["messages"] == 1 and before["runs"] >= 1 and before["logs"] == 1

    resp = await client.delete(
        "/api/v1/workspaces/" + ws["id"], headers=ws_headers(owner_tokens, ws["id"])
    )
    assert resp.status_code == 204, resp.text

    async with SessionFactory() as session:
        after = await _counts(session, ws["id"])
    for table, count in after.items():
        if table == "audit":
            continue  # append-only compliance trail, exempt by design
        assert count == 0, f"{table} left {count} orphaned rows"

    # Follow-up GET is 404 (not 403), users survive.
    resp = await client.get(
        "/api/v1/workspaces/" + ws["id"], headers=ws_headers(owner_tokens, ws["id"])
    )
    assert resp.status_code == 404
    async with SessionFactory() as session:
        assert await session.get(User, owner_id) is not None
        assert await session.get(Workspace, ws["id"]) is None


async def test_delete_unknown_workspace_is_404(app_client):
    client = app_client
    tokens = await register_user(client, "cascade-404@example.com")
    resp = await client.delete(
        "/api/v1/workspaces/00000000-0000-0000-0000-000000000000",
        headers=ws_headers(tokens, "00000000-0000-0000-0000-000000000000"),
    )
    assert resp.status_code == 404


async def test_scheduler_skips_deleted_workspace_definitions():
    """A due definition whose workspace is gone schedules nothing (no resurrection)."""
    from src.core.dates import now_utc
    from src.jobs.registry import register_builtin_jobs
    from src.services.auth import AuthService
    from src.services.jobs import JobService

    register_builtin_jobs()
    bus = RecordingBus()
    async with SessionFactory() as session:
        owner = await AuthService(session, bus).register(
            email="sched-owner@example.com", password="Password123!", first_name="S", last_name="O"
        )
        ws = await WorkspaceService(session, bus).create_workspace(
            name="Sched WS", slug="sched-ws", description=None, owner=owner
        )
        ws_id = ws.id
        await JobService(session).sync_definitions(workspace_ids=[ws_id])
        defn = (
            await session.execute(
                select(JobDefinition).where(
                    JobDefinition.workspace_id == ws_id,
                    JobDefinition.key == "invitations.expire_stale",
                )
            )
        ).scalar_one()
        # Force due in the past.
        from datetime import timedelta

        defn.enabled = True
        defn.next_run_at = now_utc() - timedelta(minutes=5)
        await session.commit()
        await WorkspaceService(session, bus).delete_workspace(ws_id, actor=owner)
        # Re-insert a stale definition row pointing at the deleted workspace,
        # simulating a definition created just before the delete committed.
        stale = JobDefinition(
            key="invitations.expire_stale",
            workspace_id=ws_id,
            name="stale",
            cron_schedule="* * * * *",
            enabled=True,
            next_run_at=now_utc() - timedelta(minutes=5),
        )
        session.add(stale)
        await session.commit()
        scheduled = await JobService(session, bus).schedule_due()
        assert scheduled == 0
        runs = (
            await session.execute(
                select(func.count()).select_from(JobRun).where(JobRun.workspace_id == ws_id)
            )
        ).scalar_one()
        assert runs == 0


async def test_create_run_refuses_deleted_workspace(app_client):
    """create_run raises JobError for a definition pointing at a deleted workspace."""
    from src.jobs.registry import register_builtin_jobs
    from src.services.auth import AuthService
    from src.services.jobs import JobError, JobService

    register_builtin_jobs()
    bus = RecordingBus()
    async with SessionFactory() as session:
        owner = await AuthService(session, bus).register(
            email="refuse-owner@example.com",
            password="Password123!",
            first_name="R",
            last_name="O",
        )
        ws = await WorkspaceService(session, bus).create_workspace(
            name="Refuse WS", slug="refuse-ws", description=None, owner=owner
        )
        ws_id = ws.id
        await JobService(session).sync_definitions(workspace_ids=[ws_id])
        await WorkspaceService(session, bus).delete_workspace(ws_id, actor=owner)
        stale = JobDefinition(
            key="invitations.expire_stale",
            workspace_id=ws_id,
            name="stale",
            cron_schedule="* * * * *",
            enabled=True,
        )
        session.add(stale)
        await session.flush()
        try:
            await JobService(session, bus).create_run(stale, trigger=JobTrigger.MANUAL)
        except JobError:
            pass
        else:
            raise AssertionError("create_run should refuse a deleted workspace")
        finally:
            await session.rollback()


async def test_global_definitions_survive_workspace_delete(app_client):
    """Global (workspace_id NULL) definitions are untouched by a workspace delete."""
    from src.jobs.registry import register_builtin_jobs
    from src.services.auth import AuthService
    from src.services.jobs import JobService

    register_builtin_jobs()
    bus = RecordingBus()
    async with SessionFactory() as session:
        owner = await AuthService(session, bus).register(
            email="global-owner@example.com",
            password="Password123!",
            first_name="G",
            last_name="O",
        )
        ws = await WorkspaceService(session, bus).create_workspace(
            name="Global WS", slug="global-ws", description=None, owner=owner
        )
        ws_id = ws.id
        await JobService(session).sync_definitions(workspace_ids=[ws_id])
        before = (
            await session.execute(
                select(func.count())
                .select_from(JobDefinition)
                .where(JobDefinition.workspace_id.is_(None))
            )
        ).scalar_one()
        assert before >= 1
        await WorkspaceService(session, bus).delete_workspace(ws_id, actor=owner)
        after = (
            await session.execute(
                select(func.count())
                .select_from(JobDefinition)
                .where(JobDefinition.workspace_id.is_(None))
            )
        ).scalar_one()
        assert after == before
