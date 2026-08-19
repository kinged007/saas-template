from __future__ import annotations

from typing import Any

from src.models.core import Notification
from src.models.workspace import User, Workspace


def _to_iso(value: Any) -> str | None:
    return value.isoformat() if value else None


def notification_to_dict(n: Notification, *, workspace_name: str | None = None) -> dict:
    data = {
        "id": n.id,
        "user_id": n.user_id,
        "workspace_id": n.workspace_id,
        "type": n.type,
        "title": n.title,
        "body": n.body,
        "payload": n.payload,
        "acknowledged_at": _to_iso(n.acknowledged_at),
        "created_at": _to_iso(n.created_at),
    }
    if workspace_name is not None:
        data["workspace_name"] = workspace_name
    return data


def user_to_dict(u: User) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "display_name": u.display_name,
        "avatar_url": u.avatar_url,
    }


def workspace_to_dict(
    w: Workspace, *, role: str | None = None, permissions: list[str] | None = None
) -> dict:
    data = {
        "id": w.id,
        "name": w.name,
        "slug": w.slug,
        "description": w.description,
        "created_by_user_id": w.created_by_user_id,
        "created_at": _to_iso(w.created_at),
    }
    if role:
        data["role"] = role
    if permissions is not None:
        data["permissions"] = permissions
    return data
