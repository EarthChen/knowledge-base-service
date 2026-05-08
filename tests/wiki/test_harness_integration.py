"""Integration tests for WikiGenerationHarness."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass, field


@dataclass
class _FakeCCBContext:
    cross_domain_calls: list = field(default_factory=list)
    module_summaries: list = field(default_factory=list)


def _make_mock_agent(content="## 概述\nModA handles auth.\n## 核心业务流程\nModA calls ModB.\n" + "x" * 600):
    agent = AsyncMock()
    agent.generate = AsyncMock(return_value=content)
    agent.repair = AsyncMock(return_value=content)
    return agent


def _make_mock_graph_store():
    gs = AsyncMock()
    gs.execute_query = AsyncMock(return_value=MagicMock(data=[]))
    return gs


def _make_mock_llm():
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value="repaired content" + "x" * 600)
    return llm


class TestHarnessRun:
    def test_harness_runs_full_pipeline(self):
        from wiki.harness import WikiGenerationHarness
        agent = _make_mock_agent()
        harness = WikiGenerationHarness(
            agent=agent, graph_store=_make_mock_graph_store(), llm=_make_mock_llm(),
        )
        result = asyncio.run(harness.run(
            domain="UserAuth", modules=["ModA", "ModB"],
            ccb_context=_FakeCCBContext(),
        ))
        assert len(result) > 0
        agent.generate.assert_called_once()

    def test_harness_simple_domain_no_repair(self):
        from wiki.harness import WikiGenerationHarness
        good_content = "## 概述\nModA does X.\n## 核心业务流程\nModA calls Y.\n" + "detail " * 100
        agent = _make_mock_agent(good_content)
        harness = WikiGenerationHarness(
            agent=agent, graph_store=_make_mock_graph_store(), llm=_make_mock_llm(),
        )
        result = asyncio.run(harness.run(
            domain="Small", modules=["ModA"],
            ccb_context=_FakeCCBContext(),
        ))
        agent.repair.assert_not_called()  # simple domain, no repair rounds

    def test_harness_updates_domain_cache(self):
        from wiki.harness import WikiGenerationHarness
        agent = _make_mock_agent()
        harness = WikiGenerationHarness(
            agent=agent, graph_store=_make_mock_graph_store(), llm=_make_mock_llm(),
        )
        asyncio.run(harness.run(
            domain="UserAuth", modules=["ModA"],
            ccb_context=_FakeCCBContext(),
        ))
        assert "UserAuth" in harness.domain_cache

    def test_harness_repair_triggered_on_low_score(self):
        from wiki.harness import WikiGenerationHarness
        bad_content = "short"  # will fail L1 length check
        good_content = "## 概述\nModA does auth.\n## 核心业务流程\nModA flow.\n" + "x" * 600
        agent = AsyncMock()
        agent.generate = AsyncMock(return_value=bad_content)
        agent.repair = AsyncMock(return_value=good_content)
        harness = WikiGenerationHarness(
            agent=agent, graph_store=_make_mock_graph_store(), llm=_make_mock_llm(),
        )
        # Use moderate to get repair rounds = 1
        result = asyncio.run(harness.run(
            domain="Auth", modules=[f"Mod{i}" for i in range(8)],
            ccb_context=_FakeCCBContext(cross_domain_calls=[{"a": "b"}] * 3),
        ))
        agent.repair.assert_called()
