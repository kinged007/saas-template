"""Workspace feature-flag keys and readers.

The registry lives in `docs/FEATURE_FLAGS.md`; this module is the code side of
it. Flags live on `workspaces.flags` as `{key: bool}`.
"""

from __future__ import annotations

from src.models.workspace import Workspace

INVITES_ENABLED_FLAG = "invites_enabled"
# Security posture rather than a feature toggle: opt-in, so a workspace that
# never set it (or predates the flag) is not affected. Enforced per request in
# src.api.deps.enforce_workspace_security.
REQUIRE_2FA_FLAG = "require_2fa"


def requires_2fa(workspace: Workspace) -> bool:
    """True when this workspace refuses sessions that have not cleared 2FA."""
    return (workspace.flags or {}).get(REQUIRE_2FA_FLAG) is True
