"""Integration tests for global LLM rate limiter pipeline wiring."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from store.schema import GraphNode, NodeLabel
from tests.wiki_config_inject import inject_wiki_embedding
from wiki.business_pipeline_runner import BusinessPipelineRunner
from wiki.llm_rate_limiter import GlobalLLMRateLimiter
from wiki.nodes.compose import compose_leaf_modules_node
from wiki.persistence import WikiPagePersistence
from wiki.pipeline_orchestrator import run_langgraph_pipeline


def _biz_wiki_mock(**overrides: int) -> MagicMock:
    defaults = {
        "cross_repo_domain_enabled": True,
        "business_domain_enabled": True,
        "business_domain_infrastructure_label": "__infrastructure__",
        "enrichment_enabled": False,
        "code_budget_enabled": False,
        "rag_enabled": False,
        "business_wiki_batch_threshold": 100,
        "business_domain_sub_batch_size": 80,
        "business_domain_classify_timeout": 600,
        "business_domain_max_concurrency": 3,
        "business_domain_cache_ttl": 3600,
        "business_wiki_skip_repo_pages": True,
        "business_repo_concurrency": 2,
        "llm_global_rpm_limit": 30,
        "llm_global_tpm_limit": 50_000,
    }
    defaults.update(overrides)
    mock = MagicMock()
    for key, value in defaults.items():
        setattr(mock, key, value)
    return mock


@pytest.mark.asyncio
async def test_run_langgraph_pipeline_injects_rate_limiter() -> None:
    captured: dict = {}

    async def fake_ainvoke(state, config=None):
        captured["config"] = config
        return {
            "domain_mapping": {},
            "domain_tree": [],
            "pages": [],
            "resolved_links": {},
            "entity_roles": {},
            "errors": [],
        }

    limiter = GlobalLLMRateLimiter(rpm_limit=10, tpm_limit=5000)
    fake_pipeline = AsyncMock()
    fake_pipeline.ainvoke = fake_ainvoke

    with patch("wiki.pipeline_orchestrator.build_wiki_pipeline", return_value=fake_pipeline):
        await run_langgraph_pipeline(
            business_id="biz-1",
            repositories=["repo-a"],
            all_modules={"repo-a": []},
            llm="fake-llm",
            llm_rate_limiter=limiter,
        )

    cfg = captured["config"]["configurable"]
    assert cfg["llm_rate_limiter"] is limiter


@pytest.mark.asyncio
async def test_business_pipeline_runner_creates_and_injects_limiter() -> None:
    mock_wiki_store = AsyncMock()
    mock_wiki_store.list_indexed_repositories = AsyncMock(
        return_value=[{"repository": "test-repo", "module_count": 1}],
    )
    mock_wiki_store.upsert_wiki_space = AsyncMock()
    mock_wiki_store.upsert_wiki_section = AsyncMock()
    mock_wiki_store.add_has_child_edge = AsyncMock()
    mock_wiki_store.get_repo_wiki_freshness = AsyncMock(return_value={})
    mock_wiki_store.get_wiki_pages_for_business = AsyncMock(return_value=[])

    graph = AsyncMock()
    graph.list_repository_modules = AsyncMock(
        return_value=[
            GraphNode(
                uid="mod-1",
                label=NodeLabel.MODULE,
                properties={"name": "SvcA"},
            ),
        ],
    )
    graph.find_descendants = AsyncMock(return_value=[])
    graph.update_node_property = AsyncMock()

    store = AsyncMock()
    store.execute_query = AsyncMock(return_value=MagicMock(data=[]))

    persistence = MagicMock(spec=WikiPagePersistence)
    persistence.list_pinned_modules = AsyncMock(return_value=[])
    persistence.cleanup_stale_domain_edges = AsyncMock()
    persistence.cleanup_stale_domain_sections = AsyncMock()

    tree_linker = MagicMock()
    tree_linker.link_pages_to_tree = AsyncMock()

    pipeline_result = MagicMock()
    pipeline_result.domain_mapping = {"domain-a": [("test-repo", "SvcA")]}
    pipeline_result.domain_tree = None
    pipeline_result.pages = []
    pipeline_result.domain_display_names = {"domain-a": "Domain A"}
    pipeline_result.resolved_links = {}

    runner = BusinessPipelineRunner(
        store=store,
        graph=graph,
        wiki_cfg=_biz_wiki_mock(),
        wiki_store=mock_wiki_store,
        persistence=persistence,
        llm_factory=None,
        embedding_cfg=inject_wiki_embedding()[1],
        budget_resolver=MagicMock(),
        flow_writer=MagicMock(),
        tree_linker=tree_linker,
        memory_loop=None,
        community_service=None,
        llm_resolver=lambda _p: AsyncMock(),
        redis_conn=None,
        task_supervisor=None,
        repo_generator=AsyncMock(),
        persist_pages=AsyncMock(),
        bulk_set_wiki_code_hashes=AsyncMock(),
        persist_resolved_wikilinks=AsyncMock(),
    )

    with patch(
        "wiki.pipeline_orchestrator.run_langgraph_pipeline",
        new_callable=AsyncMock,
        return_value=pipeline_result,
    ) as mock_pipeline:
        await runner.run("biz-test")

    limiter = mock_pipeline.await_args.kwargs.get("llm_rate_limiter")
    assert isinstance(limiter, GlobalLLMRateLimiter)
    assert limiter._rpm_limit == 30
    assert limiter._tpm_limit == 50_000


@pytest.mark.asyncio
async def test_compose_leaf_modules_acquires_llm_quota() -> None:
    mock_limiter = AsyncMock(spec=GlobalLLMRateLimiter)
    mock_llm = AsyncMock()
    mock_llm.complete_json = AsyncMock(
        return_value={"summary_text": "Module summary.", "key_methods": [], "dependencies": []},
    )

    state = {
        "modules": {
            "repo-a": [
                {
                    "uid": "mod-1",
                    "properties": {"name": "SvcA", "methods": ["run"], "calls": []},
                },
            ],
        },
        "entity_roles": {"mod-1": "core"},
    }
    config = {
        "configurable": {
            "llm": mock_llm,
            "llm_rate_limiter": mock_limiter,
        },
    }

    with patch.dict("os.environ", {"USE_AGENT_COMPOSE": "false"}):
        await compose_leaf_modules_node(state, config)

    mock_limiter.acquire.assert_awaited()
