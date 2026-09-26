from __future__ import annotations

from typing import Any

from src.models.core import Notification
from src.models.user_profile import UserProfile
from src.models.workspace import User, Workspace
from src.services.flags import requires_2fa


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
    verified = getattr(u, "email_verified_at", None)
    return {
        "id": u.id,
        "email": u.email,
        "display_name": u.display_name,
        "avatar_url": u.avatar_url,
        "is_superuser": bool(u.is_superuser),
        "email_verified": verified is not None,
    }


def workspace_to_dict(
    w: Workspace,
    *,
    role: str | None = None,
    permissions: list[str] | None = None,
    joined_at=None,
) -> dict:
    data = {
        "id": w.id,
        "name": w.name,
        "slug": w.slug,
        "description": w.description,
        "created_by_user_id": w.created_by_user_id,
        "created_at": _to_iso(w.created_at),
        # Security posture, surfaced as its own field rather than the whole
        # flags blob: clients need to know whether 2FA is enforced, not to
        # enumerate internal feature toggles.
        "require_2fa": requires_2fa(w),
    }
    if role:
        data["role"] = role
    if permissions is not None:
        data["permissions"] = permissions
    if joined_at is not None:
        data["joined_at"] = _to_iso(joined_at)
    return data


def profile_to_dict(p: UserProfile) -> dict:
    return {
        "id": p.user_id,
        "user_id": p.user_id,
        "first_name": p.first_name,
        "last_name": p.last_name,
        "bio": p.bio,
        "phone_number": p.phone_number,
        "timezone": p.timezone,
        "locale": p.locale,
        "date_of_birth": p.date_of_birth.isoformat() if p.date_of_birth else None,
        "website_url": p.website_url,
        "location": p.location,
        "custom_data": p.custom_data if p.custom_data is not None else {},
        "created_at": _to_iso(p.created_at),
        "updated_at": _to_iso(p.updated_at),
    }


def public_projection(p: UserProfile, user: User | None = None) -> dict:
    """
    Redacted projection for cross-user reads: strips phone_number, date_of_birth,
    and any custom_data keys prefixed with _private.
    """
    data = profile_to_dict(p)
    if user is not None:
        data["display_name"] = user.display_name
        data["email"] = user.email
        data["avatar_url"] = user.avatar_url
    # Redact private fields
    data["phone_number"] = None
    data["date_of_birth"] = None
    custom = data.get("custom_data") or {}
    filtered = {k: v for k, v in custom.items() if not k.startswith("_private")}
    data["custom_data"] = filtered
    return data
