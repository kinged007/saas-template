"""Dev seed: demo users, workspaces, memberships, invitations, notifications, api keys.

Idempotent — safe to run repeatedly.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import NamedTuple

from sqlalchemy import select

from src.core.dates import now_utc
from src.core.routes import INVITATIONS_ROUTE
from src.db.session import SessionFactory
from src.models.api_key import ApiKey
from src.models.core import Invitation, Notification
from src.models.workspace import Role, User, Workspace, WorkspaceMember
from src.services.api_keys import ApiKeyForbidden, ApiKeyService
from src.services.auth import AuthService
from src.services.workspaces import WorkspaceService
from src.settings import settings

logger = logging.getLogger(__name__)

DEMO_PASSWORD = "password"

DEMO_USERS = [
    ("admin@example.com", "Admin", "User"),
    ("user1@example.com", "User", "One"),
    ("user2@example.com", "User", "Two"),
]

WORKSPACES = [
    {
        "name": "Acme Corp",
        "slug": "acme-corp",
        "description": "Demo workspace",
    },
    {
        "name": "Globex",
        "slug": "globex",
        "description": "Second demo workspace",
    },
]


# Every fixture row is a NamedTuple with slug and email in the same leading
# order, built by keyword in the fixture constants below. `_check_fixtures`
# reads `row.slug` / `row.email` by name, so a row whose two strings are
# transposed is reported against the field it actually carries, with the row
# itself in the message.
class MembershipRow(NamedTuple):
    slug: str
    email: str
    role: str


class InvitationRow(NamedTuple):
    slug: str
    email: str
    role: str


class ApiKeyRow(NamedTuple):
    slug: str
    email: str
    name: str
    permissions: list[str]


class NotificationRow(NamedTuple):
    slug: str
    email: str
    type: str
    title: str
    body: str
    acknowledged: bool
    age_hours: int


# The workspace owner is added by create_workspace.
MEMBERSHIPS = [
    MembershipRow(slug="acme-corp", email="user1@example.com", role="editor"),
    MembershipRow(slug="globex", email="user1@example.com", role="viewer"),
]

# Pending invitations shown in the members page.
INVITATIONS = [
    InvitationRow(slug="acme-corp", email="user2@example.com", role="viewer"),
    InvitationRow(slug="globex", email="user2@example.com", role="editor"),
]

# Permissions are validated against the creator's role by ApiKeyService —
# they must be a subset of what the creator can do, except key-only scopes
# (notification:*) which any member may hold on a key. Raw secrets are printed
# once, at creation time; re-running the seed keeps existing keys untouched.
API_KEYS = [
    ApiKeyRow(
        slug="acme-corp",
        email="admin@example.com",
        name="ci-deploy",
        permissions=["member:read", "role:read"],
    ),
    ApiKeyRow(
        slug="acme-corp",
        email="admin@example.com",
        name="automation",
        permissions=[
            "workspace:read",
            "workspace:update",
            "member:read",
            "member:update",
            "member:delete",
            "role:read",
            "role:create",
            "apikey:read",
            "apikey:create",
            "apikey:delete",
            "notification:read",
            "notification:update",
        ],
    ),
    ApiKeyRow(
        slug="acme-corp",
        email="user1@example.com",
        name="editor-script",
        permissions=["member:read", "role:read", "notification:read"],
    ),
    ApiKeyRow(
        slug="globex",
        email="user1@example.com",
        name="viewer-read",
        permissions=["member:read"],
    ),
]


def _notifications() -> list[NotificationRow]:
    return [
        # ---- admin — Acme Corp ----
        NotificationRow(
            slug="acme-corp",
            email="admin@example.com",
            type="workspace_invitation",
            title="New invitation sent",
            body="You invited user2@example.com to Acme Corp as a viewer.",
            acknowledged=False,
            age_hours=2,
        ),
        # ---- admin — Globex ----
        NotificationRow(
            slug="globex",
            email="admin@example.com",
            type="workspace_invitation",
            title="New invitation sent",
            body="You invited user2@example.com to Globex as an editor.",
            acknowledged=False,
            age_hours=1,
        ),
        # ---- user1 — Acme Corp + Globex ----
        NotificationRow(
            slug="acme-corp",
            email="user1@example.com",
            type="workspace_invitation",
            title="You were invited to Acme Corp",
            body="Admin User invited you to the Acme Corp workspace.",
            acknowledged=False,
            age_hours=6,
        ),
        NotificationRow(
            slug="globex",
            email="user1@example.com",
            type="workspace_invitation",
            title="You were invited to Globex",
            body="Admin User invited you to the Globex workspace.",
            acknowledged=False,
            age_hours=3,
        ),
        # ---- user2 — invited to both workspaces ----
        NotificationRow(
            slug="acme-corp",
            email="user2@example.com",
            type="workspace_invitation",
            title="You were invited to Acme Corp",
            body="Admin User invited you to the Acme Corp workspace.",
            acknowledged=False,
            age_hours=2,
        ),
        NotificationRow(
            slug="globex",
            email="user2@example.com",
            type="workspace_invitation",
            title="You were invited to Globex",
            body="Admin User invited you to the Globex workspace.",
            acknowledged=False,
            age_hours=1,
        ),
    ]


def _check_fixtures() -> None:
    """Every fixture row must name a slug the seed defines, and a user it owns.

    The `slug not in workspaces` guard in each loop is the single-workspace and
    foreign-workspace skip, and it stays: a known slug can legitimately be absent
    from a run. A slug that is in no fixture at all is a typo, and skipping it
    ships a demo quietly missing rows.

    The email check applies only where the loop reads `users[row.email]`
    (members, api keys, notifications), where an unknown email is a bare
    KeyError. `INVITATIONS` invites an address that need not be registered yet —
    that is the accept-invitation flow — so only its slug is checked.
    """
    slugs = {spec["slug"] for spec in WORKSPACES}
    emails = {email for email, _, _ in DEMO_USERS}
    # `checks_email` mirrors which loop reads `users[row.email]`;
    # test_email_check_covers_exactly_the_loops_that_read_users asserts it.
    for name, fixture, checks_email in (
        ("memberships", MEMBERSHIPS, True),
        ("invitations", INVITATIONS, False),
        ("api keys", API_KEYS, True),
        ("notifications", _notifications(), True),
    ):
        for row in fixture:
            # The row is in the message because a wrong slug and a transposed
            # slug/email row look identical from the offending value alone.
            if row.slug not in slugs:
                raise RuntimeError(
                    f"{name} fixture names unknown workspace slug {row.slug!r} in row {row!r}"
                )
            if checks_email and row.email not in emails:
                raise RuntimeError(
                    f"{name} fixture names unknown user email {row.email!r} in row {row!r}"
                )


async def main() -> None:
    _check_fixtures()

    async with SessionFactory() as session:
        auth = AuthService(session)
        ws_service = WorkspaceService(session)

        changed_roles = await ws_service.sync_system_role_permissions()
        if changed_roles:
            logger.info("updated %d system role(s) to current defaults", changed_roles)

        users: dict[str, User] = {}
        for email, first_name, last_name in DEMO_USERS:
            user = await auth.get_by_email(email)
            if user is None:
                user = await auth.register(
                    email=email,
                    password=DEMO_PASSWORD,
                    first_name=first_name,
                    last_name=last_name,
                )
                logger.info("created demo user %s", email)
            users[email] = user

        # Dev-only ceiling: only when SUPERADMIN_EMAIL is unset. A set value
        # means the bootstrap account (via register) is the real superuser.
        admin = users["admin@example.com"]
        if not settings.superadmin_email.strip() and not admin.is_superuser:
            admin.is_superuser = True
            logger.info("promoted admin@example.com to superuser")

        workspaces: dict[str, Workspace] = {}
        if settings.single_workspace:
            # The canonical workspace is the oldest existing row, not the
            # demo fixture: a developer who registered before the first seed
            # already owns it. Fixture-keyed demo data is only attached when
            # that workspace is still empty of other owners — attaching it to
            # a workspace someone else created would mix demo API keys,
            # invitations and notifications into their real data.
            workspace = await ws_service.get_single_workspace()
            if workspace is None:
                spec = WORKSPACES[0]
                workspace = await ws_service.create_workspace(
                    name=spec["name"],
                    slug=spec["slug"],
                    description=spec["description"],
                    owner=users["admin@example.com"],
                )
                logger.info("created demo workspace %s", spec["slug"])
                workspaces[WORKSPACES[0]["slug"]] = workspace
            else:
                owner = await session.scalar(
                    select(WorkspaceMember).where(
                        WorkspaceMember.workspace_id == workspace.id,
                        WorkspaceMember.role_id
                        == await _system_role_id(session, workspace.id, "owner"),
                    )
                )
                if owner is None or owner.user_id == users["admin@example.com"].id:
                    workspaces[WORKSPACES[0]["slug"]] = workspace
        else:
            for spec in WORKSPACES:
                result = await session.execute(
                    select(Workspace).where(Workspace.slug == spec["slug"])
                )
                workspace = result.scalar_one_or_none()
                if workspace is None:
                    workspace = await ws_service.create_workspace(
                        name=spec["name"],
                        slug=spec["slug"],
                        description=spec["description"],
                        owner=users["admin@example.com"],
                    )
                    logger.info("created demo workspace %s", spec["slug"])
                workspaces[spec["slug"]] = workspace

        for slug, email, role_name in MEMBERSHIPS:
            if slug not in workspaces:
                continue
            workspace = workspaces[slug]
            member = await session.execute(
                select(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == workspace.id,
                    WorkspaceMember.user_id == users[email].id,
                )
            )
            if member.scalar_one_or_none() is not None:
                continue
            role = await _role_by_name(session, workspace.id, role_name)
            session.add(
                WorkspaceMember(
                    workspace_id=workspace.id,
                    user_id=users[email].id,
                    role_id=role.id,
                    status="active",
                )
            )
            logger.info("added %s to %s as %s", email, slug, role_name)

        api_keys: list[tuple[str, str, str]] = []
        api_service = ApiKeyService(session)
        for slug, email, name, permissions in API_KEYS:
            if slug not in workspaces:
                continue
            workspace = workspaces[slug]
            user = users[email]
            # A name may label several rows (key rotation mints a new row
            # carrying the old name), so the idempotency check reads the newest
            # one instead of assuming the name is unique.
            existing = await session.execute(
                select(ApiKey)
                .where(ApiKey.workspace_id == workspace.id, ApiKey.name == name)
                .order_by(ApiKey.created_at.desc())
                .limit(1)
            )
            if existing.scalar_one_or_none() is not None:
                continue
            # Row existence, not an active membership: a suspended row still counts.
            if not await ws_service.has_member_row(workspace.id, user.id):
                # The canonical workspace pre-existed and its owner is not the
                # demo admin, who never auto-joins (no login event yet).
                logger.info("skipped api key %s in %s: %s is not a member", name, slug, email)
                continue
            try:
                key, raw = await api_service.create_api_key(
                    workspace_id=workspace.id,
                    name=name,
                    permissions=permissions,
                    actor=user,
                )
            except ApiKeyForbidden as exc:
                # The guard above is status blind, so a suspended row passes it
                # while the mint — active members only — refuses. A refusal for
                # any other reason (the role cannot grant what API_KEYS asks
                # for) is a fixture bug and stays fatal.
                if await ws_service.get_membership(workspace.id, user.id) is not None:
                    raise
                logger.info("skipped api key %s in %s: %s", name, slug, exc)
                continue
            api_keys.append((name, slug, raw))
            logger.info("created api key %s in %s", name, slug)

        invitations: dict[tuple[str, str], Invitation] = {}
        for slug, email, role_name in INVITATIONS:
            if slug not in workspaces:
                continue
            workspace = workspaces[slug]
            # At most one pending invite is expected per address, but a
            # re-invite can leave several rows behind; read the newest one so
            # a repeat seed never trips on duplicates.
            existing = await session.execute(
                select(Invitation)
                .where(
                    Invitation.workspace_id == workspace.id,
                    Invitation.email == email,
                    Invitation.status == "pending",
                )
                .order_by(Invitation.created_at.desc())
                .limit(1)
            )
            invite = existing.scalar_one_or_none()
            if invite is None:
                role = await _role_by_name(session, workspace.id, role_name)
                invite = await ws_service.create_invitation(
                    workspace=workspace,
                    email=email,
                    role=role,
                    invited_by=users["admin@example.com"],
                )
                logger.info("invited %s to %s as %s", email, slug, role_name)
            invitations[(slug, email)] = invite

        now = now_utc()
        for slug, email, type_, title, body, acknowledged, age_hours in _notifications():
            if slug not in workspaces:
                continue
            user = users[email]
            workspace = workspaces[slug]
            existing = await session.execute(
                select(Notification)
                .where(
                    Notification.user_id == user.id,
                    Notification.workspace_id == workspace.id,
                    Notification.title == title,
                )
                .order_by(Notification.created_at.desc())
                .limit(1)
            )
            if existing.scalar_one_or_none() is not None:
                continue
            invite = invitations.get((slug, email))
            payload: dict = {"workspace_id": workspace.id, "workspace_name": workspace.name}
            if type_ == "workspace_invitation":
                # NotificationCenter renders an "Open" button only when the
                # payload carries a url; without it the invite is a dead end.
                # /invitations is a static frontend route, so it does not
                # depend on a live invitation row. Mirrors the workflow path
                # (workflows.on_member_invited), which sets the same url.
                payload["url"] = INVITATIONS_ROUTE
                if invite is not None:
                    payload.update({"invitation_id": invite.id, "invited_by": "Admin User"})
            created_at = now - timedelta(hours=age_hours)
            session.add(
                Notification(
                    user_id=user.id,
                    workspace_id=workspace.id,
                    type=type_,
                    title=title,
                    body=body,
                    payload=payload,
                    created_at=created_at,
                    updated_at=created_at,
                    acknowledged_at=created_at if acknowledged else None,
                )
            )
            logger.info("created %s notification for %s in %s", type_, email, slug)

        await session.commit()

    print("seed complete — demo login (all users share this password):")
    print(f"  password: {DEMO_PASSWORD}")
    for email, first_name, last_name in DEMO_USERS:
        display = f"{first_name} {last_name[0].upper()}." if last_name else first_name
        print(f"  {email:<28} {display}")
    if api_keys:
        print("  api keys (secrets shown once, at creation):")
        for name, slug, raw in api_keys:
            print(f"    {name:<16} ({slug}) {raw}")


async def _system_role_id(session, workspace_id: str, name: str) -> str:
    return (await _role_by_name(session, workspace_id, name)).id


async def _role_by_name(session, workspace_id: str, name: str) -> Role:
    result = await session.execute(
        select(Role).where(Role.workspace_id == workspace_id, Role.name == name)
    )
    role = result.scalar_one_or_none()
    if role is None:
        raise RuntimeError(f"role {name} not found in workspace {workspace_id}")
    return role


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)  # nothing else in this path configures it
    asyncio.run(main())
