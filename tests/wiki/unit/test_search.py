"""Unit tests for wiki.search.WikiSearchService — hybrid RRF fusion pipeline."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from wiki.search import WikiSearchService, _vector_hit_to_page


class TestRRFFusion:
    """RRF scoring and top-rank bonus."""

    def test_rrf_fusion_scoring(self) -> None:
        """Σ(weight × 1/(k+rank+1)) with k=60."""
        k = 60
        lists = [
            [("a", 1.0), ("b", 1.0)],
            [("b", 1.0)],
        ]
        weights = [2.0, 1.0]
        out = WikiSearchService.rrf_fusion(lists, weights, k=k)
        scores = {doc: s for doc, s in out}

        expected_a = 2.0 / (k + 0 + 1) + 0.05
        expected_b = 2.0 / (k + 1 + 1) + 1.0 / (k + 0 + 1) + 0.05
        mx = max(expected_a, expected_b)

        assert scores["a"] == pytest.approx(expected_a / mx)
        assert scores["b"] == pytest.approx(expected_b / mx)

    def test_rrf_top_rank_bonus(self) -> None:
        """#1 (rank 0) receives +0.05 bonus."""
        k = 60
        lists = [[("only", 1.0)]]
        weights = [1.0]
        out = WikiSearchService.rrf_fusion(lists, weights, k=k)
        assert len(out) == 1
        doc, score = out[0]
        assert doc == "only"
        assert score == pytest.approx(1.0)


class TestGraphExpansion:
    """Graph-aware entity extraction and neighbor expansion."""

    @pytest.mark.asyncio
    async def test_graph_query_expansion(self) -> None:
        graph = AsyncMock()
        graph.execute_query = AsyncMock(
            return_value=MagicMock(
                data=[
                    {"neighbor": "AuthProvider"},
                    {"neighbor": "TokenService"},
                ]
            )
        )
        vector = AsyncMock()
        fts = AsyncMock()
        svc = WikiSearchService(graph, vector, fts)

        q = "How does UserService login work?"
        expanded = await svc.expand_query_with_graph(q)

        assert expanded[0] == q
        assert len(expanded) == 2
        assert "UserService" in expanded[1] or "AuthProvider" in expanded[1]
        assert "AuthProvider" in expanded[1] and "TokenService" in expanded[1]

        neighbor_cy = graph.execute_query.call_args_list[0][0][0]
        assert "CALLS" in neighbor_cy and "INHERITS" in neighbor_cy
        assert graph.execute_query.call_args_list[0][0][1].get("name") == "UserService"

    @pytest.mark.asyncio
    async def test_graph_expansion_no_entity(self) -> None:
        graph = AsyncMock()
        vector = AsyncMock()
        fts = AsyncMock()
        svc = WikiSearchService(graph, vector, fts)

        q = "how does login work in general"
        expanded = await svc.expand_query_with_graph(q)
        assert expanded == [q]
        graph.execute_query.assert_not_called()


class TestFTSIndex:
    """Full-text index lifecycle."""

    @pytest.mark.asyncio
    async def test_fts_index_build(self) -> None:
        graph = AsyncMock()
        vector = AsyncMock()
        fts = AsyncMock()
        fts.execute_query = AsyncMock(
            side_effect=[
                MagicMock(data=[]),
                MagicMock(
                    data=[
                        {
                            "node": MagicMock(
                                properties={
                                    "path": "classes/UserService.md",
                                    "title": "UserService",
                                    "content": "authentication login flow",
                                }
                            ),
                            "score": 0.9,
                        }
                    ]
                ),
            ]
        )
        svc = WikiSearchService(graph, vector, fts)

        await svc.ensure_fulltext_index()
        first_cypher = fts.execute_query.call_args_list[0][0][0]
        assert "createNodeIndex" in first_cypher
        assert "WikiPage" in first_cypher

        # Searchable via keyword path
        fts.execute_query.side_effect = None
        fts.execute_query = AsyncMock(
            return_value=MagicMock(
                data=[
                    {
                        "node": MagicMock(
                            properties={
                                "path": "classes/UserService.md",
                                "title": "UserService",
                                "content": "auth",
                            }
                        ),
                        "score": 0.88,
                    }
                ]
            )
        )
        graph.execute_query = AsyncMock(return_value=MagicMock(data=[]))
        vector.search_all = AsyncMock(return_value=[])

        resp = await svc.search("repo1", "authentication", mode="keyword", limit=5)
        assert len(resp.results) >= 1
        assert any("queryNodes" in str(c[0][0]) for c in fts.execute_query.call_args_list)


