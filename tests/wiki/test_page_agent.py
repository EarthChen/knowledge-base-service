"""Tests for WikiPageAgent WorkingMemory and Agent loop."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from wiki.page_agent import WikiPageAgent, ToolResult, WorkingMemory


class TestWorkingMemory:
    def test_incorporate_call_chain(self):
        wm = WorkingMemory()
        wm.incorporate([
            ToolResult(tool="query_call_chain", data={
                "chains": [{"entry": "A.foo", "chain": ["A.foo", "B.bar"], "depth": 1}]
            })
        ])
        assert len(wm.discovered_call_chains) == 1

    def test_incorporate_callers(self):
        wm = WorkingMemory()
        wm.incorporate([
            ToolResult(tool="query_callers", data={
                "callers": [{"caller_name": "X", "target_name": "Y"}]
            })
        ])
        assert len(wm.discovered_callers) == 1

    def test_incorporate_implementations(self):
        wm = WorkingMemory()
        wm.incorporate([
            ToolResult(tool="query_implementations", data={
                "implementations": [{"impl_name": "FooImpl", "interface_name": "IFoo"}]
            })
        ])
        assert len(wm.discovered_implementations) == 1
        assert "FooImpl implements IFoo" in wm.discovered_implementations[0]

    def test_incorporate_snippet(self):
        wm = WorkingMemory()
        wm.incorporate([
            ToolResult(tool="read_source_snippet", data={
                "snippet": "public void save() { db.insert(); }",
                "func_name": "save"
            })
        ])
        assert len(wm.code_snippets) == 1
        assert "save" in wm.code_snippets[0]

    def test_max_total_chars_enforced(self):
        wm = WorkingMemory()
        for i in range(100):
            wm.incorporate([
                ToolResult(tool="read_source_snippet", data={
                    "snippet": "x" * 200, "func_name": f"func{i}"
                })
            ])
        text = wm.to_prompt_section()
        assert len(text) <= WorkingMemory.MAX_TOTAL_CHARS + 500

    def test_to_prompt_section_format(self):
        wm = WorkingMemory()
        wm.discovered_call_chains.append("A → B → C")
        wm.resolved_gaps.append("gap1 resolved")
        text = wm.to_prompt_section()
        assert "A → B → C" in text
        assert "gap1" in text

    def test_empty_working_memory(self):
        wm = WorkingMemory()
        text = wm.to_prompt_section()
        assert isinstance(text, str)


class TestWikiPageAgent:
    @pytest.mark.asyncio
    async def test_no_gaps_returns_original(self):
        llm = MagicMock()
        gs = MagicMock()
        agent = WikiPageAgent(llm, gs)
        content = "No gaps here. ## 业务概述\nSome content."
        result = await agent.enrich(content, domain_name="test")
        assert result == content

    @pytest.mark.asyncio
    async def test_with_gaps_calls_llm(self):
        llm = MagicMock()
        llm.complete_with_tools = AsyncMock(return_value={
            "content": "Enriched content without gaps.",
            "tool_calls": None,
        })
        gs = MagicMock()
        agent = WikiPageAgent(llm, gs)
        content = "## 业务概述\n<!-- CONTEXT_GAP: missing order flow -->"
        result = await agent.enrich(content, domain_name="test")
        llm.complete_with_tools.assert_called()
        assert result == "Enriched content without gaps."

    @pytest.mark.asyncio
    async def test_max_rounds_enforced(self):
        llm = MagicMock()
        call_count = 0

        async def mock_complete(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return {
                "content": None,
                "tool_calls": [{"function": {"name": "query_callers", "arguments": '{"name":"X"}'}, "id": f"c{call_count}"}],
            }

        llm.complete_with_tools = mock_complete
        llm.generate = AsyncMock(return_value="fallback content")
        gs = MagicMock()
        gs.execute_query = AsyncMock(return_value=MagicMock(data=[]))
        agent = WikiPageAgent(llm, gs)
        content = "<!-- CONTEXT_GAP: x -->"
        result = await agent.enrich(content, domain_name="test")
        assert call_count <= WikiPageAgent.MAX_ROUNDS

    @pytest.mark.asyncio
    async def test_tool_execution_failure_continues(self):
        llm = MagicMock()
        call_count = 0

        async def mock_complete(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "content": None,
                    "tool_calls": [{"function": {"name": "query_callers", "arguments": '{"name":"X"}'}, "id": "c1"}],
                }
            return {"content": "final result", "tool_calls": None}

        llm.complete_with_tools = mock_complete
        gs = MagicMock()
        gs.execute_query = AsyncMock(side_effect=Exception("db down"))
        agent = WikiPageAgent(llm, gs)
        content = "<!-- CONTEXT_GAP: something -->"
        result = await agent.enrich(content, domain_name="test")
        assert result == "final result"
