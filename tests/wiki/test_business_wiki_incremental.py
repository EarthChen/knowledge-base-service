"""Tests for incremental business wiki generation (repo-level skip)."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
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
def wiki_service_deps():
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
    cfg = WikiAppConfig(business_wiki_skip_repo_pages=False, incremental_enabled=True)
    return {
        "graph": graph,
        "store": store,
        "wiki_store": wiki_store,
        "wiki_config": cfg,
        "embedding_config": EmbeddingConfig(),
    }


@pytest.mark.asyncio
@patch("wiki.pipeline_orchestrator.run_langgraph_pipeline", new_callable=AsyncMock)
async def test_incremental_skips_unchanged_repo(mock_pipeline, wiki_service_deps):
    """When incremental=True, repo-b (not changed) should be skipped."""
    from wiki.service import WikiService

    mock_pipeline.return_value = _stub_pipeline_result()

    svc = WikiService(
        graph=wiki_service_deps["graph"],
        llm=None,
        repository_exists=AsyncMock(return_value=True),
        store=wiki_service_deps["store"],
        wiki_store=wiki_service_deps["wiki_store"],
        wiki_config=wiki_service_deps["wiki_config"],
        embedding_config=wiki_service_deps["embedding_config"],
    )
    svc.generate = AsyncMock(return_value={"pages": []})

    result = await svc.generate_business_wiki("default", incremental=True)
    assert svc.generate.call_count == 1
    call_args = svc.generate.call_args
    assert call_args[0][0] == "repo-a"
    assert "repo-b" in result.get("skipped_repos", [])


@pytest.mark.asyncio
@patch("wiki.pipeline_orchestrator.run_langgraph_pipeline", new_callable=AsyncMock)
async def test_full_regen_all_repos(mock_pipeline, wiki_service_deps):
    """When incremental=False, all repos are generated."""
    from wiki.service import WikiService

    mock_pipeline.return_value = _stub_pipeline_result()

    svc = WikiService(
        graph=wiki_service_deps["graph"],
        llm=None,
        repository_exists=AsyncMock(return_value=True),
        store=wiki_service_deps["store"],
        wiki_store=wiki_service_deps["wiki_store"],
        wiki_config=wiki_service_deps["wiki_config"],
        embedding_config=wiki_service_deps["embedding_config"],
    )
    svc.generate = AsyncMock(return_value={"pages": []})

    result = await svc.generate_business_wiki("default", incremental=False)
    assert svc.generate.call_count == 2
    assert result.get("skipped_repos", []) == []


@pytest.mark.asyncio
@patch("wiki.pipeline_orchestrator.run_langgraph_pipeline", new_callable=AsyncMock)
async def test_progress_callback_called(mock_pipeline, wiki_service_deps):
    """Progress callback should be called for each repo."""
    from wiki.service import WikiService

    mock_pipeline.return_value = _stub_pipeline_result()

    svc = WikiService(
        graph=wiki_service_deps["graph"],
        llm=None,
        repository_exists=AsyncMock(return_value=True),
        store=wiki_service_deps["store"],
        wiki_store=wiki_service_deps["wiki_store"],
        wiki_config=wiki_service_deps["wiki_config"],
        embedding_config=wiki_service_deps["embedding_config"],
    )
    svc.generate = AsyncMock(return_value={"pages": []})

    progress_calls = []
    async def on_progress(info):
        progress_calls.append(info)

    await svc.generate_business_wiki("default", incremental=True, progress_callback=on_progress)
    assert len(progress_calls) >= 1
    assert any(p.get("current_repo") == "repo-a" for p in progress_calls)
