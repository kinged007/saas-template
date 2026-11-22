"""Project-defined permissions (demo: `demo:read`, `demo:create`).

Registered on the shared catalog via `register_permission`, so they can be
granted to roles and API keys and are enforced by the existing
`require_permission` gate — no new authorization semantics.
"""

from src.core.permissions import register_permission

DEMO_READ = register_permission("demo:read", resource="demo", action="read")
DEMO_CREATE = register_permission("demo:create", resource="demo", action="create")
