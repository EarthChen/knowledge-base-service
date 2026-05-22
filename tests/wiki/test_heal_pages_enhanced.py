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
        "config": {"importance_tiers": {"test-page": "standard"}},
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
        "config": {"importance_tiers": {"gap-page": "standard"}},
        "modules": {},
    }

    mock_llm = MagicMock()
    mock_graph = AsyncMock()
    config = {"configurable": {"llm": mock_llm, "graph_store": mock_graph}}

    # Content must have CONTEXT_GAP AND be < 100 chars after cleanup to trigger enrich
    still_gappy = "<!-- CONTEXT_GAP: short gap -->\n\nTiny."
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


@pytest.mark.asyncio
async def test_enrich_skipped_when_content_is_short_but_no_context_gap():
    """When content is between 100-200 chars but has NO CONTEXT_GAP marker, enrich should NOT fire (AND logic)."""
    from wiki.models import WikiPage
    from wiki.nodes.heal import heal_pages_node

    page_row = {
        "path": "short-page",
        "title": "Short Page",
        "content": "# Short\n\nold content.",
        "page_type": "module_overview",
        "diagrams": [],
        "source_locations": [],
        "method_locations": [],
        "metadata": {"node_count": 0, "edge_count": 0, "generation_mode": "structure"},
    }
    state = {
        "pages": [dict(page_row)],
        "pages_to_heal": ["short-page"],
        "heal_attempts": {},
        "heal_hints": {},
        "quality_scores": {"short-page": {"l1_structural": 0.3, "overall": 0.3}},
        "config": {"importance_tiers": {"short-page": "standard"}},
        "modules": {},
    }

    mock_llm = MagicMock()
    mock_graph = AsyncMock()
    config = {"configurable": {"llm": mock_llm, "graph_store": mock_graph}}

    # Targeted healer returns content that is short (between 100-200 chars) but has NO context gap
    short_clean_content = "## 业务概述\n\nBrief overview only, no gap marker present here at all for testing purposes."
    patched_page = WikiPage.from_dict({**page_row, "content": short_clean_content})

    with patch("wiki.targeted_healer.TargetedHealer") as MockHealer:
        mock_healer = MagicMock()
        mock_healer.heal = AsyncMock(return_value=patched_page)
        MockHealer.return_value = mock_healer

        with patch("wiki.nodes.heal.WikiPageAgent") as MockAgent:
            mock_agent_instance = AsyncMock()
            mock_agent_instance.enrich = AsyncMock(return_value="enriched")
            MockAgent.return_value = mock_agent_instance

            await heal_pages_node(state, config)

        # Enrich should NOT be called: no CONTEXT_GAP, and content length >= 100
        mock_agent_instance.enrich.assert_not_awaited()


@pytest.mark.asyncio
async def test_enrich_fires_when_both_short_and_context_gap():
    """Enrich fires only when content has CONTEXT_GAP AND is < 100 chars after cleanup."""
    from wiki.models import WikiPage
    from wiki.nodes.heal import heal_pages_node

    page_row = {
        "path": "gap-short-page",
        "title": "Gap Short Page",
        "content": "# X\n\n<!-- CONTEXT_GAP: original -->\n\nold.",
        "page_type": "module_overview",
        "diagrams": [],
        "source_locations": [],
        "method_locations": [],
        "metadata": {"node_count": 0, "edge_count": 0, "generation_mode": "structure"},
    }
    state = {
        "pages": [dict(page_row)],
        "pages_to_heal": ["gap-short-page"],
        "heal_attempts": {},
        "heal_hints": {},
        "quality_scores": {"gap-short-page": {"l1_structural": 0.3, "overall": 0.3}},
        "config": {"importance_tiers": {"gap-short-page": "standard"}},
        "modules": {},
    }

    mock_llm = MagicMock()
    mock_graph = AsyncMock()
    config = {"configurable": {"llm": mock_llm, "graph_store": mock_graph}}

    # Content has CONTEXT_GAP but is >= 100 chars after cleanup
    long_but_gappy = (
        "## 业务概述\n\nThis is a reasonably long content section that exceeds one hundred characters easily.\n\n"
        "<!-- CONTEXT_GAP: targeted healer left this -->\n\n"
        "## 核心业务流程\n\nMore content here to pad the length out past 100 chars."
    )
    patched_page = WikiPage.from_dict({**page_row, "content": long_but_gappy})

    with patch("wiki.targeted_healer.TargetedHealer") as MockHealer:
        mock_healer = MagicMock()
        mock_healer.heal = AsyncMock(return_value=patched_page)
        MockHealer.return_value = mock_healer

        with patch("wiki.nodes.heal.WikiPageAgent") as MockAgent:
            mock_agent_instance = AsyncMock()
            mock_agent_instance.enrich = AsyncMock(return_value="enriched")
            MockAgent.return_value = mock_agent_instance

            await heal_pages_node(state, config)

        # Under new AND logic: has CONTEXT_GAP but content >= 100 chars, so enrich should NOT fire
        mock_agent_instance.enrich.assert_not_awaited()


@pytest.mark.asyncio
async def test_enrich_fires_when_context_gap_and_very_short():
    """Enrich fires when content has CONTEXT_GAP AND is < 100 chars after cleanup."""
    from wiki.models import WikiPage
    from wiki.nodes.heal import heal_pages_node

    page_row = {
        "path": "tiny-gap-page",
        "title": "Tiny Gap Page",
        "content": "# X\n\n<!-- CONTEXT_GAP: original -->\n\nold.",
        "page_type": "module_overview",
        "diagrams": [],
        "source_locations": [],
        "method_locations": [],
        "metadata": {"node_count": 0, "edge_count": 0, "generation_mode": "structure"},
    }
    state = {
        "pages": [dict(page_row)],
        "pages_to_heal": ["tiny-gap-page"],
        "heal_attempts": {},
        "heal_hints": {},
        "quality_scores": {"tiny-gap-page": {"l1_structural": 0.3, "overall": 0.3}},
        "config": {"importance_tiers": {"tiny-gap-page": "standard"}},
        "modules": {},
    }

    mock_llm = MagicMock()
    mock_graph = AsyncMock()
    config = {"configurable": {"llm": mock_llm, "graph_store": mock_graph}}

    # Content has CONTEXT_GAP AND is < 100 chars after cleanup
    short_gappy = "<!-- CONTEXT_GAP: brief -->\n\nShort."
    patched_page = WikiPage.from_dict({**page_row, "content": short_gappy})

    with patch("wiki.targeted_healer.TargetedHealer") as MockHealer:
        mock_healer = MagicMock()
        mock_healer.heal = AsyncMock(return_value=patched_page)
        MockHealer.return_value = mock_healer

        with patch("wiki.nodes.heal.WikiPageAgent") as MockAgent:
            mock_agent_instance = AsyncMock()
            mock_agent_instance.enrich = AsyncMock(return_value="enriched result")
            MockAgent.return_value = mock_agent_instance

            await heal_pages_node(state, config)

        # Both conditions met: CONTEXT_GAP present AND < 100 chars, so enrich SHOULD fire
        mock_agent_instance.enrich.assert_awaited_once()