class TestHybridParallelAndWeights:
    """Concurrency and per-path weights in fusion."""

    @pytest.mark.asyncio
    async def test_3path_parallel_execution(self) -> None:
        entered: list[tuple[str, float]] = []

        async def mark_graph(*_a: object, **_k: object) -> MagicMock:
            entered.append(("g", time.perf_counter()))
            await asyncio.sleep(0.06)
            return MagicMock(data=[])

        async def mark_vector(*_a: object, **_k: object) -> list[dict[str, object]]:
            entered.append(("v", time.perf_counter()))
            await asyncio.sleep(0.06)
            return []

        async def mark_fts(*_a: object, **_k: object) -> MagicMock:
            entered.append(("f", time.perf_counter()))
            await asyncio.sleep(0.06)
            return MagicMock(data=[])

        graph = AsyncMock()
        graph.execute_query = AsyncMock(side_effect=mark_graph)

        vector = AsyncMock()
        vector.search_all = AsyncMock(side_effect=mark_vector)

        fts = AsyncMock()
        fts.execute_query = AsyncMock(side_effect=mark_fts)

        svc = WikiSearchService(graph, vector, fts)

        # No PascalCase entities → expansion does not call graph; hybrid runs 3 paths concurrently.
        await svc.search("repo", "parallel hybrid query test", mode="hybrid", limit=10)

        times = {n: t for n, t in entered}
        span = max(times.values()) - min(times.values())
        assert span < 0.05, f"paths should start together, got span={span}"

    def test_graph_path_weight_2x(self) -> None:
        """Same rank in graph vs vector: graph contributes 2× the vector term."""
        k = 60
        lists = [
            [("x", 1.0)],
            [("x", 1.0)],
        ]
        weights = [2.0, 1.0]
        out = WikiSearchService.rrf_fusion(lists, weights, k=k)
        score_x = next(s for d, s in out if d == "x")
        g_term = 2.0 / (k + 0 + 1)
        v_term = 1.0 / (k + 0 + 1)
        assert score_x == pytest.approx(1.0)
        assert g_term == pytest.approx(2.0 * v_term)

    def test_fts_path_weight_1_5x(self) -> None:
        """Same rank in FTS vs vector: FTS contributes 1.5× the vector term."""
        k = 60
        lists = [
            [("y", 1.0)],
            [("y", 1.0)],
        ]
        weights = [1.5, 1.0]
        out = WikiSearchService.rrf_fusion(lists, weights, k=k)
        score_y = next(s for d, s in out if d == "y")
        fts_term = 1.5 / (k + 0 + 1)
        v_term = 1.0 / (k + 0 + 1)
        assert score_y == pytest.approx(1.0)
        assert fts_term == pytest.approx(1.5 * v_term)


class TestSearchBehavior:
    """End-to-end search filters and empty results."""

    @pytest.mark.asyncio
    async def test_search_empty_results(self) -> None:
        graph = AsyncMock(return_value=MagicMock(data=[]))
        graph.execute_query = AsyncMock(return_value=MagicMock(data=[]))
        vector = AsyncMock()
        vector.search_all = AsyncMock(return_value=[])
        fts = AsyncMock()
        fts.execute_query = AsyncMock(return_value=MagicMock(data=[]))

        svc = WikiSearchService(graph, vector, fts)
        resp = await svc.search("repo", "nosuchtermxyz123", mode="hybrid", limit=10)
        assert resp.results == []
        assert resp.total == 0

    @pytest.mark.asyncio
    async def test_search_respects_limit(self) -> None:
        graph = AsyncMock()
        graph.execute_query = AsyncMock(
            return_value=MagicMock(
                data=[{"page_path": f"p{i}.md", "title": f"T{i}", "snippet": ""} for i in range(10)]
            )
        )
        vector = AsyncMock()
        vector.search_all = AsyncMock(
            return_value=[{"page_path": f"v{i}.md", "title": f"V{i}", "score": 1.0 - i * 0.01} for i in range(10)]
        )
        fts = AsyncMock()
        fts.execute_query = AsyncMock(
            return_value=MagicMock(
                data=[
                    {
                        "node": MagicMock(properties={"path": f"f{i}.md", "title": f"F{i}", "content": "x"}),
                        "score": 1.0,
                    }
                    for i in range(10)
                ]
            )
        )

        svc = WikiSearchService(graph, vector, fts)
        resp = await svc.search("repo", "q", mode="hybrid", limit=5)
        assert len(resp.results) <= 5

    @pytest.mark.asyncio
    async def test_search_min_score_filter(self) -> None:
        graph = AsyncMock()
        graph.execute_query = AsyncMock(return_value=MagicMock(data=[]))
        vector = AsyncMock()
        vector.search_all = AsyncMock(
            return_value=[
                {"page_path": "low.md", "title": "L", "score": 0.1},
                {"page_path": "high.md", "title": "H", "score": 0.99},
            ]
        )
        fts = AsyncMock()
        fts.execute_query = AsyncMock(return_value=MagicMock(data=[]))

        svc = WikiSearchService(graph, vector, fts)
        resp = await svc.search("repo", "x", mode="semantic", limit=10, min_score=0.5)
        paths = {r.page_path for r in resp.results}
        assert "low.md" not in paths
        assert "high.md" in paths


