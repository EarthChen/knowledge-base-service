"""MCP tool auto-registration via decorators.

Usage:
    @mcp_tool("tool_name", min_role=Role.VIEWER)
    async def handle_tool(self, args: dict) -> dict: ...

    tools = collect_tools(server_instance)
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from auth import Role


def mcp_tool(name: str, *, min_role: Role = Role.VIEWER) -> Callable:
    """Mark an async method as an MCP tool handler."""
    def decorator(fn: Callable) -> Callable:
        fn._mcp_tool_name = name  # type: ignore[attr-defined]
        fn._mcp_tool_min_role = min_role  # type: ignore[attr-defined]
        return fn
    return decorator


def collect_tools(instance: object) -> dict[str, tuple[Callable[..., Any], Role]]:
    """Scan *instance* for @mcp_tool-decorated methods. Returns {name: (bound_method, role)}."""
    tools: dict[str, tuple[Callable[..., Any], Role]] = {}
    for attr_name in dir(instance):
        if attr_name.startswith("__"):
            continue
        method = getattr(instance, attr_name, None)
        if not callable(method):
            continue
        fn = getattr(method, "__func__", method)
        tool_name = getattr(fn, "_mcp_tool_name", None)
        if tool_name is None:
            continue
        tools[tool_name] = (method, fn._mcp_tool_min_role)
    return tools


def collect_elevated_tool_roles(*classes: type) -> dict[str, Role]:
    """Merge tools whose ``min_role`` is strictly above VIEWER (sparse map for backward compat)."""

    def _unwrap(attr: Any) -> Any:
        if isinstance(attr, (staticmethod, classmethod)):
            return attr.__func__
        return attr

    out: dict[str, Role] = {}
    for cls in classes:
        for attr_name in dir(cls):
            if attr_name.startswith("__"):
                continue
            raw = getattr(cls, attr_name, None)
            if raw is None:
                continue
            fn = _unwrap(raw)
            if not callable(fn):
                continue
            tool_name = getattr(fn, "_mcp_tool_name", None)
            if tool_name is None:
                continue
            min_role = getattr(fn, "_mcp_tool_min_role", Role.VIEWER)
            if min_role > Role.VIEWER:
                out[tool_name] = min_role
    return out
