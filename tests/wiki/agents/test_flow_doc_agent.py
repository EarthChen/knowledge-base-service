import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from wiki.agents.memory import Memory
from wiki.agents.doc_orchestrator import QualityResult
from wiki.page_agent import WorkingMemory
from wiki.quality_report import QualityReport


class TestFlowDocAgentPreFill:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "memory_cls,mod_names,row,expected",
        [
            (
                WorkingMemory,
                ["com.foo.A"],
                {"caller": "com.foo.A", "callee": "com.bar.B", "file_path": "/a.py"},
                ("chains", ["com.foo.A → com.bar.B"]),
            ),
            (
                Memory,
                ["X"],
                {"caller": "X", "callee": "Y"},
                ("entries_call_chains", ["X → Y"]),
            ),
        ],
    )
    async def test_pre_fill_fetches_call_chains(
        self, memory_cls, mod_names, row, expected
    ):
        from wiki.agents.flow_doc_agent import FlowDocAgent, FLOW_CALL_CHAIN_CY

        graph = MagicMock()
        graph.execute_query = AsyncMock(return_value=MagicMock(data=[row]))
        mock_page = MagicMock()
        mock_page._graph = graph

        with patch("wiki.page_agent.WikiPageAgent", return_value=mock_page):
            agent = FlowDocAgent(
                "checkout" if memory_cls is WorkingMemory else "f",
                "payments" if memory_cls is WorkingMemory else "d",
                llm=MagicMock(),
                graph_store=graph,
            )
            agent._page_agent = mock_page

        mem = memory_cls()
        await agent.pre_fill(mem, mod_names)

        graph.execute_query.assert_awaited_once_with(
            FLOW_CALL_CHAIN_CY,
            {"names": mod_names},
        )
        kind, value = expected
        if kind == "chains":
            assert mem.discovered_call_chains == value
        else:
            assert mem.entries.get("call_chains") == value


class TestFlowDocAgentPostProcess:
    def test_post_process_returns_flow_page(self):
        from wiki.agents.flow_doc_agent import FlowDocAgent
        from wiki.path_conventions import domain_topic_path

        mock_page = MagicMock()
        with patch("wiki.page_agent.WikiPageAgent", return_value=mock_page):
            agent = FlowDocAgent("Order Flow", "retail", llm=MagicMock(), graph_store=MagicMock())
            agent._page_agent = mock_page

        content = "# Order Flow\n\nBody with `Mod`."
        pages = agent.post_process(content, ["Mod"], WorkingMemory())
        assert len(pages) == 1
        p = pages[0]
        assert p["page_type"] == "business_flow"
        assert p["title"] == "Order Flow"
        assert p["path"] == domain_topic_path("retail", "Order Flow")
        assert p["content"] == content
        assert p["diagrams"] == []
        assert p["source_locations"] == []
        assert p["metadata"]["domain"] == "retail"
        assert p["metadata"]["flow_name"] == "Order Flow"
        assert p["metadata"]["generation_mode"] == "agent"


class TestFlowDocAgentIsAcceptable:
    def test_is_acceptable_allows_lower_threshold(self):
        from wiki.agents.flow_doc_agent import FlowDocAgent
        from wiki.agents.topic_doc_agent import TopicDocAgent

        mock_page = MagicMock()
        with patch("wiki.page_agent.WikiPageAgent", return_value=mock_page):
            flow = FlowDocAgent("f", "d", llm=MagicMock(), graph_store=MagicMock())
            topic = TopicDocAgent("t", "d", llm=MagicMock(), graph_store=MagicMock())

        # Looser than TopicDoc (0.95 / 0.5 tier 1): flow accepts 0.9+ and citation 0.4+
        q = QualityResult(
            coverage=0.91,
            citation_density=0.41,
            context_gap_count=0,
            uncovered_modules=[],
        )
        assert flow.is_acceptable(q, iteration=0) is True
        assert topic.is_acceptable(q, iteration=0) is False

        q_low = QualityResult(
            coverage=0.85,
            citation_density=0.5,
            context_gap_count=0,
            uncovered_modules=["Z"],
        )
        assert flow.is_acceptable(q_low, iteration=0) is False
        assert flow.is_acceptable(q_low, iteration=1) is False
        assert flow.is_acceptable(q_low, iteration=2) is True
        assert topic.is_acceptable(q_low, iteration=2) is False

        q_bad = QualityResult(
            coverage=0.1,
            citation_density=0.0,
            context_gap_count=5,
            uncovered_modules=["a"],
        )
        assert flow.is_acceptable(q_bad, iteration=2) is False
        assert flow.is_acceptable(q_bad, iteration=3) is False


class TestFlowDocAgentGenerate:
    @pytest.mark.asyncio
    async def test_generate_produces_flow_page(self):
        from wiki.agents.flow_doc_agent import FlowDocAgent
        from wiki.path_conventions import domain_topic_path

        mock_page = MagicMock()
        mock_page.create_memory.return_value = WorkingMemory()
        mock_page.run_tool_loop = AsyncMock(return_value=WorkingMemory())
        mock_page.run_generation = AsyncMock(
            return_value="# Checkout\n\ncheckout module `com.foo.Checkout`",
        )
        mock_page.memory_to_prompt.return_value = ""

        with patch("wiki.page_agent.WikiPageAgent", return_value=mock_page):
            agent = FlowDocAgent(
                "Checkout",
                "pay",
                llm=MagicMock(),
                graph_store=MagicMock(),
            )
            agent._page_agent = mock_page

        qr = QualityReport(
            coverage=0.95,
            citation_density=0.5,
            context_gap_count=0,
            uncovered_modules=[],
        )
        with patch("wiki.agents.flow_doc_agent.evaluate_quality", return_value=qr):
            pages = await agent.generate(
                module_names=["com.foo.Checkout"],
                baseline_context="## baseline",
            )

        assert len(pages) == 1
        assert pages[0]["page_type"] == "business_flow"
        assert pages[0]["title"] == "Checkout"
        assert pages[0]["path"] == domain_topic_path("pay", "Checkout")
        mock_page.create_memory.assert_called_once()
        mock_page.run_tool_loop.assert_awaited()
        mock_page.run_generation.assert_awaited()