@pytest.mark.asyncio
async def test_modes_single_path_only() -> None:
    """graph | semantic | keyword modes invoke only the respective port."""
    graph = AsyncMock()
    graph.execute_query = AsyncMock(return_value=MagicMock(data=[]))
    vector = AsyncMock()
    vector.search_all = AsyncMock(return_value=[])
    fts = AsyncMock()
    fts.execute_query = AsyncMock(return_value=MagicMock(data=[]))

    svc = WikiSearchService(graph, vector, fts)

    await svc.search("r", "UserService", mode="graph", limit=5)
    assert graph.execute_query.await_count >= 1
    vector.search_all.assert_not_called()
    fts.execute_query.assert_not_called()

    graph.reset_mock()
    vector.reset_mock()
    fts.reset_mock()

    await svc.search("r", "UserService", mode="semantic", limit=5)
    vector.search_all.assert_awaited()
    graph.execute_query.assert_not_called()
    fts.execute_query.assert_not_called()

    graph.reset_mock()
    vector.reset_mock()
    fts.reset_mock()

    await svc.search("r", "auth login", mode="keyword", limit=5)
    fts.execute_query.assert_awaited()
    graph.execute_query.assert_not_called()
    vector.search_all.assert_not_called()


class TestSearchErrorPathsAndScope:
    """Graph/vector/FTS failures, scope filter, and vector hit normalization."""

    @pytest.mark.asyncio
    async def test_expand_query_graph_failure_falls_back_to_original(self) -> None:
        graph = AsyncMock()
        graph.execute_query = AsyncMock(side_effect=RuntimeError("graph down"))
        svc = WikiSearchService(graph, AsyncMock(), AsyncMock())

        out = await svc.expand_query_with_graph("How does UserService work?")
        assert out == ["How does UserService work?"]

    @pytest.mark.asyncio
    async def test_hybrid_graph_path_error_still_fuses_other_paths(self) -> None:
        graph = AsyncMock()
        graph.execute_query = AsyncMock(side_effect=RuntimeError("neo4j"))
        vector = AsyncMock()
        vector.search_all = AsyncMock(
            return_value=[{"page_path": "classes/Only.md", "title": "Only", "score": 0.9}]
        )
        fts = AsyncMock()
        fts.execute_query = AsyncMock(return_value=MagicMock(data=[]))

        svc = WikiSearchService(graph, vector, fts)
        resp = await svc.search("repo", "UserService", mode="hybrid", limit=5)
        assert any(r.page_path == "classes/Only.md" for r in resp.results)

    @pytest.mark.asyncio
    async def test_semantic_vector_path_error_returns_empty(self) -> None:
        graph = AsyncMock()
        vector = AsyncMock()
        vector.search_all = AsyncMock(side_effect=RuntimeError("vector"))
        fts = AsyncMock()

        svc = WikiSearchService(graph, vector, fts)
        resp = await svc.search("repo", "query", mode="semantic", limit=10)
        assert resp.results == []

    @pytest.mark.asyncio
    async def test_keyword_fts_path_error_returns_empty(self) -> None:
        graph = AsyncMock()
        vector = AsyncMock()
        fts = AsyncMock()
        fts.execute_query = AsyncMock(side_effect=RuntimeError("fts"))

        svc = WikiSearchService(graph, vector, fts)
        resp = await svc.search("repo", "anything", mode="keyword", limit=10)
        assert resp.results == []

    @pytest.mark.asyncio
    async def test_scope_filters_page_paths(self) -> None:
        graph = AsyncMock()
        graph.execute_query = AsyncMock(return_value=MagicMock(data=[]))
        vector = AsyncMock()
        vector.search_all = AsyncMock(
            return_value=[
                {"page_path": "modules/a/page.md", "title": "In", "score": 0.9},
                {"page_path": "other/x.md", "title": "Out", "score": 0.95},
            ]
        )
        fts = AsyncMock()
        fts.execute_query = AsyncMock(return_value=MagicMock(data=[]))

        svc = WikiSearchService(graph, vector, fts)
        resp = await svc.search(
            "repo",
            "UserService",
            mode="hybrid",
            limit=10,
            scope="modules/a",
        )
        paths = {r.page_path for r in resp.results}
        assert "modules/a/page.md" in paths
        assert "other/x.md" not in paths


def test_vector_hit_to_page_fqn_and_name_fallbacks() -> None:
    assert _vector_hit_to_page({"fqn": "com.example.api.UserService#method"}) == "classes/UserService.md"
    assert _vector_hit_to_page({"name": "Blob"}) == "entities/Blob.md"
    assert _vector_hit_to_page({}) is None
