"""Tests for WikiPageAgent.repair() method."""
import asyncio
from unittest.mock import AsyncMock, MagicMock
from dataclasses import dataclass, field


@dataclass
class _FakeEvalResult:
    score: float = 0.5
    passed: bool = False
    issues: list = field(default_factory=lambda: [
        MagicMock(category="coverage", message="模块覆盖率 60%", severity="error"),
    ])
    suggestions: list = field(default_factory=lambda: ["请确保提及所有关键模块"])


def test_repair_method_exists():
    from wiki.page_agent import WikiPageAgent
    assert hasattr(WikiPageAgent, "repair")
    import inspect
    assert inspect.iscoroutinefunction(WikiPageAgent.repair)


def test_repair_returns_improved_content():
    from wiki.page_agent import WikiPageAgent

    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value="## 概述\n修正后的完整内容" + "x" * 300)

    agent = WikiPageAgent(llm=mock_llm, graph_store=MagicMock())
    eval_result = _FakeEvalResult()

    result = asyncio.run(agent.repair("原始内容" * 50, eval_result))
    assert len(result) > 200
    mock_llm.generate.assert_called_once()


def test_repair_returns_original_if_llm_fails():
    from wiki.page_agent import WikiPageAgent

    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value="too short")

    agent = WikiPageAgent(llm=mock_llm, graph_store=MagicMock())
    original = "原始内容" * 50
    eval_result = _FakeEvalResult()

    result = asyncio.run(agent.repair(original, eval_result))
    assert result == original
