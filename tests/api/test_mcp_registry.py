"""Tests for api.mcp_registry — MCP tool decorator and collector."""
from __future__ import annotations

import pytest

from auth import Role
from api.mcp_registry import collect_tools, mcp_tool


class _FakeServer:
    @mcp_tool("tool_a", min_role=Role.VIEWER)
    async def handle_a(self, args):
        return {"ok": True}

    @mcp_tool("tool_b", min_role=Role.EDITOR)
    async def handle_b(self, args):
        return {"ok": True}

    async def not_a_tool(self, args):
        return {}


class TestCollectTools:
    def test_finds_decorated_methods(self):
        server = _FakeServer()
        tools = collect_tools(server)
        assert "tool_a" in tools
        assert "tool_b" in tools
        assert "not_a_tool" not in tools

    def test_preserves_role(self):
        server = _FakeServer()
        tools = collect_tools(server)
        _, role_a = tools["tool_a"]
        _, role_b = tools["tool_b"]
        assert role_a == Role.VIEWER
        assert role_b == Role.EDITOR

    def test_collected_handler_is_bound(self):
        server = _FakeServer()
        tools = collect_tools(server)
        handler, _ = tools["tool_a"]
        assert handler.__self__ is server

    @pytest.mark.asyncio
    async def test_collected_handler_is_callable(self):
        server = _FakeServer()
        tools = collect_tools(server)
        handler, _ = tools["tool_a"]
        result = await handler({})
        assert result == {"ok": True}


class TestMcpToolDecorator:
    def test_sets_metadata(self):
        @mcp_tool("test_tool", min_role=Role.ADMIN)
        async def handler(self, args):
            pass
        assert handler._mcp_tool_name == "test_tool"
        assert handler._mcp_tool_min_role == Role.ADMIN

    def test_default_role_is_viewer(self):
        @mcp_tool("test_tool")
        async def handler(self, args):
            pass
        assert handler._mcp_tool_min_role == Role.VIEWER
