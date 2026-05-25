"""Batch AB — Pipeline Quality P2 fixes (hybrid fetch limits, semantic repo filter)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from query.hybrid_query import HybridQueryService
from query.semantic_query import SemanticQueryService
from store.schema import NodeLabel


@pytest.fixture
def mock_store():
    store = AsyncMock()
    store.keyword_search = AsyncMock(return_value=[])
    store.vector_search = AsyncMock(return_value=[])
    return store


@pytest.fixture
def mock_semantic():
    svc = AsyncMock()
    svc.search_all = AsyncMock(return_value=MagicMock(matches=[]))
    svc.search_with_parent_context = AsyncMock(return_value=MagicMock(matches=[]))
    return svc


@pytest.fixture
def mock_graph():
    svc = AsyncMock()
    svc.find_call_chain = AsyncMock(return_value=MagicMock(data=[]))
    svc.find_class_methods = AsyncMock(return_value=MagicMock(data=[]))
    svc.find_inheritance_tree = AsyncMock(return_value=MagicMock(data=[]))
    svc.find_flows_for_function = AsyncMock(return_value=MagicMock(data=[]))
    svc.find_file_entities = AsyncMock(return_value=MagicMock(data=[]))
    return svc


@pytest.mark.asyncio
async def test_hybrid_branch_fetch_scales_with_limit_not_500(
    mock_store, mock_semantic, mock_graph,
):
    """With limit=10, each search branch should fetch ~30 candidates, not 500."""
    mock_search_store = AsyncMock()
    mock_search_store.fulltext_search = AsyncMock(return_value=[])
    captured: dict[str, int] = {}

    async def capture_semantic(_q: str, k: int, **kwargs: object) -> MagicMock:
        captured["semantic_k"] = k
        return MagicMock(matches=[])

    mock_semantic.search_all = capture_semantic

    async def capture_keyword(*_a, k: int = 10, **_kw: object) -> list:
        captured["keyword_k"] = k
        return []

    mock_store.keyword_search = capture_keyword

    svc = HybridQueryService(
        mock_store,
        mock_semantic,
        mock_graph,
        search_store=mock_search_store,
        enable_bm25=True,
    )
    await svc.search_with_context(
        "retry logic",
        k=500,
        limit=10,
        offset=0,
        use_query_expansion=False,
    )

    assert captured["semantic_k"] <= 30
    assert captured["keyword_k"] <= 30
    bm25_call = mock_search_store.fulltext_search.await_args
    assert bm25_call is not None
    assert bm25_call.kwargs["limit"] <= 30


@pytest.mark.asyncio
async def test_multi_repo_hybrid_fetch_limit_scales_with_pagination() -> None:
    """Multi-repo search should not always fetch 500 candidates per repository."""
    hybrid = HybridQueryService(
        store=MagicMock(),
        semantic_svc=MagicMock(),
        graph_svc=MagicMock(),
    )
    hybrid.search_with_context = AsyncMock(
        return_value={
            "results": [],
            "semantic_matches": [],
            "total": 0,
            "offset": 0,
            "limit": 30,
            "graph_context": [],
            "query_text": "q",
            "confidence": 0.0,
            "no_results_reason": "",
        },
    )

    await hybrid.search_multi_repo(
        "q",
        ["repo-a", "repo-b"],
        limit=10,
        offset=0,
    )

    assert hybrid.search_with_context.await_count == 2
    for call in hybrid.search_with_context.await_args_list:
        assert call.kwargs["limit"] <= 30


def _make_entity_node(name: str, repository: str) -> MagicMock:
    node = MagicMock()
    node.properties = {
        "name": name,
        "repository": repository,
        "file": f"{repository}/{name}.py",
        "start_line": 1,
        "end_line": 10,
        "uid": f"Function:{repository}:{name}:1",
    }
    return node


@pytest.mark.asyncio
async def test_semantic_search_filters_results_by_repository(mock_store) -> None:
    """Search with repository='repo-a' should return only repo-a matches."""
    emb = AsyncMock()
    emb.generate_for_query = AsyncMock(return_value=[[0.1] * 8])

    mock_store.vector_search = AsyncMock(
        return_value=[
            (_make_entity_node("SvcA", "repo-a"), 0.95),
            (_make_entity_node("SvcB", "repo-b"), 0.90),
        ],
    )

    svc = SemanticQueryService(mock_store, emb, include_raw_docs_in_results=False)
    result = await svc.search_chunks("service", k=10, repository="repo-a")

    assert mock_store.vector_search.await_args.kwargs.get("repository") == "repo-a"
    assert len(result.matches) == 1
    assert result.matches[0]["repository"] == "repo-a"
    assert result.matches[0]["name"] == "SvcA"


@pytest.mark.asyncio
async def test_semantic_search_all_passes_repository_to_vector_search(mock_store) -> None:
    emb = AsyncMock()
    emb.generate_for_query = AsyncMock(return_value=[[0.1] * 8])
    mock_store.vector_search = AsyncMock(return_value=[])

    svc = SemanticQueryService(mock_store, emb, include_raw_docs_in_results=False)
    await svc.search_all("query", k=5, repository="repo-a")

    for call in mock_store.vector_search.await_args_list:
        assert call.kwargs.get("repository") == "repo-a"
        assert call.args[0] in (
            NodeLabel.FUNCTION,
            NodeLabel.CLASS,
            NodeLabel.DOCUMENT,
            NodeLabel.BUSINESS_FLOW,
            NodeLabel.BUSINESS_CONCEPT,
            NodeLabel.MODULE,
        )
