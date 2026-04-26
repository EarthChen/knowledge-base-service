"""HTTP endpoints for calling the wiki MCP tool surface."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request

from api.exceptions import KbServiceUnavailable

router = APIRouter(tags=["mcp", "wiki", "tools"])


@router.post("/tools/call")
async def mcp_tool_call(request: Request) -> dict[str, Any]:
    """MCP-compatible tool call endpoint."""
    body = await request.json()
    tool_name = body.get("name", "")
    arguments = body.get("arguments", {})

    mcp_server = getattr(request.app.state, "mcp_wiki_server", None)
    if mcp_server is None:
        raise KbServiceUnavailable("MCP server not configured")

    result = await mcp_server.handle_tool_call(tool_name, arguments)
    return {"content": [{"type": "text", "text": json.dumps(result)}]}


@router.get("/tools/list")
async def mcp_tool_list() -> dict[str, Any]:
    """List available MCP tools."""
    from api.mcp_wiki_server import TOOL_DEFINITIONS

    return {"tools": TOOL_DEFINITIONS}
