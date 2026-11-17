from __future__ import annotations

from datetime import UTC, datetime


def ensure_utc(value: datetime) -> datetime:
    """Return an aware UTC datetime; SQLite stores naive values."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def now_utc() -> datetime:
    return datetime.now(UTC)


def iso_or_none(value: datetime | None) -> str | None:
    """Serialize a stored datetime for a client, or None when there is none.

    SQLite hands back the `DateTime(timezone=True)` columns naive because it stores
    the UTC wall clock every write path puts in them, so a bare `.isoformat()`
    reads as local time in the browser.
    """
    return ensure_utc(value).isoformat() if value is not None else None
