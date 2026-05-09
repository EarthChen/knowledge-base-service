import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_heal_uses_agent_enrich_when_graph_store_available():
    """heal_pages_node should pass graph_store to WikiPageAgent.enrich when available."""
    from wiki.nodes.heal import heal_pages_node

    state = {
        "pages": [
            {
                "path": "test-page",
                "title": "Test Page",
                "content": "# Test\n\n<!-- CONTEXT_GAP: missing implementation details -->\n\nShort content.",
                "page_type": "module_overview",
                "diagrams": [],
                "source_locations": [],
                "method_locations": [],
                "metadata": {"node_count": 0, "edge_count": 0, "generation_mode": "structure"},
            }
        ],
        "pages_to_heal": ["test-page"],
        "heal_attempts": {},
        "heal_hints": {},
        "quality_scores": {"test-page": {"l1_structural": 0.3, "overall": 0.3}},
        # Skeleton tier skips strict post-heal structural re-check so one heal round suffices.
        "config": {"importance_tiers": {"test-page": "skeleton"}},
        "modules": {},
    }

    mock_llm = MagicMock(spec_set=["generate"])
    mock_llm.generate = AsyncMock(
        return_value="# Test\n\n## 概述\n\nThis is a well-written test page with proper content and structure.\n\n## 核心业务流程\n\nThe test module handles testing workflows.",
    )
    mock_graph = AsyncMock()

    config = {"configurable": {"llm": mock_llm, "graph_store": mock_graph}}

    with patch("wiki.nodes.heal.WikiPageAgent") as MockAgent:
        mock_agent_instance = AsyncMock()
        mock_agent_instance.enrich = AsyncMock(return_value="# Test\n\n## 概述\n\nEnriched content with graph context.\n\n## 核心业务流程\n\nDetailed flow.")
        MockAgent.return_value = mock_agent_instance

        result = await heal_pages_node(state, config)

    MockAgent.assert_called_once()
    call_kwargs = MockAgent.call_args
    assert call_kwargs[1].get("graph_store") == mock_graph or (len(call_kwargs[0]) > 1 and call_kwargs[0][1] == mock_graph)


@pytest.mark.asyncio
async def test_heal_calls_enrich_after_targeted_when_context_gaps_remain():
    """TargetedHealer may return content that still has CONTEXT_GAP; graph enrich should run too."""
    from wiki.models import WikiPage
    from wiki.nodes.heal import heal_pages_node

    page_row = {
        "path": "gap-page",
        "title": "Gap Page",
        "content": "# X\n\n<!-- CONTEXT_GAP: original -->\n\nold.",
        "page_type": "module_overview",
        "diagrams": [],
        "source_locations": [],
        "method_locations": [],
        "metadata": {"node_count": 0, "edge_count": 0, "generation_mode": "structure"},
    }
    state = {
        "pages": [dict(page_row)],
        "pages_to_heal": ["gap-page"],
        "heal_attempts": {},
        "heal_hints": {},
        "quality_scores": {"gap-page": {"l1_structural": 0.3, "overall": 0.3}},
        "config": {"importance_tiers": {"gap-page": "skeleton"}},
        "modules": {},
    }

    mock_llm = MagicMock()
    mock_graph = AsyncMock()
    config = {"configurable": {"llm": mock_llm, "graph_store": mock_graph}}

    still_gappy = (
        "## 业务概述\n\nBrief.\n\n"
        "<!-- CONTEXT_GAP: targeted healer left this -->\n\n"
        "## 核心业务流程\n\n```mermaid\nsequenceDiagram\n  A->>B: test\n```\n"
    )
    patched_page = WikiPage.from_dict({**page_row, "content": still_gappy})

    with patch("wiki.targeted_healer.TargetedHealer") as MockHealer:
        mock_healer = MagicMock()
        mock_healer.heal = AsyncMock(return_value=patched_page)
        MockHealer.return_value = mock_healer

        with patch("wiki.nodes.heal.WikiPageAgent") as MockAgent:
            mock_agent_instance = AsyncMock()
            mock_agent_instance.enrich = AsyncMock(
                return_value=still_gappy.replace(
                    "<!-- CONTEXT_GAP: targeted healer left this -->",
                    "Filled by graph enrich.",
                )
            )
            MockAgent.return_value = mock_agent_instance

            await heal_pages_node(state, config)

        mock_healer.heal.assert_awaited()

    mock_agent_instance.enrich.assert_awaited_once()
    enriched_input = mock_agent_instance.enrich.await_args[0][0]
    assert "<!-- CONTEXT_GAP" not in enriched_input
    assert "Brief" in enriched_input or "业务概述" in enriched_input
