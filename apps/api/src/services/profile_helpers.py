from __future__ import annotations

import json
import logging

from fastapi import HTTPException

logger = logging.getLogger(__name__)

MAX_CUSTOM_DATA_KEYS = 50
MAX_CUSTOM_DATA_BYTES = 16 * 1024  # 16 KiB


def format_display_name(first_name: str | None, last_name: str | None, fallback: str | None = None) -> str:
    """Format as 'First L.' — first name + initial of last name. Deprecated display_name fallback."""
    fn = (first_name or "").strip()
    ln = (last_name or "").strip()
    if fn and ln:
        return f"{fn} {ln[0].upper()}."
    if fn:
        return fn
    if ln:
        return ln
    if fallback:
        return fallback.strip()
    return ""


def validate_custom_data(data: dict) -> None:
    if not isinstance(data, dict):
        raise HTTPException(status_code=422, detail="custom_data must be an object")
    if len(data) > MAX_CUSTOM_DATA_KEYS:
        raise HTTPException(status_code=422, detail="custom_data exceeds limits")
    # Check serializable and size
    try:
        serialized = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"custom_data not JSON serializable: {exc}") from None
    if len(serialized.encode("utf-8")) > MAX_CUSTOM_DATA_BYTES:
        raise HTTPException(status_code=422, detail="custom_data exceeds limits")


def merge_custom_data(
    existing: dict | None, patch: dict | None, is_put: bool
) -> dict:
    """
    Apply RFC 7396 Merge Patch semantics for custom_data.

    - is_put == True: replacement semantics. If patch is None, leave existing unchanged.
                       If patch is provided, replace entirely (even if empty).
    - is_put == False: merge semantics. Shallow-merge patch into existing:
                       null deletes a key, omission retains, new/updated keys replace.
    Validates bounds (50 keys, 16 KiB) after merge/replace and raises 422 if exceeded.
    """
    existing = dict(existing or {})

    if is_put:
        if patch is None:
            # PUT without custom_data leaves bag unchanged
            result = existing
        else:
            if not isinstance(patch, dict):
                raise HTTPException(status_code=422, detail="custom_data must be an object")
            result = dict(patch)
    else:
        if patch is None:
            result = existing
        else:
            if not isinstance(patch, dict):
                raise HTTPException(status_code=422, detail="custom_data must be an object")
            result = dict(existing)
            for key, value in patch.items():
                if value is None:
                    # null deletes the key (no-op if absent)
                    result.pop(key, None)
                else:
                    result[key] = value

    validate_custom_data(result)
    return result
