import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from tests.wiki_config_inject import inject_wiki_embedding
from wiki.service import WikiService


def _mock_graph():
    g = AsyncMock()
    g.find_top_level_modules = AsyncMock(return_value=[])
    g.list_repository_modules = AsyncMock(return_value=[])
    g.find_children = AsyncMock(return_value=[])
    g.find_edges = AsyncMock(return_value=[])
    g.find_node_by_fqn = AsyncMock(return_value=None)
    g.find_node_by_path = AsyncMock(return_value=None)
    return g


def _mock_wiki_cfg():
    cfg = MagicMock()
    cfg.cross_repo_domain_enabled = True
    cfg.business_domain_enabled = True
    cfg.business_domain_infrastructure_label = "__infrastructure__"
    cfg.enrichment_enabled = False
    cfg.code_budget_enabled = False
    cfg.rag_enabled = False
    cfg.business_wiki_batch_threshold = 100
    cfg.business_domain_sub_batch_size = 80
    cfg.business_domain_classify_timeout = 600
    cfg.business_domain_max_concurrency = 3
    cfg.business_domain_cache_ttl = 3600
    return cfg


@pytest.mark.asyncio
async def test_generate_business_wiki_calls_reference_generator():
    """generate_business_wiki should invoke WikiReferenceGenerator."""
    graph = _mock_graph()

    mock_wiki_store = AsyncMock()
    mock_wiki_store.list_indexed_repositories = AsyncMock(
        return_value=[
            {"repository": "r1", "module_count": 1},
        ],
    )
    mock_wiki_store.upsert_wiki_space = AsyncMock()
    mock_wiki_store.upsert_wiki_section = AsyncMock()
    mock_wiki_store.add_has_child_edge = AsyncMock()
    mock_wiki_store.find_source_entity_mappings = AsyncMock(
        return_value=[
            {"wiki_uid": "WikiPage:r1:A.md", "entity_uid": "Class:r1:A", "path": "A.md", "repository": "r1"},
            {"wiki_uid": "WikiPage:r1:B.md", "entity_uid": "Class:r1:B", "path": "B.md", "repository": "r1"},
        ],
    )
    mock_wiki_store.find_code_entity_relationships = AsyncMock(
        return_value=[
            {"source_uid": "Class:r1:A", "target_uid": "Class:r1:B", "rel_type": "CALLS"},
        ],
    )
    mock_wiki_store.add_wiki_reference_edge = AsyncMock()
    mock_wiki_store.get_repo_wiki_freshness = AsyncMock(return_value={})
    mock_wiki_store.get_wiki_pages_for_business = AsyncMock(return_value=[])

    _, emb = inject_wiki_embedding()
    svc = WikiService(
        graph=graph,
        llm=None,
        repository_exists=AsyncMock(return_value=True),
        wiki_store=mock_wiki_store,
        wiki_config=_mock_wiki_cfg(),
        embedding_config=emb,
    )

    result = await svc.generate_business_wiki("biz")
    assert result["references_count"] >= 1
    mock_wiki_store.add_wiki_reference_edge.assert_awaited()


@pytest.mark.asyncio
async def test_reference_generation_failure_does_not_crash():
    """WikiReferenceGenerator failure should not crash business wiki generation."""
    graph = _mock_graph()

    mock_wiki_store = AsyncMock()
    mock_wiki_store.list_indexed_repositories = AsyncMock(
        return_value=[
            {"repository": "r1", "module_count": 1},
        ],
    )
    mock_wiki_store.upsert_wiki_space = AsyncMock()
    mock_wiki_store.upsert_wiki_section = AsyncMock()
    mock_wiki_store.add_has_child_edge = AsyncMock()
    mock_wiki_store.get_repo_wiki_freshness = AsyncMock(return_value={})
    mock_wiki_store.get_wiki_pages_for_business = AsyncMock(return_value=[])

    _, emb = inject_wiki_embedding()
    svc = WikiService(
        graph=graph,
        llm=None,
        repository_exists=AsyncMock(return_value=True),
        wiki_store=mock_wiki_store,
        wiki_config=_mock_wiki_cfg(),
        embedding_config=emb,
    )

    mock_gen_cls = MagicMock()
    mock_inst = MagicMock()
    mock_inst.generate = AsyncMock(side_effect=RuntimeError("reference generation failed"))
    mock_gen_cls.return_value = mock_inst

    with patch(
        "wiki.reference_generator.WikiReferenceGenerator",
        mock_gen_cls,
    ):
        result = await svc.generate_business_wiki("biz-ref-fail")
    assert "pages_count" in result
    assert result.get("references_count", 0) == 0


@pytest.mark.asyncio
async def test_generate_business_wiki_empty_repos_skips_references():
    """When no repos are indexed, return early without reference generation."""
    graph = _mock_graph()

    mock_wiki_store = AsyncMock()
    mock_wiki_store.list_indexed_repositories = AsyncMock(return_value=[])

    _, emb = inject_wiki_embedding()
    svc = WikiService(
        graph=graph,
        llm=None,
        repository_exists=AsyncMock(return_value=True),
        wiki_store=mock_wiki_store,
        wiki_config=_mock_wiki_cfg(),
        embedding_config=emb,
    )

    result = await svc.generate_business_wiki("empty-biz")
    assert "pages_count" in result
