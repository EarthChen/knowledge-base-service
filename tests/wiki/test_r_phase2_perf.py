"""R-Phase 2 backend performance: batch persistence, global search limits, business partial errors."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from httpx import ASGITransport

import core.auth as auth_module
from tests.wiki_config_inject import inject_wiki_embedding, wiki_service_injection
from api.routes.wiki_routes import (
    _GLOBAL_SEARCH_CONCURRENCY,
    get_wiki_search_dep,
    get_wiki_service_dep,
    wiki_router,
)
from fastapi import FastAPI
from store.falkordb_store import FalkorDBStore, QueryResultWrapper
from store.schema import GraphNode, NodeLabel
from store.wiki_store import WikiStore
from wiki.models import PageType, WikiPage, WikiPageMetadata, WikiStructureNode
from wiki.service import WikiService
from wiki.search import SearchResponse


@pytest.fixture(autouse=True)
def _no_auth_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_module, "_token_registry", {})


@pytest.mark.asyncio
async def test_persist_source_entity_single_unwind_query(monkeypatch: pytest.MonkeyPatch) -> None:
    """_persist_pages_to_graph should MERGE SOURCE_ENTITY edges in one UNWIND batch, not N queries."""
    store = MagicMock()
    se_calls: list[tuple[str, dict]] = []

    async def capture_se(cypher: str, params: dict | None = None) -> QueryResultWrapper:
        p = params or {}
        if "SOURCE_ENTITY" in cypher:
            se_calls.append((cypher, p))
        return QueryResultWrapper(data=[], raw=[])

    store.persist_wiki_pages = AsyncMock()
    store.execute_query = AsyncMock(side_effect=capture_se)
    store.batch_set_node_embeddings = AsyncMock()

    async def fake_emb(_items: list) -> list[list[float]]:
        return [[0.1, 0.2] for _ in _items]

    emb_gen = MagicMock()
    emb_gen.generate_for_docs = AsyncMock(side_effect=fake_emb)
    monkeypatch.setattr("wiki.persistence.EmbeddingGenerator.shared", lambda **_k: emb_gen)
    monkeypatch.setattr("wiki.persistence.gather_confidence_inputs", AsyncMock())
    monkeypatch.setattr("wiki.persistence.set_wiki_page_confidence_scores", AsyncMock())

    graph = AsyncMock()
    svc = WikiService(
        graph=graph, llm=None, repository_exists=AsyncMock(return_value=True), store=store,
        **wiki_service_injection(),
    )

    p1 = WikiPage(
        path="a.md",
        title="A",
        page_type=PageType.MODULE_OVERVIEW,
        content="x",
        diagrams=[],
        source_locations=[],
        metadata=WikiPageMetadata(node_count=0, edge_count=0),
    )
    p1._source_entity_uid = "E:1"  # type: ignore[attr-defined]
    p2 = WikiPage(
        path="b.md",
        title="B",
        page_type=PageType.CLASS_DETAIL,
        content="y",
        diagrams=[],
        source_locations=[],
        metadata=WikiPageMetadata(node_count=0, edge_count=0),
    )
    p2._source_entity_uid = "E:2"  # type: ignore[attr-defined]

    await svc._persist_pages_to_graph("myrepo", [p1, p2])

    assert len(se_calls) == 1
    cy, prm = se_calls[0]
    assert "UNWIND" in cy and "SOURCE_ENTITY" in cy
    assert "pairs" in prm
    pairs = prm["pairs"]
    assert len(pairs) == 2
    uids = {(x["wiki_uid"], x["entity_uid"]) for x in pairs}
    assert uids == {
        ("WikiPage:myrepo:a.md", "E:1"),
        ("WikiPage:myrepo:b.md", "E:2"),
    }
    store.batch_set_node_embeddings.assert_awaited_once()


@pytest.mark.asyncio
async def test_falkordb_batch_set_node_embeddings_limited_concurrency() -> None:
    """batch_set_node_embeddings should not exceed ``concurrency`` parallel set_node_embedding calls."""
    store = FalkorDBStore.__new__(FalkorDBStore)
    concurrent = 0
    max_c = 0
    lock = asyncio.Lock()
    call_order: list[int] = []
    n_items = 12

    async def slow_set(_uid: str, _label: NodeLabel, _emb: list[float]) -> None:
        nonlocal concurrent, max_c
        async with lock:
            concurrent += 1
            max_c = max(max_c, concurrent)
        await asyncio.sleep(0.02)
        async with lock:
            call_order.append(concurrent)
            concurrent -= 1

    store.set_node_embedding = AsyncMock(side_effect=slow_set)
    items: list[tuple[str, NodeLabel, list[float]]] = [
        (f"uid{i}", NodeLabel.WIKI_PAGE, [0.0, float(i)]) for i in range(n_items)
    ]
    await FalkorDBStore.batch_set_node_embeddings(store, items, concurrency=3)
    assert max_c <= 3
    assert store.set_node_embedding.await_count == n_items


@pytest.mark.asyncio
async def test_wiki_list_pages_paginated_count_and_skip_limit() -> None:
    store = MagicMock()
    call_order: list[str] = []

    async def eq(cypher: str, params: dict | None = None) -> QueryResultWrapper:
        p = params or {}
        if "count(" in cypher and "total" in cypher:
            call_order.append("count")
            return QueryResultWrapper(data=[{"total": 100}], raw=[])
        if "SKIP" in cypher:
            call_order.append("list")
            assert p.get("skip") == 5
            assert p.get("limit") == 2
            return QueryResultWrapper(
                data=[
                    {"path": "p0.md", "title": "P0", "page_type": "module_overview"},
                    {"path": "p1.md", "title": "P1", "page_type": "class_detail"},
                ],
                raw=[],
            )
        return QueryResultWrapper(data=[], raw=[])

    store.execute_query = AsyncMock(side_effect=eq)
    w = WikiStore(store)
    r, total = await w.list_wiki_pages_paginated("r1", skip=5, limit=2)
    assert total == 100
    assert call_order == ["count", "list"]
    assert len(r.data) == 2


def _make_wiki_routes_app(*, app_state: dict) -> FastAPI:
    from api.routes.wiki_routes import WikiTaskRegistry

    app = FastAPI()
    for k, v in app_state.items():
        setattr(app.state, k, v)
    if not hasattr(app.state, "wiki_store"):
        app.state.wiki_store = MagicMock()
    if not hasattr(app.state, "wiki_tasks"):
        app.state.wiki_tasks = WikiTaskRegistry()

    async def no_wiki_svc() -> MagicMock:
        return MagicMock()

    app.include_router(wiki_router)
    app.dependency_overrides[get_wiki_service_dep] = no_wiki_svc
    return app


@pytest.mark.asyncio
async def test_wiki_search_global_caps_repositories() -> None:
    repos = [f"repo{i}" for i in range(60)]
    reg = MagicMock()
    kb = MagicMock()
    kb.store = MagicMock()
    queries = MagicMock()
    rows = [{"repository": n} for n in repos]
    queries.list_repositories = AsyncMock(return_value=rows)
    reg.get_service = AsyncMock(return_value=kb)
    search_calls: list[str] = []

    async def search_side_effect(*, repository: str, **_: object) -> SearchResponse:
        search_calls.append(repository)
        return SearchResponse(
            results=[],
            query_expansion={},
            total=0,
        )

    mock_search = MagicMock()
    mock_search.search = AsyncMock(side_effect=search_side_effect)
    with patch("api.routes.wiki_routes.GraphQueryRepository", return_value=queries):
        app = _make_wiki_routes_app(
            app_state={
                "registry": reg,
                "wiki_search_service": mock_search,
            },
        )
        app.dependency_overrides[get_wiki_search_dep] = lambda: mock_search

        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post(
                "/api/v1/wiki/search/global",
                json={"query": "hello", "limit": 10},
            )
        assert r.status_code == 200
        assert len(search_calls) == 50
        data = r.json()
        assert len(data.get("repositories_searched", [])) == 50


@pytest.mark.asyncio
async def test_wiki_search_global_semaphore_limited_concurrency() -> None:
    """Global search should not exceed ``_GLOBAL_SEARCH_CONCURRENCY`` parallel per-repo searches."""
    n_repos = 25
    repos = [f"repo{i}" for i in range(n_repos)]
    reg = MagicMock()
    kb = MagicMock()
    kb.store = MagicMock()
    queries = MagicMock()
    rows = [{"repository": n} for n in repos]
    queries.list_repositories = AsyncMock(return_value=rows)
    reg.get_service = AsyncMock(return_value=kb)

    concurrent = 0
    max_c = 0
    lock = asyncio.Lock()

    async def search_side_effect(*, repository: str, **_: object) -> SearchResponse:
        nonlocal concurrent, max_c
        async with lock:
            concurrent += 1
            max_c = max(max_c, concurrent)
        await asyncio.sleep(0.02)
        async with lock:
            concurrent -= 1
        return SearchResponse(
            results=[],
            query_expansion={},
            total=0,
        )

    mock_search = MagicMock()
    mock_search.search = AsyncMock(side_effect=search_side_effect)
    with patch("api.routes.wiki_routes.GraphQueryRepository", return_value=queries):
        app = _make_wiki_routes_app(
            app_state={
                "registry": reg,
                "wiki_search_service": mock_search,
            },
        )
        app.dependency_overrides[get_wiki_search_dep] = lambda: mock_search

        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post(
                "/api/v1/wiki/search/global",
                json={"query": "hello", "limit": 10},
            )
    assert r.status_code == 200
    assert max_c <= _GLOBAL_SEARCH_CONCURRENCY
    assert mock_search.search.await_count == n_repos


@pytest.mark.asyncio
async def test_persist_source_entity_skips_unwind_when_no_entity_uid(monkeypatch: pytest.MonkeyPatch) -> None:
    """When no page has entity_uid, persist_wiki_pages runs but UNWIND SOURCE_ENTITY is not called."""
    store = MagicMock()
    se_calls: list[tuple[str, dict]] = []

    async def capture_se(cypher: str, params: dict | None = None) -> QueryResultWrapper:
        p = params or {}
        if "SOURCE_ENTITY" in cypher:
            se_calls.append((cypher, p))
        return QueryResultWrapper(data=[], raw=[])

    store.persist_wiki_pages = AsyncMock()
    store.execute_query = AsyncMock(side_effect=capture_se)
    store.batch_set_node_embeddings = AsyncMock()

    async def fake_emb(_items: list) -> list[list[float]]:
        return [[0.1, 0.2] for _ in _items]

    emb_gen = MagicMock()
    emb_gen.generate_for_docs = AsyncMock(side_effect=fake_emb)
    monkeypatch.setattr("wiki.persistence.EmbeddingGenerator.shared", lambda **_k: emb_gen)
    monkeypatch.setattr("wiki.persistence.gather_confidence_inputs", AsyncMock())
    monkeypatch.setattr("wiki.persistence.set_wiki_page_confidence_scores", AsyncMock())

    graph = AsyncMock()
    svc = WikiService(
        graph=graph, llm=None, repository_exists=AsyncMock(return_value=True), store=store,
        **wiki_service_injection(),
    )

    p1 = WikiPage(
        path="a.md",
        title="A",
        page_type=PageType.MODULE_OVERVIEW,
        content="x",
        diagrams=[],
        source_locations=[],
        metadata=WikiPageMetadata(node_count=0, edge_count=0),
    )
    p2 = WikiPage(
        path="b.md",
        title="B",
        page_type=PageType.CLASS_DETAIL,
        content="y",
        diagrams=[],
        source_locations=[],
        metadata=WikiPageMetadata(node_count=0, edge_count=0),
    )

    await svc._persist_pages_to_graph("myrepo", [p1, p2])

    store.persist_wiki_pages.assert_awaited_once()
    assert se_calls == []
    store.execute_query.assert_not_awaited()
    store.batch_set_node_embeddings.assert_awaited_once()


@pytest.mark.asyncio
async def test_generate_business_wiki_partial_errors_on_repo_failure() -> None:
    """Per-repo generate failures are surfaced as partial_errors in the result dict."""
    graph = AsyncMock()
    graph.find_top_level_modules = AsyncMock(return_value=[])
    graph.find_children = AsyncMock(return_value=[])
    graph.find_edges = AsyncMock(return_value=[])
    graph.find_node_by_fqn = AsyncMock(return_value=None)
    graph.find_node_by_path = AsyncMock(return_value=None)

    mod = GraphNode(
        uid="Module:r1:mod",
        label=NodeLabel.MODULE,
        properties={"name": "mod", "path": "src/mod"},
    )

    async def list_mods(repo: str) -> list[GraphNode]:
        if repo == "r-ok":
            return [mod]
        return [mod]

    graph.list_repository_modules = AsyncMock(side_effect=list_mods)

    mock_wiki_store = AsyncMock()
    mock_wiki_store.list_indexed_repositories = AsyncMock(
        return_value=[
            {"repository": "r-ok", "module_count": 1},
            {"repository": "r-fail", "module_count": 1},
        ],
    )
    mock_wiki_store.upsert_wiki_space = AsyncMock()
    mock_wiki_store.upsert_wiki_section = AsyncMock()
    mock_wiki_store.add_has_child_edge = AsyncMock()
    mock_wiki_store.find_source_entity_mappings = AsyncMock(return_value=[])
    mock_wiki_store.find_code_entity_relationships = AsyncMock(return_value=[])
    mock_wiki_store.get_repo_wiki_freshness = AsyncMock(return_value={})
    mock_wiki_store.get_wiki_pages_for_business = AsyncMock(return_value=[])

    overview_page = WikiPage(
        path="overview.md",
        title="O",
        page_type=PageType.REPO_OVERVIEW,
        content="x",
        diagrams=[],
        source_locations=[],
        metadata=WikiPageMetadata(node_count=0, edge_count=0),
    )

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

    _, emb = inject_wiki_embedding()
    svc = WikiService(
        graph=graph,
        llm=None,
        repository_exists=AsyncMock(return_value=True),
        wiki_store=mock_wiki_store,
        wiki_config=mock_wiki_cfg,
        embedding_config=emb,
    )

    from wiki.pipeline_orchestrator import PipelineResult

    stub_result = PipelineResult(
        domain_mapping={"__infrastructure__": [("r-ok", "mod"), ("r-fail", "mod")]},
        domain_tree=None,
        pages=[],
        resolved_links={},
        entity_roles={},
    )

    with (
        patch("wiki.pipeline_orchestrator.run_langgraph_pipeline", new_callable=AsyncMock, return_value=stub_result),
        patch("wiki.reference_generator.WikiReferenceGenerator") as RefGen,
    ):
        RefGen.return_value.generate = AsyncMock(return_value=0)

        async def gen_one(
            repository: str,
            *_a: object,
            **_k: object,
        ) -> dict[str, object]:
            if repository == "r-fail":
                raise RuntimeError("index failed")
            return {
                "pages": [],
                "structure": {"repository": repository, "root": {}, "total_pages": 0},
                "stats": {"total_pages": 0, "generation_time_ms": 0},
                "degraded": False,
            }

        svc.generate = AsyncMock(side_effect=gen_one)
        result = await svc.generate_business_wiki("biz-partial", language="en")

    assert "partial_errors" in result
    assert any(
        e.get("repository") == "r-fail" and "index failed" in e.get("error", "")
        for e in result["partial_errors"]
    )
