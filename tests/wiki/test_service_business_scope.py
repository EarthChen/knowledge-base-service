import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from store.schema import GraphNode, NodeLabel
from wiki.service import WikiService


def _mock_graph():
    g = AsyncMock()
    g.find_modules = AsyncMock(return_value=[])
    g.find_children = AsyncMock(return_value=[])
    g.find_edges = AsyncMock(return_value=[])
    g.find_node_by_fqn = AsyncMock(return_value=None)
    g.find_node_by_path = AsyncMock(return_value=None)
    g.find_top_level_modules = AsyncMock(return_value=[])
    g.list_repository_modules = AsyncMock(return_value=[])
    return g


@pytest.mark.asyncio
async def test_generate_business_wiki_returns_result():
    """generate_business_wiki should return a dict with domains and pages_count."""
    graph = _mock_graph()
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value='{"__infrastructure__": [["test-repo", "mod"]]}')
    mock_store = AsyncMock()
    mock_store.persist_wiki_pages = AsyncMock()
    mock_store.execute_query = AsyncMock()
    mock_store.set_node_embedding = AsyncMock()
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

    svc = WikiService(
        graph=graph,
        llm=llm,
        repository_exists=AsyncMock(return_value=True),
        store=mock_store,
        wiki_store=mock_wiki_store,
    )

    with patch("wiki.service.get_settings") as mock_settings:
        mock_wiki_cfg = MagicMock()
        mock_wiki_cfg.cross_repo_domain_enabled = True
        mock_wiki_cfg.business_domain_enabled = True
        mock_wiki_cfg.business_domain_infrastructure_label = "__infrastructure__"
        mock_wiki_cfg.enrichment_enabled = False
        mock_wiki_cfg.code_budget_enabled = False
        mock_wiki_cfg.rag_enabled = False
        mock_wiki_cfg.business_wiki_batch_threshold = 100
        mock_settings.return_value.wiki = mock_wiki_cfg
        mock_settings.return_value.embedding = MagicMock()

        result = await svc.generate_business_wiki(
            business_id="test-biz",
            language="en",
        )
        assert "domains" in result
        assert "pages_count" in result


@pytest.mark.asyncio
async def test_generate_business_wiki_without_llm():
    """Without LLM, all modules go to infrastructure domain."""
    graph = _mock_graph()
    mock_wiki_store = AsyncMock()
    mock_wiki_store.list_indexed_repositories = AsyncMock(return_value=[
        {"repository": "repo-a", "module_count": 1}
    ])
    mock_wiki_store.upsert_wiki_space = AsyncMock()
    mock_wiki_store.upsert_wiki_section = AsyncMock()
    mock_wiki_store.add_has_child_edge = AsyncMock()
    mock_wiki_store.find_source_entity_mappings = AsyncMock(return_value=[])
    mock_wiki_store.find_code_entity_relationships = AsyncMock(return_value=[])

    svc = WikiService(
        graph=graph,
        llm=None,
        repository_exists=AsyncMock(return_value=True),
        wiki_store=mock_wiki_store,
    )

    with patch("wiki.service.get_settings") as mock_settings:
        mock_wiki_cfg = MagicMock()
        mock_wiki_cfg.cross_repo_domain_enabled = True
        mock_wiki_cfg.business_domain_enabled = True
        mock_wiki_cfg.business_domain_infrastructure_label = "__infrastructure__"
        mock_wiki_cfg.enrichment_enabled = False
        mock_wiki_cfg.code_budget_enabled = False
        mock_wiki_cfg.rag_enabled = False
        mock_wiki_cfg.business_wiki_batch_threshold = 100
        mock_settings.return_value.wiki = mock_wiki_cfg

        result = await svc.generate_business_wiki(
            business_id="biz",
            language="en",
        )
        assert isinstance(result.get("domains"), list)
        assert isinstance(result.get("pages_count"), int)


@pytest.mark.asyncio
async def test_generate_business_wiki_empty_repos():
    """When no repos are indexed, return empty result immediately."""
    graph = _mock_graph()
    mock_wiki_store = AsyncMock()
    mock_wiki_store.list_indexed_repositories = AsyncMock(return_value=[])

    svc = WikiService(
        graph=graph,
        llm=None,
        repository_exists=AsyncMock(return_value=True),
        wiki_store=mock_wiki_store,
    )

    with patch("wiki.service.get_settings") as mock_settings:
        mock_wiki_cfg = MagicMock()
        mock_wiki_cfg.rag_enabled = False
        mock_settings.return_value.wiki = mock_wiki_cfg

        result = await svc.generate_business_wiki(business_id="empty-biz")
        assert result["domains"] == []
        assert result["pages_count"] == 0
