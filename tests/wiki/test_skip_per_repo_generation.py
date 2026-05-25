"""Per-repo wiki generation respects business_wiki_skip_repo_pages."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.config import AppWikiFlags as WikiAppConfig, EmbeddingConfig
from wiki.pipeline_orchestrator import PipelineResult


def _stub_pipeline_result(**overrides):
    defaults = dict(
        domain_mapping={"infra": [("repo-a", "Svc")]},
        domain_tree=None,
        pages=[],
        resolved_links={},
        entity_roles={},
        errors=[],
    )
    defaults.update(overrides)
    return PipelineResult(**defaults)


@pytest.fixture
def wiki_service_deps_skip_true():
    graph = AsyncMock()
    graph.list_repository_modules = AsyncMock(return_value=[MagicMock()])
    graph.get_repo_stats = AsyncMock(return_value={"module_count": 0, "class_count": 0, "function_count": 0})
    graph.update_node_property = AsyncMock()
    graph.find_descendants = AsyncMock(return_value=[])
    store = MagicMock()
    store.execute_query = AsyncMock(return_value=MagicMock(data=[], raw=[]))
    store.persist_wiki_pages = AsyncMock()
    wiki_store = MagicMock()
    wiki_store._store = store
    wiki_store.execute_query = AsyncMock(return_value=MagicMock(data=[], raw=[]))
    wiki_store.list_indexed_repositories = AsyncMock(return_value=[
        {"repository": "repo-a", "module_count": 5},
        {"repository": "repo-b", "module_count": 3},
    ])
    wiki_store.get_repo_wiki_freshness = AsyncMock(return_value={
        "repo-a": {"last_indexed": "2026-04-27T10:00:00", "last_generated": "2026-04-26T10:00:00"},
        "repo-b": {"last_indexed": "2026-04-25T10:00:00", "last_generated": "2026-04-26T10:00:00"},
    })
    wiki_store.upsert_wiki_space = AsyncMock()
    wiki_store.upsert_wiki_section = AsyncMock()
    wiki_store.add_has_child_edge = AsyncMock()
    wiki_store.get_wiki_pages_for_business = AsyncMock(return_value=[])
    wiki_store.get_wiki_generation_version = AsyncMock(return_value=None)
    cfg = WikiAppConfig(business_wiki_skip_repo_pages=True)
    return {
        "graph": graph,
        "store": store,
        "wiki_store": wiki_store,
        "wiki_config": cfg,
        "embedding_config": EmbeddingConfig(),
    }


@pytest.mark.asyncio
@patch("wiki.pipeline_orchestrator.run_langgraph_pipeline", new_callable=AsyncMock)
async def test_skip_repo_pages_true_does_not_run_per_repo_even_if_version_missing(
    mock_pipeline, wiki_service_deps_skip_true,
):
    """With skip_repo_pages=True, never run per-repo generate() for 'new' repos."""
    from wiki.service import WikiService

    mock_pipeline.return_value = _stub_pipeline_result()

    svc = WikiService(
        graph=wiki_service_deps_skip_true["graph"],
        llm=None,
        repository_exists=AsyncMock(return_value=True),
        store=wiki_service_deps_skip_true["store"],
        wiki_store=wiki_service_deps_skip_true["wiki_store"],
        wiki_config=wiki_service_deps_skip_true["wiki_config"],
        embedding_config=wiki_service_deps_skip_true["embedding_config"],
    )
    svc.generate = AsyncMock(return_value={"pages": []})

    await svc.generate_business_wiki("default", incremental=True)

    svc.generate.assert_not_called()
    wiki_service_deps_skip_true["wiki_store"].get_wiki_generation_version.assert_not_called()


@pytest.mark.asyncio
@patch("wiki.pipeline_orchestrator.run_langgraph_pipeline", new_callable=AsyncMock)
async def test_skip_repo_pages_false_still_runs_per_repo_for_changed_repos(mock_pipeline):
    """With skip_repo_pages=False, incremental runs per-repo generate for stale repos."""
    from wiki.service import WikiService

    graph = AsyncMock()
    graph.list_repository_modules = AsyncMock(return_value=[MagicMock()])
    graph.get_repo_stats = AsyncMock(return_value={"module_count": 0, "class_count": 0, "function_count": 0})
    graph.update_node_property = AsyncMock()
    graph.find_descendants = AsyncMock(return_value=[])
    store = MagicMock()
    store.execute_query = AsyncMock(return_value=MagicMock(data=[], raw=[]))
    store.persist_wiki_pages = AsyncMock()
    wiki_store = MagicMock()
    wiki_store._store = store
    wiki_store.execute_query = AsyncMock(return_value=MagicMock(data=[], raw=[]))
    wiki_store.list_indexed_repositories = AsyncMock(return_value=[
        {"repository": "repo-a", "module_count": 5},
        {"repository": "repo-b", "module_count": 3},
    ])
    wiki_store.get_repo_wiki_freshness = AsyncMock(return_value={
        "repo-a": {"last_indexed": "2026-04-27T10:00:00", "last_generated": "2026-04-26T10:00:00"},
        "repo-b": {"last_indexed": "2026-04-25T10:00:00", "last_generated": "2026-04-26T10:00:00"},
    })
    wiki_store.upsert_wiki_space = AsyncMock()
    wiki_store.upsert_wiki_section = AsyncMock()
    wiki_store.add_has_child_edge = AsyncMock()
    wiki_store.get_wiki_pages_for_business = AsyncMock(return_value=[])
    wiki_store.get_wiki_generation_version = AsyncMock(return_value=None)
    cfg = WikiAppConfig(business_wiki_skip_repo_pages=False, incremental_enabled=True)

    mock_pipeline.return_value = _stub_pipeline_result()

    svc = WikiService(
        graph=graph,
        llm=None,
        repository_exists=AsyncMock(return_value=True),
        store=store,
        wiki_store=wiki_store,
        wiki_config=cfg,
        embedding_config=EmbeddingConfig(),
    )
    svc.generate = AsyncMock(return_value={"pages": []})

    await svc.generate_business_wiki("default", incremental=True)

    assert svc.generate.call_count == 1
    assert svc.generate.call_args[0][0] == "repo-a"
    wiki_store.get_wiki_generation_version.assert_not_called()
