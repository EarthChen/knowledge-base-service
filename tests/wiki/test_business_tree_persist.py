"""Tests for business wiki tree UIDs, persistence, and code_structure view."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from store.schema import GraphNode, NodeLabel
from tests.wiki_config_inject import inject_wiki_embedding
from wiki.pipeline_orchestrator import PipelineResult
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
    mock_wiki_cfg.business_domain_sub_batch_size = 80
    mock_wiki_cfg.business_domain_classify_timeout = 600
    mock_wiki_cfg.business_domain_max_concurrency = 3
    mock_wiki_cfg.business_domain_cache_ttl = 3600
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
    mock_wiki_cfg.business_domain_sub_batch_size = 80
    mock_wiki_cfg.business_domain_classify_timeout = 600
    mock_wiki_cfg.business_domain_max_concurrency = 3
    mock_wiki_cfg.business_domain_cache_ttl = 3600
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
    mock_wiki_cfg.business_domain_sub_batch_size = 80
    mock_wiki_cfg.business_domain_classify_timeout = 600
    mock_wiki_cfg.business_domain_max_concurrency = 3
    mock_wiki_cfg.business_domain_cache_ttl = 3600
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

    stub_result = PipelineResult(
        domain_mapping={shared: [(shared, "core")]},
        domain_tree=None,
        pages=[],
        resolved_links={},
        entity_roles={},
    )

    with patch(
        "wiki.pipeline_orchestrator.run_langgraph_pipeline",
        new_callable=AsyncMock,
        return_value=stub_result,
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


class TestRecursiveTreeLinking:
    @pytest.mark.asyncio
    async def test_nested_domains_create_nested_sections(self):
        """Nested domain tree upserts WikiSection nodes and HAS_CHILD edges recursively."""
        from wiki.dependency_graph import DomainNode

        module_by_repo = {"svc": [_graph_module("svc", "x")]}
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
        mock_wiki_cfg.business_domain_sub_batch_size = 80
        mock_wiki_cfg.business_domain_classify_timeout = 600
        mock_wiki_cfg.business_domain_max_concurrency = 3
        mock_wiki_cfg.business_domain_cache_ttl = 3600
        mock_wiki_cfg.confidence_scoring_enabled = False

        tb = WikiTreeBuilder()
        business_id = "biz-nested"

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

        domain_tree = [
            DomainNode(
                name="User Management",
                description="Dom",
                modules=["UserController"],
                children=[
                    DomainNode(name="Authentication", modules=["AuthService", "TokenService"]),
                    DomainNode(name="Profile", modules=["ProfileService"]),
                ],
            ),
        ]
        pages_by_entity_uid = {
            "UserController": {"uid": "wp:UserController"},
            "AuthService": {"uid": "wp:AuthService"},
            "TokenService": {"uid": "wp:TokenService"},
            "ProfileService": {"uid": "wp:ProfileService"},
        }

        await svc._link_pages_to_nested_tree(
            business_id, domain_tree, pages_by_entity_uid, tb,
        )

        roots = tb.generate_domain_section_uid(business_id, "__root__")
        assert roots in {
            c.kwargs.get("uid") for c in mock_wiki_store.upsert_wiki_section.await_args_list
        }

        section_names = [
            c.kwargs["title"] for c in mock_wiki_store.upsert_wiki_section.await_args_list
        ]
        assert "User Management" in section_names
        assert "Authentication" in section_names
        assert "Profile" in section_names

        edges = mock_wiki_store.add_has_child_edge.await_args_list

        um_uid = tb.generate_domain_section_uid(business_id, "User Management")
        auth_uid = tb.generate_domain_section_uid(
            business_id, "User Management/Authentication"
        )
        profile_uid = tb.generate_domain_section_uid(
            business_id, "User Management/Profile"
        )

        assert any(
            e.kwargs.get("parent_uid") == tb.generate_space_uid(business_id)
            and e.kwargs.get("child_uid") == roots
            for e in edges
        )
        parent_child = {(e.kwargs["parent_uid"], e.kwargs["child_uid"]) for e in edges}
        assert (roots, um_uid) in parent_child
        assert (um_uid, auth_uid) in parent_child
        assert (um_uid, profile_uid) in parent_child

        page_edges = {(e.kwargs["parent_uid"], e.kwargs["child_uid"]) for e in edges}
        assert (um_uid, "wp:UserController") in page_edges
        assert (auth_uid, "wp:AuthService") in page_edges
        assert (auth_uid, "wp:TokenService") in page_edges
        assert (profile_uid, "wp:ProfileService") in page_edges
