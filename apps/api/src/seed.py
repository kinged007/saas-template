"""Dev seed: demo users, workspaces, memberships, invitations, notifications, api keys.

Idempotent — safe to run repeatedly.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import select

from src.core.dates import now_utc
from src.db.session import SessionFactory
from src.models.api_key import ApiKey
from src.models.core import Invitation, Notification
from src.models.workspace import Role, User, Workspace, WorkspaceMember
from src.services.api_keys import ApiKeyService
from src.services.auth import AuthService
from src.services.workspaces import WorkspaceService
from src.settings import settings
from src.workflows import INVITATIONS_ROUTE

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

# (workspace slug, user email, role) — the owner is added by create_workspace.
MEMBERSHIPS = [
    ("acme-corp", "user1@example.com", "editor"),
    ("globex", "user1@example.com", "viewer"),
]

# (workspace slug, email, role) — pending invitations shown in the members page.
INVITATIONS = [
    ("acme-corp", "user2@example.com", "viewer"),
    ("globex", "user2@example.com", "editor"),
]

# (workspace slug, creator email, name, permissions).
# Permissions are validated against the creator's role by ApiKeyService —
# they must be a subset of what the creator can do, except key-only scopes
# (notification:*) which any member may hold on a key. Raw secrets are printed
# once, at creation time; re-running the seed keeps existing keys untouched.
API_KEYS = [
    (
        "acme-corp",
        "admin@example.com",
        "ci-deploy",
        ["member:read", "role:read"],
    ),
    (
        "acme-corp",
        "admin@example.com",
        "automation",
        [
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
    (
        "acme-corp",
        "user1@example.com",
        "editor-script",
        ["member:read", "role:read", "notification:read"],
    ),
    (
        "globex",
        "user1@example.com",
        "viewer-read",
        ["member:read"],
    ),
]


def _notifications() -> list[tuple[str, str, str, str, str, bool, int]]:
    """(user email, workspace slug, type, title, body, acknowledged, age_hours)."""
    return [
        # ---- admin — Acme Corp ----
        (
            "admin@example.com",
            "acme-corp",
            "workspace_invitation",
            "New invitation sent",
            "You invited user2@example.com to Acme Corp as a viewer.",
            False,
            2,
        ),
        # ---- admin — Globex ----
        (
            "admin@example.com",
            "globex",
            "workspace_invitation",
            "New invitation sent",
            "You invited user2@example.com to Globex as an editor.",
            False,
            1,
        ),
        # ---- user1 — Acme Corp + Globex ----
        (
            "user1@example.com",
            "acme-corp",
            "workspace_invitation",
            "You were invited to Acme Corp",
            "Admin User invited you to the Acme Corp workspace.",
            False,
            6,
        ),
        (
            "user1@example.com",
            "globex",
            "workspace_invitation",
            "You were invited to Globex",
            "Admin User invited you to the Globex workspace.",
            False,
            3,
        ),
        # ---- user2 — invited to both workspaces ----
        (
            "user2@example.com",
            "acme-corp",
            "workspace_invitation",
            "You were invited to Acme Corp",
            "Admin User invited you to the Acme Corp workspace.",
            False,
            2,
        ),
        (
            "user2@example.com",
            "globex",
            "workspace_invitation",
            "You were invited to Globex",
            "Admin User invited you to the Globex workspace.",
            False,
            1,
        ),
    ]


def _check_fixtures() -> None:
    """Every fixture row must name a slug the seed defines, and a user it owns.

    The `slug not in workspaces` guard in each loop is the single-workspace and
    foreign-workspace skip, and it stays: a known slug can legitimately be absent
    from a run. A slug that is in no fixture at all is a typo, and skipping it
    ships a demo quietly missing rows.

    The email check applies only where the loop reads `users[email]` (members,
    api keys, notifications), where an unknown email is a bare KeyError.
    `INVITATIONS` invites an address that need not be registered yet — that is
    the accept-invitation flow — so only its slug is checked.
    """
    slugs = {spec["slug"] for spec in WORKSPACES}
    emails = {email for email, _, _ in DEMO_USERS}
    # (fixture name, slug, email to check or None) — notification rows are
    # (email, slug, ...).
    rows = [
        (name, slug, email if checks_email else None)
        for name, fixture, checks_email in (
            ("memberships", MEMBERSHIPS, True),
            ("invitations", INVITATIONS, False),
            ("api keys", API_KEYS, True),
        )
        for slug, email, *_ in fixture
    ]
    rows += [("notifications", slug, email) for email, slug, *_ in _notifications()]
    for name, slug, email in rows:
        if slug not in slugs:
            raise RuntimeError(f"{name} fixture names unknown workspace slug {slug!r}")
        if email is not None and email not in emails:
            raise RuntimeError(f"{name} fixture names unknown user email {email!r}")


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
            existing = await session.execute(
                select(ApiKey).where(ApiKey.workspace_id == workspace.id, ApiKey.name == name)
            )
            if existing.scalar_one_or_none() is not None:
                continue
            # `active_only=False`: the question is whether a member row exists
            # for the demo admin at all, and a suspended row is still a row.
            if await ws_service.get_membership(workspace.id, user.id, active_only=False) is None:
                # The canonical workspace pre-existed and its owner is not the
                # demo admin, who never auto-joins (no login event yet).
                logger.info("skipped api key %s in %s: %s is not a member", name, slug, email)
                continue
            key, raw = await api_service.create_api_key(
                workspace_id=workspace.id,
                name=name,
                permissions=permissions,
                actor=user,
            )
            api_keys.append((name, slug, raw))
            logger.info("created api key %s in %s", name, slug)

        invitations: dict[tuple[str, str], Invitation] = {}
        for slug, email, role_name in INVITATIONS:
            if slug not in workspaces:
                continue
            workspace = workspaces[slug]
            existing = await session.execute(
                select(Invitation).where(
                    Invitation.workspace_id == workspace.id,
                    Invitation.email == email,
                    Invitation.status == "pending",
                )
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
        for email, slug, type_, title, body, acknowledged, age_hours in _notifications():
            if slug not in workspaces:
                continue
            user = users[email]
            workspace = workspaces[slug]
            existing = await session.execute(
                select(Notification).where(
                    Notification.user_id == user.id,
                    Notification.workspace_id == workspace.id,
                    Notification.title == title,
                )
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
    asyncio.run(main())
