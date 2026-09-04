from __future__ import annotations

import logging

from fastmcp import FastMCP

from src.mcp.platform.registry import get_registry

logger = logging.getLogger(__name__)

_mcp: FastMCP | None = None


def build_platform_mcp() -> FastMCP:
    """FastMCP server over the platform registry (internal, streamable-http).

    Tool bodies reuse the same service proxies; scope/audit still happens via
    the registry wrappers. This is the MCP entry point for out-of-process
    runners (Vercel Sandbox) — the in-process ChatHandler uses registry.build_tools directly.
    """
    global _mcp
    if _mcp is not None:
        return _mcp
    mcp = FastMCP("platform")
    for spec in get_registry().values():
        # register as FastMCP tool (thin shim — execution still via spec.func if called via MCP)
        fn = spec.func

        mcp.tool(name=spec.name, description=spec.description or fn.__doc__ or spec.name)(fn)
    _mcp = mcp
    return mcp


def get_platform_mcp() -> FastMCP:
    return build_platform_mcp()
