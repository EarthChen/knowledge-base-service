"""Tests that LangGraph resolved_links become WIKI_REFERENCES on business wiki generation."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from store.schema import GraphNode, NodeLabel
from tests.wiki_config_inject import inject_wiki_embedding
from wiki.models import PageType, WikiPage, WikiPageMetadata
from wiki.pipeline_orchestrator import PipelineResult
from wiki.service import WikiService


def _mock_graph(module_by_repo: dict[str, list[GraphNode]]):
    """Same breadth as sibling business-wiki tests (domain persist + RelatedPagesBuilder)."""
    g = AsyncMock()
    g.find_modules = AsyncMock(return_value=[])
    g.find_children = AsyncMock(return_value=[])
    g.find_edges = AsyncMock(return_value=[])
    g.find_node_by_fqn = AsyncMock(return_value=None)
    g.find_node_by_path = AsyncMock(return_value=None)
    g.find_top_level_modules = AsyncMock(return_value=[])
    g.list_repository_modules = AsyncMock(
        side_effect=lambda repo: module_by_repo.get(repo, []),
    )
    g.find_module_import_edges = AsyncMock(return_value=[])
    g.find_repository_calls_edges = AsyncMock(return_value=[])
    g.update_node_property = AsyncMock()
    g.find_descendants = AsyncMock(return_value=[])
    return g


def _graph_module(repo: str, name: str) -> GraphNode:
    return GraphNode(
        uid=f"Module:{repo}:{name}",
        label=NodeLabel.MODULE,
        properties={"name": name, "path": name},
    )


def _wiki_store_stub(repos: list[dict[str, object]]) -> AsyncMock:
    ws = AsyncMock()
    ws.list_indexed_repositories = AsyncMock(return_value=repos)
    ws.upsert_wiki_space = AsyncMock()
    ws.upsert_wiki_section = AsyncMock()
    ws.add_has_child_edge = AsyncMock()
    ws.find_source_entity_mappings = AsyncMock(return_value=[])
    ws.find_code_entity_relationships = AsyncMock(return_value=[])
    ws.get_repo_wiki_freshness = AsyncMock(return_value={})
    ws.add_wiki_reference_edge = AsyncMock()
    return ws


@pytest.mark.asyncio
async def test_generate_business_wiki_persists_resolved_links() -> None:
    biz = "biz-wl"
    module_by_repo = {"svc": [_graph_module("svc", "core")]}
    graph = _mock_graph(module_by_repo)
    wiki_store = _wiki_store_stub([{"repository": "svc", "module_count": 1}])
    mock_store = AsyncMock()
    mock_store.persist_wiki_pages = AsyncMock()
    mock_store.execute_query = AsyncMock()
    mock_store.set_node_embedding = AsyncMock()

    wiki_cfg = MagicMock()
    wiki_cfg.cross_repo_domain_enabled = True
    wiki_cfg.business_domain_enabled = True
    wiki_cfg.business_domain_infrastructure_label = "__infrastructure__"
    wiki_cfg.enrichment_enabled = False
    wiki_cfg.code_budget_enabled = False
    wiki_cfg.rag_enabled = False
    wiki_cfg.business_wiki_batch_threshold = 100
    wiki_cfg.business_domain_sub_batch_size = 80
    wiki_cfg.business_domain_classify_timeout = 600
    wiki_cfg.business_domain_max_concurrency = 3
    wiki_cfg.business_domain_cache_ttl = 3600
    wiki_cfg.confidence_scoring_enabled = False

    meta = WikiPageMetadata(node_count=0, edge_count=0)

    stub_pages = [
        WikiPage(
            path="wiki/a",
            title="Alpha",
            page_type=PageType.DOMAIN_OVERVIEW,
            content="see [[Beta]]",
            diagrams=[],
            source_locations=[],
            metadata=meta,
        ),
        WikiPage(
            path="wiki/b",
            title="Beta",
            page_type=PageType.DOMAIN_OVERVIEW,
            content="Beta page",
            diagrams=[],
            source_locations=[],
            metadata=meta,
        ),
    ]
    stub_result = PipelineResult(
        domain_mapping={"pay": [("svc", "core")]},
        domain_tree=None,
        pages=stub_pages,
        resolved_links={
            "wiki/a": [{"from_text": "Beta", "target_path": "wiki/b"}],
        },
        entity_roles={},
    )

    _, emb = inject_wiki_embedding()
    svc = WikiService(
        graph=graph,
        llm=None,
        repository_exists=AsyncMock(return_value=True),
        store=mock_store,
        wiki_store=wiki_store,
        wiki_config=wiki_cfg,
        embedding_config=emb,
    )
    svc.generate = AsyncMock(return_value={})

    with patch(
        "wiki.pipeline_orchestrator.run_langgraph_pipeline",
        new_callable=AsyncMock,
        return_value=stub_result,
    ):
        await svc.generate_business_wiki(biz, language="en", incremental=False)

    wiki_store.add_wiki_reference_edge.assert_awaited_once()
    call = wiki_store.add_wiki_reference_edge.await_args
    assert call.kwargs["source_uid"] == WikiService._business_wikipage_uid(biz, "wiki/a")
    assert call.kwargs["target_uid"] == WikiService._business_wikipage_uid(biz, "wiki/b")
    assert call.kwargs["relation_type"] == "wikilink"
    assert call.kwargs["context"] == "Beta"
    assert call.kwargs["auto_generated"] is True
