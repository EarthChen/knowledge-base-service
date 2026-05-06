from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_compose_single_leaf_domain_with_ccb():
    """When graph_store is provided, should use CCB + compose_leaf_domain_from_context."""
    from wiki.pipeline_nodes import _compose_single_leaf_domain

    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(
        return_value='{"executive_summary": "Test summary", "content": "## 业务概述\\nContent here"}'
    )

    mock_graph = AsyncMock()
    mock_graph.execute_query = AsyncMock(return_value=MagicMock(data=[]))

    mock_wiki = AsyncMock()
    mock_wiki.execute_query = AsyncMock(return_value=MagicMock(data=[]))

    leaf = {"name": "payment", "modules": ["PaymentSvc"], "parent": "commerce"}
    module_index = {
        "PaymentSvc": [
            {
                "uid": "Module::PaymentSvc:0",
                "properties": {
                    "name": "PaymentSvc",
                    "business_summary": "Process payments",
                    "file": "pay.java",
                },
                "_repo": "repo1",
            }
        ]
    }
    entity_roles = {"Module::PaymentSvc:0": "has_business_logic"}
    domain_mapping = {"payment": [("repo1", "PaymentSvc")]}

    with patch("wiki.content_context_builder.ContentContextBuilder.build_context", new_callable=AsyncMock) as mock_build:
        from wiki.content_context_builder import EnrichedDomainContext
        mock_build.return_value = EnrichedDomainContext(
            domain_name="payment",
            parent_domain="commerce",
        )
        pages, paths = await _compose_single_leaf_domain(
            leaf,
            module_index,
            entity_roles,
            mock_llm,
            8000,
            graph_store=mock_graph,
            wiki_store=mock_wiki,
            domain_mapping=domain_mapping,
        )
        mock_build.assert_awaited_once()

    assert len(pages) >= 1
    assert pages[0].get("content")
    assert paths


@pytest.mark.asyncio
async def test_compose_single_leaf_domain_without_ccb_fallback():
    """Without graph_store, should use existing code path."""
    from wiki.pipeline_nodes import _compose_single_leaf_domain

    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(
        return_value='{"executive_summary": "Test", "content": "## 业务概述\\nOld path"}'
    )

    leaf = {"name": "test", "modules": ["Svc"], "parent": "root"}
    module_index = {
        "Svc": [
            {
                "uid": "Module::Svc:0",
                "properties": {"name": "Svc", "business_summary": "test"},
                "_repo": "r",
            }
        ]
    }
    entity_roles = {"Module::Svc:0": "has_business_logic"}

    pages, paths = await _compose_single_leaf_domain(
        leaf,
        module_index,
        entity_roles,
        mock_llm,
        8000,
    )

    assert isinstance(pages, list)
    assert isinstance(paths, list)


@pytest.mark.asyncio
async def test_compose_ccb_failure_falls_back_to_legacy():
    """When CCB raises, should fall through to legacy path instead of returning empty."""
    from wiki.pipeline_nodes import _compose_single_leaf_domain

    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(
        return_value='{"executive_summary": "Legacy", "content": "## 业务概述\\nLegacy content"}'
    )

    mock_graph = AsyncMock()
    mock_graph.execute_query = AsyncMock(side_effect=RuntimeError("graph down"))

    leaf = {"name": "order", "modules": ["OrderSvc"], "parent": "root"}
    module_index = {
        "OrderSvc": [
            {
                "uid": "Module::OrderSvc:0",
                "properties": {"name": "OrderSvc", "business_summary": "orders", "file": "o.java"},
                "_repo": "r",
            }
        ]
    }
    entity_roles = {"Module::OrderSvc:0": "has_business_logic"}

    pages, paths = await _compose_single_leaf_domain(
        leaf,
        module_index,
        entity_roles,
        mock_llm,
        8000,
        graph_store=mock_graph,
    )

    assert isinstance(pages, list)
    assert len(pages) >= 1, "Should have fallen back to legacy path, not empty"
