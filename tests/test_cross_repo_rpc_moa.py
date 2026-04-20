"""Cross-repo Moa RPC matching: @MoaProvider without args + implemented interfaces."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from indexer.cross_repo_enricher import CrossRepoEnricher
from store.falkordb_store import QueryResultWrapper


@pytest.mark.asyncio
async def test_moa_provider_no_args_matches_consumer_service_uri_fqn() -> None:
    """Provider keys include graph ``interfaces`` so FQN serviceUri resolves."""
    mock_idx = MagicMock()
    mock_idx.cross_repo_delete_edges = AsyncMock()
    mock_idx.cross_repo_merge_rpc_edge = AsyncMock()

    mock_idx.cross_repo_rpc_providers = AsyncMock(
        return_value=QueryResultWrapper(
            [
                {
                    "uid": "Class:prov:OperationListServiceImpl:1",
                    "name": "OperationListServiceImpl",
                    "rpc_interface": "",
                    "repository": "repo-b",
                    "annotations": ["@MoaProvider"],
                    "fqn": "com.example.OperationListServiceImpl",
                    "interfaces": ["OperationListService"],
                    "base_classes": [],
                }
            ]
        )
    )
    service_uri = "com.immomo.moaservice.ultron.user.io.interfaces.external.OperationListService"
    mock_idx.cross_repo_rpc_consumers = AsyncMock(
        return_value=QueryResultWrapper(
            [
                {
                    "uid": "Function:consumer:field:operationListService:10",
                    "name": "field:operationListService",
                    "annotations": [f'@MoaConsumer(serviceUri = "{service_uri}")'],
                    "repository": "repo-a",
                    "class_uid": None,
                    "class_name": None,
                    "class_repository": None,
                }
            ]
        )
    )

    enricher = CrossRepoEnricher(MagicMock(), indexer_store=mock_idx)
    count = await enricher._enrich_cross_repo_rpc()

    assert count == 1
    mock_idx.cross_repo_merge_rpc_edge.assert_awaited_once()
    args = mock_idx.cross_repo_merge_rpc_edge.await_args.args
    assert args[0] == "Function:consumer:field:operationListService:10"
    assert args[1] == "Class:prov:OperationListServiceImpl:1"
    assert args[2] == "repo-a"
    assert args[3] == "repo-b"
    assert args[4] == service_uri


@pytest.mark.asyncio
async def test_moa_match_simple_name_from_consumer_fqn() -> None:
    """Consumer FQN serviceUri matches provider registered only by interface simple name."""
    mock_idx = MagicMock()
    mock_idx.cross_repo_delete_edges = AsyncMock()
    mock_idx.cross_repo_merge_rpc_edge = AsyncMock()

    mock_idx.cross_repo_rpc_providers = AsyncMock(
        return_value=QueryResultWrapper(
            [
                {
                    "uid": "p1",
                    "name": "SomeServiceImpl",
                    "rpc_interface": "",
                    "repository": "repo-b",
                    "annotations": ["@MoaProvider"],
                    "fqn": "x.SomeServiceImpl",
                    "interfaces": ["SomeService"],
                    "base_classes": [],
                }
            ]
        )
    )
    mock_idx.cross_repo_rpc_consumers = AsyncMock(
        return_value=QueryResultWrapper(
            [
                {
                    "uid": "c1",
                    "name": "field:x",
                    "annotations": ['@MoaConsumer(serviceUri = "com.vendor.pkg.SomeService")'],
                    "repository": "repo-a",
                    "class_uid": None,
                    "class_name": None,
                    "class_repository": None,
                }
            ]
        )
    )

    enricher = CrossRepoEnricher(MagicMock(), indexer_store=mock_idx)
    count = await enricher._enrich_cross_repo_rpc()

    assert count == 1
    mock_idx.cross_repo_merge_rpc_edge.assert_awaited_once()


@pytest.mark.asyncio
async def test_same_repo_skips_edge() -> None:
    mock_idx = MagicMock()
    mock_idx.cross_repo_delete_edges = AsyncMock()
    mock_idx.cross_repo_merge_rpc_edge = AsyncMock()
    mock_idx.cross_repo_rpc_providers = AsyncMock(
        return_value=QueryResultWrapper(
            [
                {
                    "uid": "p1",
                    "name": "Impl",
                    "rpc_interface": "",
                    "repository": "repo-a",
                    "annotations": ["@MoaProvider"],
                    "fqn": "x.Impl",
                    "interfaces": ["Iface"],
                    "base_classes": [],
                }
            ]
        )
    )
    mock_idx.cross_repo_rpc_consumers = AsyncMock(
        return_value=QueryResultWrapper(
            [
                {
                    "uid": "c1",
                    "name": "field:x",
                    "annotations": ['@MoaConsumer(serviceUri = "a.b.Iface")'],
                    "repository": "repo-a",
                    "class_uid": None,
                    "class_name": None,
                    "class_repository": None,
                }
            ]
        )
    )
    enricher = CrossRepoEnricher(MagicMock(), indexer_store=mock_idx)
    count = await enricher._enrich_cross_repo_rpc()
    assert count == 0
    mock_idx.cross_repo_merge_rpc_edge.assert_not_awaited()
