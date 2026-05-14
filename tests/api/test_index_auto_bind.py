"""Tests for automatic business↔repository binding after successful indexing."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import api.kb_state as kb_state
from api.routes.kb_index_helpers import run_index_task
from api.routes.kb_schemas import IndexRequest


@pytest.fixture
def kb_state_restore() -> None:
    saved_registry = kb_state.registry
    saved_tm = kb_state.task_manager
    saved_rr = kb_state.repo_registry
    yield
    kb_state.registry = saved_registry
    kb_state.task_manager = saved_tm
    kb_state.repo_registry = saved_rr


@pytest.mark.asyncio
async def test_run_index_task_auto_binds_new_repo(kb_state_restore: None, tmp_path) -> None:
    business_id = "test-biz"
    mock_bm = MagicMock()
    mock_bm.get_repos.return_value = ["repo-a"]

    mock_registry = MagicMock()
    mock_registry.business_manager = mock_bm
    mock_svc = MagicMock()
    mock_svc.mcp_handler.handle_rag_index = AsyncMock(return_value={"indexed_files": 1})
    mock_registry.get_service = AsyncMock(return_value=mock_svc)

    mock_tm = MagicMock()
    mock_tm.make_progress_callback.return_value = None

    kb_state.registry = mock_registry
    kb_state.task_manager = mock_tm
    kb_state.repo_registry = MagicMock()

    repo_dir = str(tmp_path / "proj")
    tmp_path.joinpath("proj").mkdir()

    req = IndexRequest(
        business_id=business_id,
        directory=repo_dir,
        repository="new-repo",
        mode="full",
    )

    with (
        patch("api.routes.kb_index_helpers.GraphQueryRepository") as gq_cls,
        patch("indexer.cross_repo_enricher.CrossRepoEnricher") as ce_cls,
    ):
        gq_inst = MagicMock()
        gq_inst.tag_unowned_nodes = AsyncMock()
        gq_inst.get_repository_sample_file = AsyncMock(return_value=None)
        gq_cls.return_value = gq_inst

        ce_inst = MagicMock()
        ce_inst.enrich_all = AsyncMock(return_value={})
        ce_cls.return_value = ce_inst

        await run_index_task("task-1", req, business_id)

    mock_bm.set_repos.assert_called_once_with(business_id, ["repo-a", "new-repo"])
    mock_tm.mark_completed.assert_called_once()


@pytest.mark.asyncio
async def test_run_index_task_auto_bind_idempotent_when_repo_already_bound(
    kb_state_restore: None,
    tmp_path,
) -> None:
    business_id = "test-biz"
    mock_bm = MagicMock()
    mock_bm.get_repos.return_value = ["repo-a", "new-repo"]

    mock_registry = MagicMock()
    mock_registry.business_manager = mock_bm
    mock_svc = MagicMock()
    mock_svc.mcp_handler.handle_rag_index = AsyncMock(return_value={"indexed_files": 1})
    mock_registry.get_service = AsyncMock(return_value=mock_svc)

    mock_tm = MagicMock()
    mock_tm.make_progress_callback.return_value = None

    kb_state.registry = mock_registry
    kb_state.task_manager = mock_tm
    kb_state.repo_registry = MagicMock()

    repo_dir = str(tmp_path / "proj")
    tmp_path.joinpath("proj").mkdir()

    req = IndexRequest(
        business_id=business_id,
        directory=repo_dir,
        repository="new-repo",
        mode="full",
    )

    with (
        patch("api.routes.kb_index_helpers.GraphQueryRepository") as gq_cls,
        patch("indexer.cross_repo_enricher.CrossRepoEnricher") as ce_cls,
    ):
        gq_inst = MagicMock()
        gq_inst.tag_unowned_nodes = AsyncMock()
        gq_inst.get_repository_sample_file = AsyncMock(return_value=None)
        gq_cls.return_value = gq_inst

        ce_inst = MagicMock()
        ce_inst.enrich_all = AsyncMock(return_value={})
        ce_cls.return_value = ce_inst

        await run_index_task("task-1", req, business_id)

    mock_bm.set_repos.assert_not_called()
    mock_tm.mark_completed.assert_called_once()
