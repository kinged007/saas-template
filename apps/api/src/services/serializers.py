from __future__ import annotations

from datetime import datetime

from src.core.dates import iso_or_none
from src.models.core import Notification
from src.models.user_profile import UserProfile
from src.models.workspace import User, Workspace


def notification_to_dict(n: Notification, *, workspace_name: str | None = None) -> dict:
    data = {
        "id": n.id,
        "user_id": n.user_id,
        "workspace_id": n.workspace_id,
        "type": n.type,
        "title": n.title,
        "body": n.body,
        "payload": n.payload,
        "acknowledged_at": iso_or_none(n.acknowledged_at),
        "created_at": iso_or_none(n.created_at),
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


ONBOARDING_ENABLED_FLAG = "onboarding_enabled"


def workspace_to_dict(
    w: Workspace,
    *,
    role: str | None = None,
    permissions: list[str] | None = None,
    joined_at: datetime | None = None,
) -> dict:
    data = {
        "id": w.id,
        "name": w.name,
        "slug": w.slug,
        "description": w.description,
        "created_by_user_id": w.created_by_user_id,
        "created_at": iso_or_none(w.created_at),
        # Default-on: only an explicit False disables it (FEATURE_FLAGS.md).
        ONBOARDING_ENABLED_FLAG: (w.flags or {}).get(ONBOARDING_ENABLED_FLAG) is not False,
    }
    if role:
        data["role"] = role
    if permissions is not None:
        data["permissions"] = permissions
    if joined_at is not None:
        data["joined_at"] = iso_or_none(joined_at)
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
        # A `Date` column has no offset to give.
        "date_of_birth": p.date_of_birth.isoformat() if p.date_of_birth else None,
        "website_url": p.website_url,
        "location": p.location,
        "custom_data": p.custom_data if p.custom_data is not None else {},
        "created_at": iso_or_none(p.created_at),
        "updated_at": iso_or_none(p.updated_at),
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
