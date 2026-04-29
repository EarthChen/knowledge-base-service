"""Cross-repo enricher: shared-library INHERITS / IMPLEMENTS resolution."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from indexer.cross_repo_enricher import CrossRepoEnricher
from store.falkordb_store import QueryResultWrapper


class TestCrossRepoSymbolResolution:
    @pytest.mark.asyncio
    async def test_cross_repo_inherits_resolved(self) -> None:
        """BaseService in common-api links to UserService in service-a via INHERITS."""
        mock_idx = MagicMock()
        mock_idx.cross_repo_delete_symbol_edges = AsyncMock()
        mock_idx.cross_repo_merge_inherits_edge = AsyncMock()
        mock_idx.cross_repo_merge_implements_edge = AsyncMock()

        mock_idx.cross_repo_symbol_candidates = AsyncMock(
            return_value=QueryResultWrapper(
                [
                    {
                        "uid": "cls:UserService",
                        "repository": "service-a",
                        "base_classes": ["BaseService"],
                        "interfaces": [],
                        "name": "UserService",
                    }
                ]
            )
        )
        mock_idx.cross_repo_class_inherit_parents = AsyncMock(
            return_value=QueryResultWrapper([])
        )
        mock_idx.cross_repo_class_implements_targets = AsyncMock(
            return_value=QueryResultWrapper([])
        )
        mock_idx.cross_repo_find_class_by_name = AsyncMock(
            side_effect=[
                {
                    "uid": "cls:BaseService",
                    "repository": "common-api",
                    "name": "BaseService",
                    "fqn": "com.shared.BaseService",
                },
            ]
        )

        enricher = CrossRepoEnricher(MagicMock(), indexer_store=mock_idx)
        count = await enricher._enrich_cross_repo_symbols()

        assert count == 1
        mock_idx.cross_repo_merge_inherits_edge.assert_awaited_once()
        args = mock_idx.cross_repo_merge_inherits_edge.await_args.args
        assert args[0] == "cls:UserService"
        assert args[1] == "cls:BaseService"
        assert args[2] == "service-a"
        assert args[3] == "common-api"
        mock_idx.cross_repo_merge_implements_edge.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skips_java_lang_object(self) -> None:
        mock_idx = MagicMock()
        mock_idx.cross_repo_delete_symbol_edges = AsyncMock()
        mock_idx.cross_repo_merge_inherits_edge = AsyncMock()
        mock_idx.cross_repo_symbol_candidates = AsyncMock(
            return_value=QueryResultWrapper(
                [
                    {
                        "uid": "cls:X",
                        "repository": "service-a",
                        "base_classes": ["java.lang.Object"],
                        "interfaces": [],
                        "name": "X",
                    }
                ]
            )
        )
        mock_idx.cross_repo_class_inherit_parents = AsyncMock(
            return_value=QueryResultWrapper([])
        )
        mock_idx.cross_repo_class_implements_targets = AsyncMock(
            return_value=QueryResultWrapper([])
        )
        mock_idx.cross_repo_find_class_by_name = AsyncMock()

        enricher = CrossRepoEnricher(MagicMock(), indexer_store=mock_idx)
        count = await enricher._enrich_cross_repo_symbols()

        assert count == 0
        mock_idx.cross_repo_find_class_by_name.assert_not_awaited()
        mock_idx.cross_repo_merge_inherits_edge.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skips_when_inherit_already_linked(self) -> None:
        mock_idx = MagicMock()
        mock_idx.cross_repo_delete_symbol_edges = AsyncMock()
        mock_idx.cross_repo_merge_inherits_edge = AsyncMock()
        mock_idx.cross_repo_symbol_candidates = AsyncMock(
            return_value=QueryResultWrapper(
                [
                    {
                        "uid": "cls:Child",
                        "repository": "service-a",
                        "base_classes": ["BaseService"],
                        "interfaces": [],
                        "name": "Child",
                    }
                ]
            )
        )
        mock_idx.cross_repo_class_inherit_parents = AsyncMock(
            return_value=QueryResultWrapper(
                [{"name": "BaseService", "fqn": "com.local.BaseService"}]
            )
        )
        mock_idx.cross_repo_class_implements_targets = AsyncMock(
            return_value=QueryResultWrapper([])
        )
        mock_idx.cross_repo_find_class_by_name = AsyncMock()

        enricher = CrossRepoEnricher(MagicMock(), indexer_store=mock_idx)
        count = await enricher._enrich_cross_repo_symbols()

        assert count == 0
        mock_idx.cross_repo_find_class_by_name.assert_not_awaited()


@pytest.mark.asyncio
async def test_enrich_all_includes_symbol_stats() -> None:
    """enrich_all returns cross_repo_symbol_edges count."""
    mock_idx = MagicMock()
    mock_idx.cross_repo_delete_edges = AsyncMock()
    mock_idx.cross_repo_rpc_providers = AsyncMock(return_value=QueryResultWrapper([]))
    mock_idx.cross_repo_rpc_consumers = AsyncMock(return_value=QueryResultWrapper([]))
    mock_idx.di_delete_depends_on_edges = AsyncMock()
    mock_idx.di_all_classes = AsyncMock(return_value=QueryResultWrapper([]))
    mock_idx.di_field_and_constructor_candidates = AsyncMock(
        return_value=QueryResultWrapper([])
    )
    mock_idx.entity_delete_accesses_table_edges = AsyncMock()
    mock_idx.entity_semantic_entity_classes = AsyncMock(
        return_value=QueryResultWrapper([])
    )
    mock_idx.entity_dao_candidates = AsyncMock(return_value=QueryResultWrapper([]))
    mock_idx.cross_repo_delete_symbol_edges = AsyncMock()
    mock_idx.cross_repo_symbol_candidates = AsyncMock(
        return_value=QueryResultWrapper([])
    )

    enricher = CrossRepoEnricher(MagicMock(), indexer_store=mock_idx)
    stats = await enricher.enrich_all()

    assert stats["cross_repo_symbol_edges"] == 0
    assert "cross_repo_rpc_edges" in stats
    mock_idx.cross_repo_delete_symbol_edges.assert_awaited()
