"""generate_business_wiki passes token_budget_multiplier to generate()."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from store.schema import GraphNode, NodeLabel
from tests.wiki_config_inject import inject_wiki_embedding
from wiki.service import WikiService


def _biz_wiki_mock():
    m = MagicMock()
    m.cross_repo_domain_enabled = True
    m.business_domain_enabled = True
    m.business_domain_infrastructure_label = "__infrastructure__"
    m.enrichment_enabled = False
    m.code_budget_enabled = False
    m.rag_enabled = False
    m.business_wiki_batch_threshold = 100
    return m


def _mock_graph():
    g = AsyncMock()
    g.list_repository_modules = AsyncMock(return_value=[])
    return g


@pytest.mark.asyncio
async def test_generate_business_wiki_passes_token_budget_multiplier_to_generate() -> None:
    """Custom multiplier must be forwarded to per-repo generate() calls."""
    graph = _mock_graph()
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value='{"__infrastructure__": [["test-repo", "mod"]]}')
    mock_store = AsyncMock()
    mock_wiki_store = AsyncMock()
    mock_wiki_store.list_indexed_repositories = AsyncMock(return_value=[
        {"repository": "test-repo", "module_count": 1}
    ])
    mock_wiki_store.upsert_wiki_space = AsyncMock()
    mock_wiki_store.upsert_wiki_section = AsyncMock()
    mock_wiki_store.add_has_child_edge = AsyncMock()
    mock_wiki_store.find_source_entity_mappings = AsyncMock(return_value=[])
    mock_wiki_store.find_code_entity_relationships = AsyncMock(return_value=[])

    graph.list_repository_modules = AsyncMock(
        return_value=[
            GraphNode(
                uid="Module:test-repo:mod",
                label=NodeLabel.MODULE,
                properties={"name": "mod", "path": "mod"},
            ),
        ],
    )

    _, emb = inject_wiki_embedding()
    svc = WikiService(
        graph=graph,
        llm=llm,
        repository_exists=AsyncMock(return_value=True),
        store=mock_store,
        wiki_store=mock_wiki_store,
        wiki_config=_biz_wiki_mock(),
        embedding_config=emb,
    )
    svc.generate = AsyncMock(return_value={})

    await svc.generate_business_wiki(
        business_id="test-biz",
        language="en",
        token_budget_multiplier=2.5,
    )

    svc.generate.assert_awaited()
    kwargs = svc.generate.await_args.kwargs
    assert kwargs.get("token_budget_multiplier") == 2.5
