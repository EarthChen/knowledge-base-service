"""Tests for P1.1: list_files tool."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from wiki.page_agent import AGENT_TOOLS, ToolResult, WikiPageAgent, WorkingMemory


class TestListFilesToolDefinition:
    def test_list_files_in_agent_tools(self):
        names = [t["function"]["name"] for t in AGENT_TOOLS]
        assert "list_files" in names

    def test_list_files_has_directory_param(self):
        for tool in AGENT_TOOLS:
            if tool["function"]["name"] == "list_files":
                params = tool["function"]["parameters"]["properties"]
                assert "directory" in params
                assert "max_depth" in params


class TestListFilesTool:
    @pytest.fixture
    def tmp_repo(self, tmp_path):
        (tmp_path / "src" / "main").mkdir(parents=True)
        (tmp_path / "src" / "main" / "App.java").write_text("class App {}")
        (tmp_path / "src" / "main" / "Service.java").write_text("class Service {}")
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "app.yaml").write_text("port: 8080")
        return tmp_path

    @pytest.mark.asyncio
    async def test_lists_directory_contents(self, tmp_repo):
        agent = WikiPageAgent(MagicMock(), MagicMock(), repo_path=str(tmp_repo))
        result = await agent._tool_list_files({"directory": "src/main"})
        assert "files" in result
        assert any("App.java" in f for f in result["files"])
        assert any("Service.java" in f for f in result["files"])

    @pytest.mark.asyncio
    async def test_rejects_absolute_path(self, tmp_repo):
        agent = WikiPageAgent(MagicMock(), MagicMock(), repo_path=str(tmp_repo))
        result = await agent._tool_list_files({"directory": "/etc"})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_rejects_path_traversal(self, tmp_repo):
        agent = WikiPageAgent(MagicMock(), MagicMock(), repo_path=str(tmp_repo))
        result = await agent._tool_list_files({"directory": "../"})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_returns_error_for_nonexistent_dir(self, tmp_repo):
        agent = WikiPageAgent(MagicMock(), MagicMock(), repo_path=str(tmp_repo))
        result = await agent._tool_list_files({"directory": "nonexistent"})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_unavailable_without_repo_path(self):
        agent = WikiPageAgent(MagicMock(), MagicMock(), repo_path=None)
        result = await agent._tool_list_files({"directory": "src"})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_max_entries_limit(self, tmp_path):
        # Create 60 files
        d = tmp_path / "many"
        d.mkdir()
        for i in range(60):
            (d / f"file_{i:03d}.txt").write_text(f"content {i}")
        agent = WikiPageAgent(MagicMock(), MagicMock(), repo_path=str(tmp_path))
        result = await agent._tool_list_files({"directory": "many"})
        assert len(result["files"]) <= 50
        assert result["truncated"] is True


class TestWorkingMemoryListFiles:
    def test_incorporate_list_files(self):
        mem = WorkingMemory()
        mem.incorporate([
            ToolResult(tool="list_files", data={"directory": "src/", "files": ["src/A.java", "src/B.java"]}),
        ])
        assert any("A.java" in f for f in mem.search_findings)
