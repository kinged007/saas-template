"""Project-owned extension area (update-path seam, see #1794).

Everything a derived project adds lives here — routers, models, settings,
workflows, jobs, permissions — so template updates never conflict with it.
The template ships this package with one minimal demo per seam kind, named
`demo_*` so it reads as an example and not plumbing. Removal is one command:

    rm -rf apps/api/src/project

(with the default `EXTENSION_MODULES`, an absent area starts up with plain
template behavior). The template loads this package through exactly three
hooks, called by `src/extensions.py`:

- `register(app)` — routers, at import time.
- `register_jobs()` — job specs, at import time (before definition sync).
- `register_workflows(registry, bus, connection_manager, cipher)` — event
  subscriptions, in the lifespan right after the template workflows.
"""

from __future__ import annotations

__all__ = ["register", "register_jobs", "register_workflows"]


def register(app) -> None:
    """Serve the project routers on the API."""
    from src.project.router import router

    app.include_router(router, prefix="/api/v1")


def register_jobs() -> None:
    """Register project job specs on the shared `job_registry`."""
    from src.project import jobs  # noqa: F401


def register_workflows(registry, bus, connection_manager=None, cipher=None) -> None:
    """Subscribe project workflows to the shared registry and bus."""
    from src.project.workflows import register_workflows as _register

    _register(registry, bus, connection_manager, cipher)
