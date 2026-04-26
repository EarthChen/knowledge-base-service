"""WikiService BusinessFlow integration (Sprint 3)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from wiki.models import PageType, WikiPage, WikiPageMetadata, WikiStructure, WikiStructureNode
from tests.wiki_config_inject import wiki_service_injection
from wiki.service import WikiService


def _overview_page() -> WikiPage:
    return WikiPage(
        path="README.md",
        title="r1",
        page_type=PageType.REPO_OVERVIEW,
        content="# r1\n",
        diagrams=[],
        source_locations=[],
        metadata=WikiPageMetadata(node_count=0, edge_count=0),
    )


@pytest.mark.asyncio
async def test_generate_creates_business_flows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("wiki.service.gather_confidence_inputs", AsyncMock())
    monkeypatch.setattr("wiki.service.set_wiki_page_confidence_scores", AsyncMock())
    flow_inferencer = MagicMock()
    flow_inferencer._business_flow_enabled = True
    flow_inferencer.find_entry_points = AsyncMock(
        return_value=[
            {
                "uid": "fn-entry",
                "name": "handleRequest",
                "business_summary": "HTTP entry",
                "file": "api/handler.py",
            },
        ],
    )
    flow_dict = {
        "flow_name": "checkout_flow",
        "description": "Checkout",
        "category": "交易",
        "steps": [{"function": "handleRequest", "role": "entry_point", "order": 1}],
    }
    flow_inferencer.infer_from_chain = AsyncMock(return_value=flow_dict)

    chain_rows = [["fn-callee", "processOrder", "Orders", "svc/order.py"]]

    persist_calls: list[tuple[str, dict]] = []

    async def exec_side(cypher: str, params: dict) -> MagicMock:
        persist_calls.append((cypher, params))
        r = MagicMock()
        if "CALLS" in cypher:
            r.raw = chain_rows
        else:
            r.raw = []
        return r

    store = MagicMock()
    store.execute_query = AsyncMock(side_effect=exec_side)
    store.persist_wiki_pages = AsyncMock()

    graph = AsyncMock()
    svc = WikiService(
        graph=graph,
        llm=None,
        repository_exists=AsyncMock(return_value=True),
        store=store,
        deferred_enrichment=None,
        flow_inferencer=flow_inferencer,
        **wiki_service_injection(),
    )

    root = WikiStructureNode(
        path="README.md",
        title="r1",
        page_type=PageType.REPO_OVERVIEW,
        children=[],
    )
    structure = WikiStructure(repository="myrepo", root=root, total_pages=1)
    svc._planner.plan = AsyncMock(return_value=structure)
    svc._compose_all_pages = AsyncMock(return_value=([_overview_page()], False))
    svc._composer_for = MagicMock()

    await svc.generate("myrepo", "repo", "structure", "json")

    flow_inferencer.find_entry_points.assert_awaited_once()
    flow_inferencer.infer_from_chain.assert_awaited_once()
    merge_calls = [c for c, p in persist_calls if "MERGE" in c and "BusinessFlow" in c]
    assert merge_calls, "expected BusinessFlow MERGE"
    _, merge_params = next((c, p) for c, p in persist_calls if "BusinessFlow" in c)
    assert merge_params["uid"] == "BusinessFlow:myrepo:checkout_flow"
    assert merge_params["name"] == "checkout_flow"
    assert json.loads(merge_params["steps"]) == flow_dict["steps"]


@pytest.mark.asyncio
async def test_generate_skips_flows_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("wiki.service.gather_confidence_inputs", AsyncMock())
    monkeypatch.setattr("wiki.service.set_wiki_page_confidence_scores", AsyncMock())
    flow_inferencer = MagicMock()
    flow_inferencer._business_flow_enabled = False
    flow_inferencer.find_entry_points = AsyncMock(return_value=[{"uid": "x"}])
    flow_inferencer.infer_from_chain = AsyncMock()

    store = MagicMock()
    store.execute_query = AsyncMock()
    store.persist_wiki_pages = AsyncMock()

    graph = AsyncMock()
    svc = WikiService(
        graph=graph,
        llm=None,
        repository_exists=AsyncMock(return_value=True),
        store=store,
        flow_inferencer=flow_inferencer,
        **wiki_service_injection(),
    )

    root = WikiStructureNode(
        path="README.md",
        title="r1",
        page_type=PageType.REPO_OVERVIEW,
        children=[],
    )
    structure = WikiStructure(repository="r1", root=root, total_pages=1)
    svc._planner.plan = AsyncMock(return_value=structure)
    svc._compose_all_pages = AsyncMock(return_value=([_overview_page()], False))
    svc._composer_for = MagicMock()

    await svc.generate("r1", "repo", "structure", "json")

    flow_inferencer.find_entry_points.assert_not_called()
    flow_inferencer.infer_from_chain.assert_not_called()


@pytest.mark.asyncio
async def test_generate_without_flow_inferencer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("wiki.service.gather_confidence_inputs", AsyncMock())
    monkeypatch.setattr("wiki.service.set_wiki_page_confidence_scores", AsyncMock())
    store = MagicMock()
    store.persist_wiki_pages = AsyncMock()

    graph = AsyncMock()
    svc = WikiService(
        graph=graph,
        llm=None,
        repository_exists=AsyncMock(return_value=True),
        store=store,
        flow_inferencer=None,
        **wiki_service_injection(),
    )

    root = WikiStructureNode(
        path="README.md",
        title="r1",
        page_type=PageType.REPO_OVERVIEW,
        children=[],
    )
    structure = WikiStructure(repository="r1", root=root, total_pages=1)
    svc._planner.plan = AsyncMock(return_value=structure)
    svc._compose_all_pages = AsyncMock(return_value=([_overview_page()], False))
    svc._composer_for = MagicMock()

    await svc.generate("r1", "repo", "structure", "json")

    svc._compose_all_pages.assert_awaited_once()
    store.execute_query.assert_not_called()


@pytest.mark.asyncio
async def test_build_call_chain_traverses_calls() -> None:
    store = MagicMock()

    async def exec_query(cypher: str, params: dict) -> MagicMock:
        assert params.get("uid") == "fn-a"
        r = MagicMock()
        r.raw = [
            ["fn-b", "b", "sb", "b.py"],
            ["fn-b", "b", "sb", "b.py"],
            ["fn-c", "c", "sc", "c.py"],
        ]
        return r

    store.execute_query = AsyncMock(side_effect=exec_query)

    svc = WikiService(
        graph=AsyncMock(),
        llm=None,
        repository_exists=AsyncMock(return_value=True),
        store=store,
        **wiki_service_injection(),
    )
    ep = {"uid": "fn-a", "name": "a", "business_summary": "sa", "file": "a.py"}
    chain = await svc._build_call_chain(ep)

    assert len(chain) == 3
    assert chain[0]["name"] == "a"
    assert chain[1]["name"] == "b"
    assert chain[2]["name"] == "c"
    store.execute_query.assert_awaited_once()


@pytest.mark.asyncio
async def test_persist_flow_creates_business_flow_node() -> None:
    calls: list[tuple[str, dict]] = []

    async def capture(cypher: str, params: dict) -> None:
        calls.append((cypher, params))

    store = MagicMock()
    store.execute_query = AsyncMock(side_effect=capture)

    svc = WikiService(
        graph=AsyncMock(),
        llm=None,
        repository_exists=AsyncMock(return_value=True),
        store=store,
        **wiki_service_injection(),
    )
    flow = {
        "flow_name": "notify",
        "description": "Sends alerts",
        "category": "系统",
        "steps": [{"function": "send", "role": "notifier", "order": 1}],
    }
    await svc._persist_flow(flow, "repo-x")

    assert len(calls) == 1
    cypher, params = calls[0]
    assert "MERGE (bf:BusinessFlow" in cypher
    assert params["uid"] == "BusinessFlow:repo-x:notify"
    assert params["repo"] == "repo-x"
    assert params["name"] == "notify"
    assert params["desc"] == "Sends alerts"
    assert params["cat"] == "系统"
    assert json.loads(params["steps"]) == flow["steps"]
