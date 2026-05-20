"""@function_tool decorator for auto-generating ToolDef from type hints.

Eliminates hand-written JSON Schema by inferring parameters from
function signatures. Handlers automatically unpack dict args into
function kwargs.
"""
from __future__ import annotations

import inspect
from typing import Any, Awaitable, Callable, get_type_hints, get_origin, get_args

from wiki.agents.base_agent import ToolDef


def function_tool(
    name: str | None = None,
    *,
    tier: int = 1,
    description: str | None = None,
) -> Callable:
    """Auto-generate ToolDef from function signature + type hints."""

    def decorator(fn: Callable) -> Callable:
        tool_name = name or fn.__name__
        tool_desc = description or (fn.__doc__ or "").strip().split("\n")[0]

        try:
            hints = get_type_hints(fn, include_extras=True)
        except Exception:
            hints = {}

        params_schema = _build_params_schema(fn, hints)
        has_ctx_param = _fn_accepts_ctx(fn)

        async def _handler(args: dict[str, Any], ctx: Any = None) -> dict[str, Any]:
            if has_ctx_param and ctx is not None:
                return await fn(ctx=ctx, **args)
            return await fn(**args)

        fn._tool_def = ToolDef(
            name=tool_name,
            description=tool_desc,
            parameters=params_schema,
            handler=_handler,
            tier=tier,
        )
        return fn

    return decorator


def _fn_accepts_ctx(fn: Callable) -> bool:
    """Check if a function has a 'ctx' parameter."""
    sig = inspect.signature(fn)
    return "ctx" in sig.parameters


def _build_params_schema(fn: Callable, hints: dict) -> dict[str, Any]:
    """Build JSON Schema from function parameters (skip 'self', 'ctx', 'args')."""
    sig = inspect.signature(fn)
    properties: dict[str, Any] = {}
    required: list[str] = []

    for param_name, param in sig.parameters.items():
        if param_name in ("self", "ctx", "args", "return"):
            continue
        hint = hints.get(param_name, str)
        properties[param_name] = _type_to_json_schema(hint)
        if param.default is inspect.Parameter.empty:
            required.append(param_name)

    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }


def _type_to_json_schema(hint: Any) -> dict[str, Any]:
    """Convert a Python type hint to JSON Schema."""
    if hint is str:
        return {"type": "string"}
    if hint is int:
        return {"type": "integer"}
    if hint is float:
        return {"type": "number"}
    if hint is bool:
        return {"type": "boolean"}

    origin = get_origin(hint)
    if origin is list:
        args = get_args(hint)
        items = _type_to_json_schema(args[0]) if args else {"type": "string"}
        return {"type": "array", "items": items}

    # Default fallback
    return {"type": "string"}


def collect_tools(instance: Any) -> list[ToolDef]:
    """Collect all @function_tool decorated methods from an instance.

    Returns ToolDef objects with handlers bound to the instance.
    """
    tools: list[ToolDef] = []
    for attr_name in dir(instance):
        if attr_name.startswith("_"):
            continue
        try:
            attr = getattr(type(instance), attr_name, None)
        except Exception:
            continue
        if attr is None or not hasattr(attr, "_tool_def"):
            continue

        original_td: ToolDef = attr._tool_def
        bound_method = getattr(instance, attr_name)
        accepts_ctx = _fn_accepts_ctx(attr)

        async def _bound_handler(
            args: dict[str, Any],
            ctx: Any = None,
            _method=bound_method,
            _accepts_ctx=accepts_ctx,
        ) -> dict[str, Any]:
            if _accepts_ctx and ctx is not None:
                return await _method(ctx=ctx, **args)
            return await _method(**args)

        tools.append(ToolDef(
            name=original_td.name,
            description=original_td.description,
            parameters=original_td.parameters,
            handler=_bound_handler,
            tier=original_td.tier,
        ))
    return tools
