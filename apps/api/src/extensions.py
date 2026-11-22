"""Project extension loading (update-path seam, see #1794).

Derived projects ship their own code under `src/project/` (routers, models,
settings, workflows, jobs, permissions) instead of editing template-owned
files. This module is the only template-owned loader: `main.py` and
`src/models/__init__.py` each call into it once, and no per-feature edit is
needed afterwards.

Failure contract: a configured extension module that cannot be imported, or
whose hook raises, aborts startup with a `RuntimeError` naming the module and
the error. The one exception is the default module (`src.project`) when
`EXTENSION_MODULES` is unset: an absent project area means "no extensions",
so startup succeeds with template behavior unchanged (this is also what makes
`rm -rf apps/api/src/project` the one-command demo removal).
"""

from __future__ import annotations

import importlib
import logging
import os
from types import ModuleType

logger = logging.getLogger(__name__)

DEFAULT_EXTENSION_MODULE = "src.project"


def _explicitly_configured() -> bool:
    return "EXTENSION_MODULES" in os.environ


def extension_module_names() -> list[str]:
    """Configured extension modules, in order (comma-separated env var)."""
    from src.settings import settings

    return settings.extension_module_list


def _missing_is_absent_default(name: str, exc: ModuleNotFoundError) -> bool:
    return exc.name == name and name == DEFAULT_EXTENSION_MODULE and not _explicitly_configured()


def load_extension_modules() -> list[ModuleType]:
    """Import every configured extension module, failing fast on breakage."""
    loaded: list[ModuleType] = []
    for name in extension_module_names():
        try:
            loaded.append(importlib.import_module(name))
        except ModuleNotFoundError as exc:
            if _missing_is_absent_default(name, exc):
                logger.info("extension module %r absent; running with template behavior", name)
                continue
            raise RuntimeError(f"extension module {name!r} failed to load: {exc}") from exc
        except Exception as exc:
            raise RuntimeError(f"extension module {name!r} failed to load: {exc}") from exc
    return loaded


def load_extension_models() -> None:
    """Import `{module}.models` for every extension so migrations see its tables.

    Called once from `src/models/__init__.py`; the import registers project
    models on `Base.metadata` for Alembic autogenerate and `create_all`.
    An extension with no `.models` submodule is fine (router-only project).
    """
    for name in extension_module_names():
        models_name = f"{name}.models"
        try:
            importlib.import_module(models_name)
        except ModuleNotFoundError as exc:
            if exc.name == models_name:
                continue  # no models in this extension; nothing to register
            if exc.name == name and _missing_is_absent_default(name, exc):
                continue
            raise RuntimeError(f"extension module {name!r} models failed to load: {exc}") from exc


def load_extension_cascade_models() -> list[type]:
    """Workspace-scoped project models for the workspace-delete cascade.

    Any model defined in an extension's `.models` submodule carrying a
    `workspace_id` column is deleted with its workspace (see
    `src/db/cascade.py`) — the same rule the template applies to its own
    tables, so project rows can never be orphaned and no per-feature
    template edit is needed.
    """
    from src.db.base import Base

    load_extension_models()  # ensure extension tables are registered first
    names = extension_module_names()
    if not names:
        return []
    out: list[type] = []
    for mapper in Base.registry.mappers:
        cls = mapper.class_
        if not hasattr(cls, "__tablename__"):
            continue
        table = cls.__table__
        if "workspace_id" not in table.c:
            continue
        module = cls.__module__ or ""
        if not any(module == name or module.startswith(name + ".") for name in names):
            continue
        out.append(cls)
    return out


def register_extension_routes(app) -> None:
    """Call `register(app)` on every extension that defines it (import time)."""
    for mod in load_extension_modules():
        hook = getattr(mod, "register", None)
        if hook is None:
            continue
        try:
            hook(app)
        except Exception as exc:
            raise RuntimeError(
                f"extension module {mod.__name__!r} register(app) failed: {exc}"
            ) from exc


def register_extension_jobs() -> None:
    """Call `register_jobs()` on every extension that defines it (import time).

    Runs before the lifespan's `sync_definitions`, so extension job specs are
    on the shared `job_registry` when definitions are provisioned.
    """
    for mod in load_extension_modules():
        hook = getattr(mod, "register_jobs", None)
        if hook is None:
            continue
        try:
            hook()
        except Exception as exc:
            raise RuntimeError(
                f"extension module {mod.__name__!r} register_jobs() failed: {exc}"
            ) from exc


def register_extension_workflows(registry, bus, connection_manager=None, cipher=None) -> None:
    """Call `register_workflows(...)` on every extension that defines it.

    Runs in the lifespan right after the template `build_workflows`, with the
    same registry/bus/connection-manager/cipher objects.
    """
    for mod in load_extension_modules():
        hook = getattr(mod, "register_workflows", None)
        if hook is None:
            continue
        try:
            hook(registry, bus, connection_manager, cipher)
        except Exception as exc:
            raise RuntimeError(
                f"extension module {mod.__name__!r} register_workflows() failed: {exc}"
            ) from exc
