"""Tests for business wiki tree UIDs, persistence, and code_structure view."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from store.schema import GraphNode, NodeLabel
from tests.wiki_config_inject import inject_wiki_embedding
from wiki.service import WikiService
from wiki.tree_builder import WikiTreeBuilder


def _mock_graph_for_business_wiki(module_by_repo: dict[str, list[GraphNode]]):
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
    return g


def _wiki_store_mock(repos: list[dict[str, object]]):
    mock_wiki_store = AsyncMock()
    mock_wiki_store.list_indexed_repositories = AsyncMock(return_value=repos)
    mock_wiki_store.upsert_wiki_space = AsyncMock()
    mock_wiki_store.upsert_wiki_section = AsyncMock()
    mock_wiki_store.add_has_child_edge = AsyncMock()
    mock_wiki_store.find_source_entity_mappings = AsyncMock(return_value=[])
    mock_wiki_store.find_code_entity_relationships = AsyncMock(return_value=[])
    mock_wiki_store.get_repo_wiki_freshness = AsyncMock(return_value={})
    return mock_wiki_store


def _graph_module(repo: str, name: str) -> GraphNode:
    return GraphNode(
        uid=f"Module:{repo}:{name}",
        label=NodeLabel.MODULE,
        properties={"name": name, "path": name},
    )


def test_wiki_space_created_with_correct_uid():
    assert WikiTreeBuilder().generate_space_uid("my-biz") == "WikiSpace:my-biz"


def test_wiki_section_uid_for_domain():
    assert (
        WikiTreeBuilder().generate_domain_section_uid("my-biz", "用户管理")
        == "WikiSection:my-biz:domain:用户管理"
    )


def test_wiki_section_uid_for_repo():
    assert (
        WikiTreeBuilder().generate_repo_section_uid("my-biz", "user-service")
        == "WikiSection:my-biz:repo:user-service"
    )


def test_content_hash_computed():
    builder = WikiTreeBuilder()
    h1 = builder.compute_content_hash("same")
    h2 = builder.compute_content_hash("same")
    assert h1 == h2
    assert len(h1) == 64


def test_naming_conflict_detection():
    builder = WikiTreeBuilder()
    pages = [
        {"repository": "repo-a", "entity_name": "OrderService"},
        {"repository": "repo-b", "entity_name": "OrderService"},
    ]
    conflicts = builder.detect_naming_conflicts(pages)
    assert conflicts == {"OrderService": ["repo-a", "repo-b"]}


@pytest.mark.asyncio
async def test_domain_tree_persisted_to_store():
    module_by_repo = {"svc": [_graph_module("svc", "core")]}
    graph = _mock_graph_for_business_wiki(module_by_repo)
    mock_wiki_store = _wiki_store_mock([{"repository": "svc", "module_count": 1}])
    mock_store = AsyncMock()
    mock_store.persist_wiki_pages = AsyncMock()
    mock_store.execute_query = AsyncMock()
    mock_store.set_node_embedding = AsyncMock()

    mock_wiki_cfg = MagicMock()
    mock_wiki_cfg.cross_repo_domain_enabled = True
    mock_wiki_cfg.business_domain_enabled = True
    mock_wiki_cfg.business_domain_infrastructure_label = "__infrastructure__"
    mock_wiki_cfg.enrichment_enabled = False
    mock_wiki_cfg.code_budget_enabled = False
    mock_wiki_cfg.rag_enabled = False
    mock_wiki_cfg.business_wiki_batch_threshold = 100
    mock_wiki_cfg.confidence_scoring_enabled = False
    _, emb = inject_wiki_embedding()
    svc = WikiService(
        graph=graph,
        llm=None,
        repository_exists=AsyncMock(return_value=True),
        store=mock_store,
        wiki_store=mock_wiki_store,
        wiki_config=mock_wiki_cfg,
        embedding_config=emb,
    )

    await svc.generate_business_wiki("biz-x", language="en")

    mock_wiki_store.upsert_wiki_space.assert_awaited()
    mock_wiki_store.upsert_wiki_section.assert_awaited()
    mock_wiki_store.add_has_child_edge.assert_awaited()


@pytest.mark.asyncio
async def test_code_structure_view_tree():
    module_by_repo = {
        "repo-b": [_graph_module("repo-b", "bmod")],
        "repo-a": [_graph_module("repo-a", "amod")],
    }
    graph = _mock_graph_for_business_wiki(module_by_repo)
    mock_wiki_store = _wiki_store_mock([
        {"repository": "repo-b", "module_count": 1},
        {"repository": "repo-a", "module_count": 1},
    ])
    mock_store = AsyncMock()
    mock_store.persist_wiki_pages = AsyncMock()
    mock_store.execute_query = AsyncMock()
    mock_store.set_node_embedding = AsyncMock()

    mock_wiki_cfg = MagicMock()
    mock_wiki_cfg.cross_repo_domain_enabled = True
    mock_wiki_cfg.business_domain_enabled = True
    mock_wiki_cfg.business_domain_infrastructure_label = "__infrastructure__"
    mock_wiki_cfg.enrichment_enabled = False
    mock_wiki_cfg.code_budget_enabled = False
    mock_wiki_cfg.rag_enabled = False
    mock_wiki_cfg.business_wiki_batch_threshold = 100
    mock_wiki_cfg.confidence_scoring_enabled = False
    _, emb = inject_wiki_embedding()
    svc = WikiService(
        graph=graph,
        llm=None,
        repository_exists=AsyncMock(return_value=True),
        store=mock_store,
        wiki_store=mock_wiki_store,
        wiki_config=mock_wiki_cfg,
        embedding_config=emb,
    )
    svc.generate = AsyncMock(return_value={})

    await svc.generate_business_wiki("biz-tree", language="en")

    code_edges = [
        c
        for c in mock_wiki_store.add_has_child_edge.await_args_list
        if c.kwargs.get("view_type") == "code_structure"
    ]
    assert len(code_edges) == 2
    assert code_edges[0].kwargs["child_uid"] == "WikiSection:biz-tree:repo:repo-a"
    assert code_edges[0].kwargs["sort_order"] == 0
    assert code_edges[1].kwargs["child_uid"] == "WikiSection:biz-tree:repo:repo-b"
    assert code_edges[1].kwargs["sort_order"] == 1
    assert code_edges[0].kwargs["parent_uid"] == "WikiSpace:biz-tree"

    code_sections = [
        c
        for c in mock_wiki_store.upsert_wiki_section.await_args_list
        if c.kwargs.get("section_type") == "code_module"
    ]
    assert len(code_sections) == 2
    titles = [c.kwargs["title"] for c in code_sections]
    assert titles == ["repo-a", "repo-b"]


@pytest.mark.asyncio
async def test_domain_and_repo_same_name_distinct_section_uids():
    """Domain section and repo section must not share a UID when names match."""
    shared = "same-name"
    module_by_repo = {shared: [_graph_module(shared, "core")]}
    graph = _mock_graph_for_business_wiki(module_by_repo)
    mock_wiki_store = _wiki_store_mock([{"repository": shared, "module_count": 1}])
    mock_store = AsyncMock()
    mock_store.persist_wiki_pages = AsyncMock()
    mock_store.execute_query = AsyncMock()
    mock_store.set_node_embedding = AsyncMock()

    mock_wiki_cfg = MagicMock()
    mock_wiki_cfg.cross_repo_domain_enabled = True
    mock_wiki_cfg.business_domain_enabled = True
    mock_wiki_cfg.business_domain_infrastructure_label = "__infrastructure__"
    mock_wiki_cfg.enrichment_enabled = False
    mock_wiki_cfg.code_budget_enabled = False
    mock_wiki_cfg.rag_enabled = False
    mock_wiki_cfg.business_wiki_batch_threshold = 100
    mock_wiki_cfg.confidence_scoring_enabled = False
    _, emb = inject_wiki_embedding()
    svc = WikiService(
        graph=graph,
        llm=None,
        repository_exists=AsyncMock(return_value=True),
        store=mock_store,
        wiki_store=mock_wiki_store,
        wiki_config=mock_wiki_cfg,
        embedding_config=emb,
    )
    svc.generate = AsyncMock(return_value={})

    planner_inst = MagicMock()
    planner_inst.classify = AsyncMock(
        return_value={shared: [(shared, "core")]},
    )

    with patch(
        "wiki.cross_repo_domain_planner.CrossRepoBusinessDomainPlanner",
        return_value=planner_inst,
    ):
        await svc.generate_business_wiki("biz-collision", language="en")

    tb = WikiTreeBuilder()
    domain_uid = tb.generate_domain_section_uid("biz-collision", shared)
    repo_uid = tb.generate_repo_section_uid("biz-collision", shared)
    assert domain_uid != repo_uid

    section_uids = {
        c.kwargs["uid"] for c in mock_wiki_store.upsert_wiki_section.await_args_list
    }
    assert domain_uid in section_uids
    assert repo_uid in section_uids
