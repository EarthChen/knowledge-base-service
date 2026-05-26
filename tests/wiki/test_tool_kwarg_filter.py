"""Tests for @function_tool kwarg filtering (drops LLM-hallucinated params)."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from wiki.page_agent import WikiPageAgent


class TestToolKwargFilter:
    @pytest.mark.asyncio
    async def test_unknown_kwargs_are_filtered(self):
        from wiki.agents.tool_decorator import function_tool

        @function_tool(name="list_like")
        async def list_like(directory: str, max_depth: int = 2) -> dict:
            """List files in a directory."""
            return {"directory": directory, "max_depth": max_depth}

        result = await list_like._tool_def.handler(
            {"file_path": "src/main", "directory": "src/main", "extra": "x"}
        )
        assert result == {"directory": "src/main", "max_depth": 2}

    @pytest.mark.asyncio
    async def test_valid_kwargs_still_work(self):
        from wiki.agents.tool_decorator import function_tool

        @function_tool()
        async def add(a: int, b: int) -> dict:
            """Add two numbers."""
            return {"sum": a + b}

        result = await add._tool_def.handler({"a": 3, "b": 4})
        assert result == {"sum": 7}

    @pytest.mark.asyncio
    async def test_unknown_kwargs_filtered_via_collect_tools(self):
        from wiki.agents.tool_decorator import collect_tools, function_tool

        class Agent:
            @function_tool(name="list_files")
            async def list_files(self, directory: str, max_depth: int = 2) -> dict:
                """List files."""
                return {"directory": directory, "max_depth": max_depth}

        tools = collect_tools(Agent())
        result = await tools[0].handler({"file_path": "ignored", "directory": "src", "max_depth": 3})
        assert result == {"directory": "src", "max_depth": 3}

    @pytest.mark.asyncio
    async def test_list_files_no_typeerror_on_hallucinated_file_path(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "App.java").write_text("class App {}")
        agent = WikiPageAgent(MagicMock(), MagicMock(), repo_path=str(tmp_path))
        result = await agent._execute_tool(
            "list_files", {"file_path": "src", "directory": "src"}
        )
        assert "error" not in result
        assert "files" in result

    @pytest.mark.asyncio
    async def test_list_files_hallucinated_only_kwargs_no_typeerror(self, tmp_path):
        (tmp_path / "src").mkdir()
        agent = WikiPageAgent(MagicMock(), MagicMock(), repo_path=str(tmp_path))
        result = await agent._execute_tool("list_files", {"file_path": "src"})
        assert "error" in result
        assert "unexpected keyword" not in str(result.get("error", "")).lower()
