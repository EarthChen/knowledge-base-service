"""Tests for P1.2: grep_code tool."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from wiki.page_agent import WikiPageAgent, AGENT_TOOLS, WorkingMemory, ToolResult


class TestGrepCodeToolDefinition:
    def test_grep_code_in_agent_tools(self):
        names = [t["function"]["name"] for t in AGENT_TOOLS]
        assert "grep_code" in names

    def test_grep_code_has_pattern_param(self):
        for tool in AGENT_TOOLS:
            if tool["function"]["name"] == "grep_code":
                params = tool["function"]["parameters"]["properties"]
                assert "pattern" in params
                assert "file_pattern" in params


class TestGrepCodeTool:
    @pytest.fixture
    def tmp_repo(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "Service.java").write_text(
            "public class Service {\n    throw new PaymentException(\"failed\");\n}\n"
        )
        (tmp_path / "src" / "Controller.java").write_text(
            "public class Controller {\n    service.process();\n}\n"
        )
        (tmp_path / "config.yaml").write_text("server:\n  port: 8080\n")
        return tmp_path

    @pytest.mark.asyncio
    async def test_finds_pattern(self, tmp_repo):
        agent = WikiPageAgent(MagicMock(), MagicMock(), repo_path=str(tmp_repo))
        result = await agent._tool_grep_code({"pattern": "PaymentException"})
        assert len(result["matches"]) >= 1
        assert "Service.java" in result["matches"][0]["file"]

    @pytest.mark.asyncio
    async def test_regex_pattern(self, tmp_repo):
        agent = WikiPageAgent(MagicMock(), MagicMock(), repo_path=str(tmp_repo))
        result = await agent._tool_grep_code({"pattern": r"throw\s+new\s+\w+Exception"})
        assert len(result["matches"]) >= 1

    @pytest.mark.asyncio
    async def test_file_pattern_filter(self, tmp_repo):
        agent = WikiPageAgent(MagicMock(), MagicMock(), repo_path=str(tmp_repo))
        result = await agent._tool_grep_code({"pattern": "port", "file_pattern": "*.yaml"})
        assert len(result["matches"]) >= 1
        assert "config.yaml" in result["matches"][0]["file"]

    @pytest.mark.asyncio
    async def test_returns_error_without_pattern(self, tmp_repo):
        agent = WikiPageAgent(MagicMock(), MagicMock(), repo_path=str(tmp_repo))
        result = await agent._tool_grep_code({"pattern": ""})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_unavailable_without_repo_path(self):
        agent = WikiPageAgent(MagicMock(), MagicMock(), repo_path=None)
        result = await agent._tool_grep_code({"pattern": "test"})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_max_results_respected(self, tmp_path):
        d = tmp_path / "many"
        d.mkdir()
        # Create file with many matching lines
        content = "\n".join(f"line {i} MATCH" for i in range(30))
        (d / "big.txt").write_text(content)
        agent = WikiPageAgent(MagicMock(), MagicMock(), repo_path=str(tmp_path))
        result = await agent._tool_grep_code({"pattern": "MATCH", "max_results": 5})
        assert len(result["matches"]) == 5
        assert result["truncated"] is True

    @pytest.mark.asyncio
    async def test_invalid_regex_fallback_to_literal(self, tmp_repo):
        """Invalid regex should fallback to literal search."""
        agent = WikiPageAgent(MagicMock(), MagicMock(), repo_path=str(tmp_repo))
        result = await agent._tool_grep_code({"pattern": "class ["})  # Invalid regex
        # Should not raise, falls back to literal
        assert "error" not in result


class TestWorkingMemoryGrepCode:
    def test_incorporate_grep_results(self):
        mem = WorkingMemory()
        mem.incorporate([ToolResult(tool="grep_code", data={
            "pattern": "Exception",
            "matches": [{"file": "A.java", "line": 10, "content": "throw new Exception()"}],
        })])
        assert any("grep:" in f for f in mem.search_findings)
