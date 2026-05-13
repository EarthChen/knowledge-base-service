"""Tests for TopicDocAgent (topic-level deep-dive documentation)."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from wiki.agents.doc_orchestrator import QualityResult
from wiki.page_agent import WorkingMemory


@pytest.fixture
def patched_page_agent():
    """Patch WikiPageAgent so TopicDocAgent tests avoid full tool registration."""
    with patch("wiki.page_agent.WikiPageAgent") as mock_cls:
        instance = MagicMock()
        mock_cls.return_value = instance
        instance._graph = MagicMock()
        yield instance


def _make_agent(patched_page_agent, **kwargs):
    from wiki.agents.topic_doc_agent import TopicDocAgent

    return TopicDocAgent(
        topic_name=kwargs.get("topic_name", "Auth Flow"),
        domain_name=kwargs.get("domain_name", "security"),
        llm=MagicMock(),
        graph_store=MagicMock(),
        **{k: v for k, v in kwargs.items() if k not in ("topic_name", "domain_name")},
    )


class TestTopicDocAgentPreFill:
    @pytest.mark.asyncio
    async def test_pre_fill_fetches_snippets_for_subset(self, patched_page_agent):
        row = {
            "func_name": "login",
            "snippet": "def login():\n    pass",
            "file_path": "auth.py",
        }
        query_result = MagicMock()
        query_result.data = [row]
        patched_page_agent._graph.execute_query = AsyncMock(return_value=query_result)

        agent = _make_agent(patched_page_agent)
        memory = WorkingMemory()

        await agent.pre_fill(memory, module_names=["auth.module"])

        assert len(memory.code_snippets) == 1
        assert "[login @ auth.py]" in memory.code_snippets[0]
        assert "def login():" in memory.code_snippets[0]
        patched_page_agent._graph.execute_query.assert_awaited_once()


class TestTopicDocAgentAcceptable:
    def test_is_acceptable_strict_coverage(self, patched_page_agent):
        agent = _make_agent(patched_page_agent)

        q_ok = QualityResult(
            coverage=0.95, citation_density=0.5, context_gap_count=0,
            uncovered_modules=[],
        )
        assert agent.is_acceptable(q_ok, iteration=0) is True

        q_gaps = QualityResult(
            coverage=0.95, citation_density=0.5, context_gap_count=1,
            uncovered_modules=[],
        )
        assert agent.is_acceptable(q_gaps, iteration=0) is False

        q_low = QualityResult(
            coverage=0.94, citation_density=0.6, context_gap_count=0,
            uncovered_modules=["x"],
        )
        assert agent.is_acceptable(q_low, iteration=0) is False

        q_relaxed = QualityResult(
            coverage=0.9, citation_density=0.2, context_gap_count=3,
            uncovered_modules=["a"],
        )
        assert agent.is_acceptable(q_relaxed, iteration=1) is False
        assert agent.is_acceptable(q_relaxed, iteration=2) is True

        q_bad = QualityResult(
            coverage=0.5, citation_density=0.0, context_gap_count=5,
            uncovered_modules=["a", "b"],
        )
        assert agent.is_acceptable(q_bad, iteration=2) is False

        assert agent.is_acceptable(q_bad, iteration=3) is True


class TestTopicDocAgentPostProcess:
    def test_post_process_returns_single_topic_page(self, patched_page_agent):
        from wiki.path_conventions import domain_topic_path

        agent = _make_agent(
            patched_page_agent,
            topic_name="My Topic",
            domain_name="My Domain",
        )
        content = "## Details\n\nUse `FooBar`."
        pages = agent.post_process(content, ["ModA"], WorkingMemory())

        assert len(pages) == 1
        p = pages[0]
        assert p["page_type"] == "topic"
        assert p["title"] == "My Topic"
        assert p["path"] == domain_topic_path("My Domain", "My Topic")
        assert p["content"] == content
        assert p["diagrams"] == []
        assert p["source_locations"] == []
        assert p["metadata"]["generation_mode"] == "agent"
        assert p["metadata"]["domain"] == "My Domain"

    def test_post_process_empty_content_placeholder(self, patched_page_agent):
        agent = _make_agent(patched_page_agent, topic_name="Empty Topic")
        pages = agent.post_process("", ["m"], WorkingMemory())
        assert len(pages) == 1
        assert "# Empty Topic" in pages[0]["content"]
        assert "CONTEXT_GAP" in pages[0]["content"]


class TestTopicDocAgentGenerate:
    @pytest.mark.asyncio
    async def test_generate_produces_topic_page(self, patched_page_agent):
        from wiki.quality_report import QualityReport

        patched_page_agent.create_memory = MagicMock(return_value=WorkingMemory())
        patched_page_agent.run_tool_loop = AsyncMock(
            return_value=WorkingMemory(),
        )
        patched_page_agent.run_generation = AsyncMock(
            return_value="# Auth\n\n`com.example.Auth` coverage.",
        )
        patched_page_agent.memory_to_prompt = MagicMock(return_value="memo")

        agent = _make_agent(
            patched_page_agent,
            topic_name="Authentication",
            domain_name="platform",
        )
        good = QualityReport(
            coverage=0.96,
            citation_density=0.6,
            context_gap_count=0,
            uncovered_modules=[],
        )
        with patch(
            "wiki.agents.topic_doc_agent.evaluate_quality",
            return_value=good,
        ):
            pages = await agent.generate(
                module_names=["com.example.Auth"],
                baseline_context="## baseline",
            )

        assert len(pages) == 1
        assert pages[0]["page_type"] == "topic"
        assert pages[0]["title"] == "Authentication"
        patched_page_agent.run_generation.assert_awaited()
        patched_page_agent.run_tool_loop.assert_awaited()
