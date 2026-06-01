from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from wiki.agents.base_agent import GenericAgent


class _StubAgent(GenericAgent):
    """Minimal concrete subclass for testing GenericAgent methods."""

    def incorporate(self, tool_name, result, memory):
        pass

    def memory_to_prompt(self, memory):
        return ""


@pytest.mark.asyncio
async def test_remember_stores_and_returns_uid():
    agent = _StubAgent.__new__(_StubAgent)
    agent._memory_backend = AsyncMock()
    agent._memory_backend.store = AsyncMock(return_value="qa-abc")
    agent._remember_call_count = 0
    result = await agent.remember(question="What does X do?", answer="X handles Y", confidence=0.8)
    assert result["stored"] is True
    assert result["uid"] == "qa-abc"


@pytest.mark.asyncio
async def test_remember_rate_limit():
    agent = _StubAgent.__new__(_StubAgent)
    agent._memory_backend = AsyncMock()
    agent._memory_backend.store = AsyncMock(return_value="id")
    agent._remember_call_count = 5
    result = await agent.remember(question="q", answer="a")
    assert result["stored"] is False
    assert "rate_limit" in result.get("error", "")


@pytest.mark.asyncio
async def test_remember_no_backend_degrades():
    agent = _StubAgent.__new__(_StubAgent)
    agent._memory_backend = None
    agent._remember_call_count = 0
    result = await agent.remember(question="q", answer="a")
    assert result["stored"] is False
    assert "not_configured" in result.get("error", "")


@pytest.mark.asyncio
async def test_remember_low_confidence_rejected():
    agent = _StubAgent.__new__(_StubAgent)
    agent._memory_backend = AsyncMock()
    agent._remember_call_count = 0
    result = await agent.remember(question="q", answer="a", confidence=0.3)
    assert result["stored"] is False
    assert "confidence" in result.get("error", "")


def test_remember_in_collect_tools():
    from wiki.agents.tool_decorator import collect_tools

    agent = _StubAgent.__new__(_StubAgent)
    tools = collect_tools(agent)
    names = {t.name for t in tools}
    assert "remember" in names
    remember_tool = next(t for t in tools if t.name == "remember")
    assert remember_tool.tier == 2
    assert "long-term memory" in remember_tool.description.lower()


def test_restrict_tools():
    agent = _StubAgent.__new__(_StubAgent)
    agent.restrict_tools(["search_entities", "read_code"])
    assert hasattr(agent, "_tool_allowlist")
    assert "search_entities" in agent._tool_allowlist
    assert "read_code" in agent._tool_allowlist
