"""Tests for Batch Y backend pipeline quality P2 fixes."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wiki.pipeline_graph import build_wiki_pipeline, route_by_reorg_type


@pytest.mark.asyncio
async def test_round2_gap_fill_syncs_compound_keys():
    """Round-2 gap-fill should update both bare name and repo|name summary keys."""
    from wiki.nodes.compose import compose_leaf_modules_node

    state = {
        "modules": {
            "repo_a": [
                {
                    "properties": {"name": "UserService", "repository": "repo_a", "path": "a/user.py"},
                    "labels": ["Module"],
                },
            ],
            "repo_b": [
                {
                    "properties": {"name": "UserService", "repository": "repo_b", "path": "b/user.py"},
                    "labels": ["Module"],
                },
            ],
        },
        "entity_roles": {},
    }
    filled_a = {"summary_text": "Filled repo A summary " * 8, "key_methods": []}
    filled_b = {"summary_text": "Filled repo B summary " * 8, "key_methods": []}
    call_count = 0

    async def mock_gen(name, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        repo = kwargs.get("repository", "")
        if kwargs.get("neighbor_summaries"):
            if repo == "repo_a":
                return (name, filled_a)
            if repo == "repo_b":
                return (name, filled_b)
        return (name, {"summary_text": "CONTEXT_GAP", "key_methods": []})

    configurable = {"llm": AsyncMock(), "graph_store": None}

    with patch("wiki.nodes.compose._generate_single_module_summary", side_effect=mock_gen):
        with patch("wiki.nodes.compose.PipelineConcurrency") as mock_pc:
            mock_pc.semaphore.return_value = MagicMock(__aenter__=AsyncMock(), __aexit__=AsyncMock())
            result = await compose_leaf_modules_node(state, {"configurable": configurable})

    summaries = result["module_summaries"]
    assert call_count == 4  # 2 round-1 + 2 round-2
    assert summaries["repo_a|UserService"]["summary_text"] == filled_a["summary_text"]
    assert summaries["repo_b|UserService"]["summary_text"] == filled_b["summary_text"]


def test_route_by_reorg_none_goes_to_finalize():
    assert route_by_reorg_type({"reorg_type": "none"}) == "finalize"


def test_route_by_reorg_light_goes_to_classify():
    assert route_by_reorg_type({"reorg_type": "light"}) == "classify_entity_roles"


def test_pipeline_entry_point_is_detect_reorg():
    pipeline = build_wiki_pipeline(checkpointer=False)
    graph = pipeline.get_graph()
    start_edges = [(e.source, e.target) for e in graph.edges if e.source == "__start__"]
    assert start_edges == [("__start__", "detect_reorg")]


@pytest.mark.asyncio
async def test_reorg_none_skips_classification_nodes():
    """When reorg_type is none, classify nodes must not run."""
    pipeline = build_wiki_pipeline(checkpointer=False)
    classify_calls: list[str] = []

    async def track_classify_entities(state, config=None):
        classify_calls.append("entity_roles")
        return {"entity_roles": {}, "role_stats": {}}

    async def track_classify_arch(state, config=None):
        classify_calls.append("architecture_layers")
        return {"architecture_layers": {}}

    with patch("wiki.pipeline_graph.classify_entities_node", side_effect=track_classify_entities), patch(
        "wiki.pipeline_graph.classify_architecture_layers_node",
        side_effect=track_classify_arch,
    ):
        result = await pipeline.ainvoke(
            {
                "business_id": "y2-test",
                "repositories": ["repo-1"],
                "config": {},
                "modules": {
                    "repo-1": [
                        {
                            "uid": "Module::Svc:0",
                            "label": "Module",
                            "properties": {"name": "Svc"},
                        },
                    ],
                },
                "domain_tree": [{"name": "svc", "modules": ["Svc"], "children": []}],
                "is_incremental": True,
                "affected_domains": [],
                "pages": [],
                "errors": [],
            },
            config={"configurable": {"thread_id": "y2-none-skip"}},
        )

    assert result["reorg_type"] == "none"
    assert classify_calls == []


@pytest.mark.asyncio
async def test_compose_parent_pages_incremental_filters_affected():
    """Incremental run should only regenerate parents with affected children."""
    from wiki.nodes.aggregate import compose_parent_pages_node

    mock_llm = AsyncMock()
    mock_llm.complete_json = AsyncMock(
        return_value=json.loads(
            '{"title": "Parent Overview", "content": "Updated parent.", '
            '"executive_summary": "Summary.", "page_type": "domain_overview"}'
        )
    )

    state = {
        "is_incremental": True,
        "affected_domains": ["payment", "auth"],
        "domain_tree": [
            {
                "name": "commerce",
                "modules": [],
                "children": [
                    {"name": "payment", "modules": ["PaySvc"], "children": []},
                    {"name": "billing", "modules": ["BillSvc"], "children": []},
                ],
            },
            {
                "name": "platform",
                "modules": [],
                "children": [
                    {"name": "auth", "modules": ["AuthSvc"], "children": []},
                    {"name": "notify", "modules": ["NotifySvc"], "children": []},
                ],
            },
            {
                "name": "infra",
                "modules": [],
                "children": [
                    {"name": "cache", "modules": ["CacheSvc"], "children": []},
                ],
            },
        ],
        "leaf_summaries": {
            "payment": {"summary_text": "Payments", "module_count": 1},
            "billing": {"summary_text": "Billing", "module_count": 1},
            "auth": {"summary_text": "Auth", "module_count": 1},
            "notify": {"summary_text": "Notify", "module_count": 1},
            "cache": {"summary_text": "Cache", "module_count": 1},
        },
        "modules": {},
        "entity_roles": {},
    }
    config = {"configurable": {"llm": mock_llm}}

    with patch("wiki.nodes.aggregate.PipelineConcurrency.semaphore") as mock_sem:
        mock_sem.return_value.__aenter__ = AsyncMock(return_value=None)
        mock_sem.return_value.__aexit__ = AsyncMock(return_value=None)
        result = await compose_parent_pages_node(state, config)

    pages = result.get("pages") or []
    assert len(pages) == 2
    paths = {p.get("path", "") for p in pages}
    assert "/__domains__/commerce/_overview" in paths
    assert "/__domains__/platform/_overview" in paths
    assert "/__domains__/infra/_overview" not in paths
    assert mock_llm.complete_json.await_count == 2


@pytest.mark.asyncio
async def test_domain_doc_agent_pre_fill_scopes_by_repo():
    """Pre-fill should query snippets scoped by repo|name pairs for cross-repo modules."""
    from wiki.domain_doc_agent import DomainDocAgent
    from wiki.page_agent import WorkingMemory

    query_params: list[dict] = []

    async def capture_query(cypher, params):
        query_params.append(dict(params))
        result = MagicMock()
        repo = ""
        if params.get("valid_pairs") == ["repo_a|UserService"]:
            repo = "repo_a"
        elif params.get("valid_pairs") == ["repo_b|UserService"]:
            repo = "repo_b"
        result.data = [
            {
                "func_name": f"handle_{repo or 'unknown'}",
                "snippet": f"def handle_{repo or 'unknown'}(): pass",
                "file_path": f"{repo or 'unknown'}/UserService.java",
            },
        ]
        return result

    graph = MagicMock()
    graph.execute_query = AsyncMock(side_effect=capture_query)

    agent = DomainDocAgent(
        domain_name="users",
        llm=MagicMock(),
        graph_store=graph,
    )
    agent._page_agent._graph = graph

    memory_a = WorkingMemory()
    await agent.pre_fill(memory_a, module_names=["UserService"], valid_pairs=["repo_a|UserService"])
    memory_b = WorkingMemory()
    await agent.pre_fill(memory_b, module_names=["UserService"], valid_pairs=["repo_b|UserService"])

    assert query_params[0]["valid_pairs"] == ["repo_a|UserService"]
    assert query_params[1]["valid_pairs"] == ["repo_b|UserService"]
    assert "handle_repo_a" in memory_a.code_snippets[0]
    assert "handle_repo_b" in memory_b.code_snippets[0]
