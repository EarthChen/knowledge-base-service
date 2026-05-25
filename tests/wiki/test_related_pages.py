"""tests/wiki/test_related_pages.py — Sprint 3 tests for cross-page references."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestFindRelatedEntities:
    @pytest.mark.asyncio
    async def test_find_related_outgoing(self):
        """Should return entities connected by outgoing CALLS edges."""
        from store.falkordb_store import FalkorDBStore

        store = FalkorDBStore.__new__(FalkorDBStore)
        mock_graph = MagicMock()

        out_result = MagicMock()
        out_result.result_set = [["target_uid", "CALLS"]]
        in_result = MagicMock()
        in_result.result_set = []
        mock_graph.query.side_effect = [out_result, in_result]
        store._graph = mock_graph

        with patch("store.falkordb_store._graph_executor", None):
            with patch("asyncio.get_running_loop") as mock_loop:
                def run_executor(ex, fn):
                    return fn()

                mock_loop.return_value.run_in_executor = AsyncMock(
                    side_effect=lambda ex, fn: run_executor(ex, fn)
                )
                result = await store.find_related_entities(
                    "source_uid",
                    edge_types=["CALLS"],
                    max_hops=1,
                )

        assert isinstance(result, dict)
        assert len(result["entities"]) >= 1
        uids = [uid for uid, _ in result["entities"]]
        assert "target_uid" in uids
        assert result["query_failed"] is False

    @pytest.mark.asyncio
    async def test_find_related_bidirectional(self):
        """Should find both outgoing and incoming edges."""
        from store.falkordb_store import FalkorDBStore

        store = FalkorDBStore.__new__(FalkorDBStore)
        mock_graph = MagicMock()

        out_result = MagicMock()
        out_result.result_set = [["out_uid", "CALLS"]]
        in_result = MagicMock()
        in_result.result_set = [["in_uid", "IMPORTS"]]
        mock_graph.query.side_effect = [out_result, in_result]
        store._graph = mock_graph

        with patch("store.falkordb_store._graph_executor", None):
            with patch("asyncio.get_running_loop") as mock_loop:
                def run_executor(ex, fn):
                    return fn()

                mock_loop.return_value.run_in_executor = AsyncMock(
                    side_effect=lambda ex, fn: run_executor(ex, fn)
                )
                result = await store.find_related_entities(
                    "target_uid",
                    edge_types=["CALLS", "IMPORTS"],
                    max_hops=1,
                )

        uids = [uid for uid, _ in result["entities"]]
        assert "out_uid" in uids
        assert "in_uid" in uids
        assert result["query_failed"] is False

    @pytest.mark.asyncio
    async def test_find_related_excludes_self(self):
        """Should not include the queried node itself."""
        from store.falkordb_store import FalkorDBStore

        store = FalkorDBStore.__new__(FalkorDBStore)
        mock_graph = MagicMock()

        out_result = MagicMock()
        out_result.result_set = [["self_uid", "CALLS"], ["other_uid", "CALLS"]]
        in_result = MagicMock()
        in_result.result_set = []
        mock_graph.query.side_effect = [out_result, in_result]
        store._graph = mock_graph

        with patch("store.falkordb_store._graph_executor", None):
            with patch("asyncio.get_running_loop") as mock_loop:
                def run_executor(ex, fn):
                    return fn()

                mock_loop.return_value.run_in_executor = AsyncMock(
                    side_effect=lambda ex, fn: run_executor(ex, fn)
                )
                result = await store.find_related_entities(
                    "self_uid",
                    edge_types=["CALLS"],
                )

        uids = [uid for uid, _ in result["entities"]]
        assert "self_uid" not in uids
        assert "other_uid" in uids
        assert result["query_failed"] is False


class TestFindEntitiesByDomain:
    @pytest.mark.asyncio
    async def test_find_entities_by_domain(self):
        """Should return entities with matching business_domain."""
        from store.falkordb_store import FalkorDBStore

        store = FalkorDBStore.__new__(FalkorDBStore)
        mock_graph = MagicMock()
        mock_result = MagicMock()
        mock_result.result_set = [["uid_b"], ["uid_c"]]
        mock_graph.query.return_value = mock_result
        store._graph = mock_graph

        with patch("store.falkordb_store._graph_executor", None):
            with patch("asyncio.get_running_loop") as mock_loop:
                def run_executor(ex, fn):
                    return fn()

                mock_loop.return_value.run_in_executor = AsyncMock(
                    side_effect=lambda ex, fn: run_executor(ex, fn)
                )
                result = await store.find_entities_by_domain(
                    "User Management",
                    exclude_uid="uid_a",
                )

        assert isinstance(result, list)
        assert "uid_b" in result
        assert "uid_c" in result

    @pytest.mark.asyncio
    async def test_find_entities_by_domain_empty(self):
        """Should return empty list for unknown domain."""
        from store.falkordb_store import FalkorDBStore

        store = FalkorDBStore.__new__(FalkorDBStore)
        mock_graph = MagicMock()
        mock_result = MagicMock()
        mock_result.result_set = []
        mock_graph.query.return_value = mock_result
        store._graph = mock_graph

        with patch("store.falkordb_store._graph_executor", None):
            with patch("asyncio.get_running_loop") as mock_loop:
                def run_executor(ex, fn):
                    return fn()

                mock_loop.return_value.run_in_executor = AsyncMock(
                    side_effect=lambda ex, fn: run_executor(ex, fn)
                )
                result = await store.find_entities_by_domain("Unknown")

        assert result == []


class TestFindSiblings:
    @pytest.mark.asyncio
    async def test_find_siblings_under_same_parent(self):
        """Should return sibling entities under the same parent via CONTAINS."""
        from store.falkordb_store import FalkorDBStore

        store = FalkorDBStore.__new__(FalkorDBStore)
        mock_graph = MagicMock()
        mock_result = MagicMock()
        mock_result.result_set = [["sibling_b_uid"], ["sibling_c_uid"]]
        mock_graph.query.return_value = mock_result
        store._graph = mock_graph

        with patch("store.falkordb_store._graph_executor", None):
            with patch("asyncio.get_running_loop") as mock_loop:
                def run_executor(ex, fn):
                    return fn()

                mock_loop.return_value.run_in_executor = AsyncMock(
                    side_effect=lambda ex, fn: run_executor(ex, fn)
                )
                result = await store.find_siblings("child_a_uid")

        assert isinstance(result, list)
        assert "sibling_b_uid" in result
        assert "sibling_c_uid" in result

    @pytest.mark.asyncio
    async def test_find_siblings_leaf_no_siblings(self):
        """Node with no CONTAINS parent should return empty list."""
        from store.falkordb_store import FalkorDBStore

        store = FalkorDBStore.__new__(FalkorDBStore)
        mock_graph = MagicMock()
        mock_result = MagicMock()
        mock_result.result_set = []
        mock_graph.query.return_value = mock_result
        store._graph = mock_graph

        with patch("store.falkordb_store._graph_executor", None):
            with patch("asyncio.get_running_loop") as mock_loop:
                def run_executor(ex, fn):
                    return fn()

                mock_loop.return_value.run_in_executor = AsyncMock(
                    side_effect=lambda ex, fn: run_executor(ex, fn)
                )
                result = await store.find_siblings("orphan_uid")

        assert result == []


class TestRelatedPagesBuilder:
    @pytest.mark.asyncio
    async def test_graph_proximity_highest_weight(self):
        """Graph neighbors (CALLS/IMPORTS) should rank highest."""
        from wiki.related_pages_builder import RelatedPagesBuilder

        mock_store = MagicMock()
        mock_store.find_related_entities = AsyncMock(return_value={
            "entities": [
                ("controller_uid", "CALLS"),
                ("service_uid", "IMPORTS"),
            ],
            "query_failed": False,
        })
        mock_store.find_entities_by_domain = AsyncMock(return_value=["domain_uid"])
        mock_store.find_siblings = AsyncMock(return_value=["sibling_uid"])

        builder = RelatedPagesBuilder(mock_store)
        results = await builder.build(
            entity_uid="test_uid",
            business_domain="User Management",
        )
        assert len(results) >= 1
        assert results[0].relevance_score >= 1.0
        assert results[0].strategy.startswith("graph:")

    @pytest.mark.asyncio
    async def test_related_pages_max_limit(self):
        """Should return at most MAX_RELATED items."""
        from wiki.related_pages_builder import RelatedPagesBuilder

        mock_store = MagicMock()
        mock_store.find_related_entities = AsyncMock(return_value={
            "entities": [(f"uid_{i}", "CALLS") for i in range(15)],
            "query_failed": False,
        })
        mock_store.find_entities_by_domain = AsyncMock(return_value=[
            f"domain_uid_{i}" for i in range(10)
        ])
        mock_store.find_siblings = AsyncMock(return_value=[
            f"sib_uid_{i}" for i in range(5)
        ])

        builder = RelatedPagesBuilder(mock_store)
        results = await builder.build(
            entity_uid="hub_uid",
            business_domain="Core",
        )
        assert len(results) <= 10

    @pytest.mark.asyncio
    async def test_domain_siblings_included(self):
        """Same-domain entities should appear in results."""
        from wiki.related_pages_builder import RelatedPagesBuilder

        mock_store = MagicMock()
        mock_store.find_related_entities = AsyncMock(return_value={"entities": [], "query_failed": False})
        mock_store.find_entities_by_domain = AsyncMock(return_value=["same_domain_uid"])
        mock_store.find_siblings = AsyncMock(return_value=[])

        builder = RelatedPagesBuilder(mock_store)
        results = await builder.build(
            entity_uid="service_uid",
            business_domain="User Management",
        )
        uids = [r.entity_uid for r in results]
        assert "same_domain_uid" in uids

    @pytest.mark.asyncio
    async def test_score_accumulation(self):
        """Entity appearing in multiple strategies should have accumulated score."""
        from wiki.related_pages_builder import RelatedPagesBuilder

        mock_store = MagicMock()
        # Same uid appears in graph AND domain
        mock_store.find_related_entities = AsyncMock(return_value={
            "entities": [("shared_uid", "CALLS")],
            "query_failed": False,
        })
        mock_store.find_entities_by_domain = AsyncMock(return_value=["shared_uid"])
        mock_store.find_siblings = AsyncMock(return_value=["shared_uid"])

        builder = RelatedPagesBuilder(mock_store)
        results = await builder.build(
            entity_uid="source_uid",
            business_domain="Core",
        )
        assert len(results) == 1
        assert results[0].entity_uid == "shared_uid"
        assert results[0].relevance_score == 2.0  # 1.0 + 0.6 + 0.4

    @pytest.mark.asyncio
    async def test_empty_results(self):
        """If no related entities found, return empty list."""
        from wiki.related_pages_builder import RelatedPagesBuilder

        mock_store = MagicMock()
        mock_store.find_related_entities = AsyncMock(return_value={"entities": [], "query_failed": False})
        mock_store.find_entities_by_domain = AsyncMock(return_value=[])
        mock_store.find_siblings = AsyncMock(return_value=[])

        builder = RelatedPagesBuilder(mock_store)
        results = await builder.build(entity_uid="lonely_uid")
        assert results == []

    @pytest.mark.asyncio
    async def test_no_domain_skips_domain_lookup(self):
        """When business_domain is None, domain lookup should be skipped."""
        from wiki.related_pages_builder import RelatedPagesBuilder

        mock_store = MagicMock()
        mock_store.find_related_entities = AsyncMock(return_value={"entities": [], "query_failed": False})
        mock_store.find_entities_by_domain = AsyncMock(return_value=[])
        mock_store.find_siblings = AsyncMock(return_value=[])

        builder = RelatedPagesBuilder(mock_store)
        await builder.build(entity_uid="uid", business_domain=None)
        mock_store.find_entities_by_domain.assert_not_called()


class TestRelatedToEdgePersistence:
    @pytest.mark.asyncio
    async def test_build_and_persist_calls_upsert_edge(self):
        """build_and_persist should call store.upsert_edge for each related entity."""
        from wiki.related_pages_builder import RelatedPagesBuilder

        mock_store = MagicMock()
        mock_store.find_related_entities = AsyncMock(return_value={
            "entities": [
                ("related_uid_1", "CALLS"),
                ("related_uid_2", "IMPORTS"),
            ],
            "query_failed": False,
        })
        mock_store.find_entities_by_domain = AsyncMock(return_value=[])
        mock_store.find_siblings = AsyncMock(return_value=[])
        mock_store.upsert_edge = AsyncMock()

        builder = RelatedPagesBuilder(mock_store)
        results = await builder.build_and_persist(
            entity_uid="source_uid",
            business_domain="Core",
        )

        assert len(results) == 2
        assert mock_store.upsert_edge.call_count == 2
        for call in mock_store.upsert_edge.call_args_list:
            edge = call.args[0] if call.args else call.kwargs.get("edge")
            assert edge.source_uid == "source_uid"
            assert edge.edge_type.value == "RELATED_TO" or str(edge.edge_type) == "RELATED_TO"

    @pytest.mark.asyncio
    async def test_build_and_persist_handles_upsert_failure(self):
        """If upsert_edge fails for one edge, others should still be attempted."""
        from wiki.related_pages_builder import RelatedPagesBuilder

        mock_store = MagicMock()
        mock_store.find_related_entities = AsyncMock(return_value={
            "entities": [("uid_1", "CALLS"), ("uid_2", "CALLS")],
            "query_failed": False,
        })
        mock_store.find_entities_by_domain = AsyncMock(return_value=[])
        mock_store.find_siblings = AsyncMock(return_value=[])
        mock_store.upsert_edge = AsyncMock(side_effect=[Exception("DB error"), None])

        builder = RelatedPagesBuilder(mock_store)
        results = await builder.build_and_persist(entity_uid="source_uid")

        assert len(results) == 2
        assert mock_store.upsert_edge.call_count == 2

    @pytest.mark.asyncio
    async def test_related_to_edge_type_exists(self):
        """RELATED_TO should be a valid EdgeType."""
        from store.schema import EdgeType

        assert hasattr(EdgeType, "RELATED_TO")
        assert EdgeType.RELATED_TO == "RELATED_TO"


class TestApiRelatedPages:
    def test_page_detail_route_references_related_pages(self):
        """Page detail route should include related_pages logic."""
        import importlib
        import inspect

        try:
            mod = importlib.import_module("api.routes.wiki_page_routes")
        except ImportError:
            mod = importlib.import_module("api.routes.wiki_routes")

        source = inspect.getsource(mod)
        assert "related_pages" in source


class TestRelatedPagesIntegration:
    def test_service_uses_related_pages_builder(self):
        """generate_business_wiki source should reference RelatedPagesBuilder."""
        import inspect

        from wiki.business_pipeline_runner import BusinessPipelineRunner

        source = inspect.getsource(BusinessPipelineRunner.run)
        assert "RelatedPagesBuilder" in source
        assert "build_and_persist" in source
