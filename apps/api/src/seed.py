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

logger = logging.getLogger(__name__)

DEMO_PASSWORD = "password"
ADMIN_EMAIL = f"admin@{settings.seed_email_domain}"
USER1_EMAIL = f"user1@{settings.seed_email_domain}"
USER2_EMAIL = f"user2@{settings.seed_email_domain}"
ADMIN_DISPLAY_NAME = "Admin User"

DEMO_USERS = [
    (ADMIN_EMAIL, "Admin", "User"),
    (USER1_EMAIL, "User", "One"),
    (USER2_EMAIL, "User", "Two"),
]

WORKSPACES = settings.seed_workspace_specs
FIRST_WORKSPACE, SECOND_WORKSPACE = WORKSPACES

# (workspace slug, user email, role) — the owner is added by create_workspace.
MEMBERSHIPS = [
    (FIRST_WORKSPACE["slug"], USER1_EMAIL, "editor"),
    (SECOND_WORKSPACE["slug"], USER1_EMAIL, "viewer"),
]

# (workspace slug, email, role) — pending invitations shown in the members page.
INVITATIONS = [
    (FIRST_WORKSPACE["slug"], USER2_EMAIL, "viewer"),
    (SECOND_WORKSPACE["slug"], USER2_EMAIL, "editor"),
]

# (workspace slug, creator email, name, permissions).
# Permissions are validated against the creator's role by ApiKeyService —
# they must be a subset of what the creator can do. Raw secrets are printed
# once, at creation time; re-running the seed keeps existing keys untouched.
API_KEYS = [
    (
        FIRST_WORKSPACE["slug"],
        ADMIN_EMAIL,
        "ci-deploy",
        ["member:read", "role:read"],
    ),
    (
        FIRST_WORKSPACE["slug"],
        ADMIN_EMAIL,
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
        FIRST_WORKSPACE["slug"],
        USER1_EMAIL,
        "editor-script",
        ["member:read", "role:read", "notification:read"],
    ),
    (
        SECOND_WORKSPACE["slug"],
        USER1_EMAIL,
        "viewer-read",
        ["member:read"],
    ),
]


def _notifications() -> list[dict]:
    """(user email, workspace slug, type, title, body, acknowledged, age_hours)."""
    first_name = FIRST_WORKSPACE["name"]
    second_name = SECOND_WORKSPACE["name"]
    return [
        (
            ADMIN_EMAIL,
            FIRST_WORKSPACE["slug"],
            "workspace_invitation",
            "New invitation sent",
            f"You invited {USER2_EMAIL} to {first_name} as a viewer.",
            False,
            2,
        ),
        (
            ADMIN_EMAIL,
            SECOND_WORKSPACE["slug"],
            "workspace_invitation",
            "New invitation sent",
            f"You invited {USER2_EMAIL} to {second_name} as an editor.",
            False,
            1,
        ),
        (
            USER1_EMAIL,
            FIRST_WORKSPACE["slug"],
            "workspace_invitation",
            f"You were invited to {first_name}",
            f"{ADMIN_DISPLAY_NAME} invited you to the {first_name} workspace.",
            False,
            6,
        ),
        (
            USER1_EMAIL,
            SECOND_WORKSPACE["slug"],
            "workspace_invitation",
            f"You were invited to {second_name}",
            f"{ADMIN_DISPLAY_NAME} invited you to the {second_name} workspace.",
            False,
            3,
        ),
        (
            USER2_EMAIL,
            FIRST_WORKSPACE["slug"],
            "workspace_invitation",
            f"You were invited to {first_name}",
            f"{ADMIN_DISPLAY_NAME} invited you to the {first_name} workspace.",
            False,
            2,
        ),
        (
            USER2_EMAIL,
            SECOND_WORKSPACE["slug"],
            "workspace_invitation",
            f"You were invited to {second_name}",
            f"{ADMIN_DISPLAY_NAME} invited you to the {second_name} workspace.",
            False,
            1,
        ),
    ]


async def main() -> None:
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
        admin = users[ADMIN_EMAIL]
        if not settings.superadmin_email.strip() and not admin.is_superuser:
            admin.is_superuser = True
            logger.info("promoted %s to superuser", ADMIN_EMAIL)

        workspaces: dict[str, Workspace] = {}
        for spec in WORKSPACES:
            result = await session.execute(select(Workspace).where(Workspace.slug == spec["slug"]))
            workspace = result.scalar_one_or_none()
            if workspace is None:
                workspace = await ws_service.create_workspace(
                    name=spec["name"],
                    slug=spec["slug"],
                    description=spec["description"],
                    owner=users[ADMIN_EMAIL],
                )
                logger.info("created demo workspace %s", spec["slug"])
            workspaces[spec["slug"]] = workspace

        for slug, email, role_name in MEMBERSHIPS:
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
            workspace = workspaces[slug]
            user = users[email]
            existing = await session.execute(
                select(ApiKey).where(ApiKey.workspace_id == workspace.id, ApiKey.name == name)
            )
            if existing.scalar_one_or_none() is not None:
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
                    invited_by=users[ADMIN_EMAIL],
                )
                logger.info("invited %s to %s as %s", email, slug, role_name)
            invitations[(slug, email)] = invite

        now = now_utc()
        for email, slug, type_, title, body, acknowledged, age_hours in _notifications():
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
            if type_ == "workspace_invitation" and invite is not None:
                payload.update({"invitation_id": invite.id, "invited_by": ADMIN_DISPLAY_NAME})
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
