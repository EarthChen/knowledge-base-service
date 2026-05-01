"""Unit tests for wiki.flow_writer.BusinessFlowWriter."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wiki.flow_writer import BusinessFlowWriter


@pytest.mark.asyncio
async def test_generate_business_flows_no_inferencer() -> None:
    writer = BusinessFlowWriter(MagicMock(), MagicMock(), flow_inferencer=None)
    assert await writer.generate_business_flows("my-repo") == 0


@pytest.mark.asyncio
async def test_generate_business_flows_inferencer_disabled() -> None:
    inferencer = MagicMock()
    inferencer._business_flow_enabled = False
    writer = BusinessFlowWriter(MagicMock(), MagicMock(), inferencer)
    inferencer.find_entry_points = AsyncMock()
    assert await writer.generate_business_flows("r") == 0
    inferencer.find_entry_points.assert_not_called()


@pytest.mark.asyncio
async def test_generate_business_flows_creates_one_flow_per_entry() -> None:
    store = MagicMock()
    inferencer = MagicMock()
    inferencer._business_flow_enabled = True
    inferencer.find_entry_points = AsyncMock(
        return_value=[
            {"uid": "f1", "name": "a", "business_summary": "s", "file": "a.py"},
            {"uid": "f2", "name": "b", "business_summary": "", "file": "b.py"},
        ]
    )
    inferencer.infer_from_chain = AsyncMock(
        side_effect=[{"flow_name": "flow_a", "steps": []}, None],
    )
    writer = BusinessFlowWriter(store, MagicMock(), inferencer)

    chain_a = [
        {"name": "a", "business_summary": "s", "file": "a.py"},
        {"name": "callee", "business_summary": "x", "file": "c.py"},
    ]
    chain_b = [{"name": "b", "business_summary": "", "file": "b.py"}]

    with patch.object(writer, "build_call_chain", new=AsyncMock(side_effect=[chain_a, chain_b])):
        with patch.object(writer, "persist_flow", new=AsyncMock()) as pf:
            created = await writer.generate_business_flows("repo-x")

    assert created == 1
    assert inferencer.infer_from_chain.await_count == 2
    pf.assert_awaited_once()
    assert pf.await_args.args[0]["flow_name"] == "flow_a"


@pytest.mark.asyncio
async def test_build_call_chain_no_store() -> None:
    writer = BusinessFlowWriter(None, MagicMock(), MagicMock())
    assert await writer.build_call_chain({"uid": "u", "name": "n"}) == []


@pytest.mark.asyncio
async def test_build_call_chain_missing_uid() -> None:
    store = MagicMock()
    store.execute_query = AsyncMock()
    writer = BusinessFlowWriter(store, MagicMock(), MagicMock())
    assert await writer.build_call_chain({"name": "only"}) == []
    store.execute_query.assert_not_called()


@pytest.mark.asyncio
async def test_build_call_chain_merges_entry_point_and_callees() -> None:
    store = MagicMock()
    store.execute_query = AsyncMock(
        return_value=MagicMock(raw=[["uid-b", "fn", "summary", "f2.py"]])
    )
    writer = BusinessFlowWriter(store, MagicMock(), MagicMock())
    ep = {"uid": "uid-a", "name": "root", "business_summary": "rs", "file": "f1.py"}
    chain = await writer.build_call_chain(ep)
    assert chain == [
        {"name": "root", "business_summary": "rs", "file": "f1.py"},
        {"name": "fn", "business_summary": "summary", "file": "f2.py"},
    ]


@pytest.mark.asyncio
async def test_build_call_chain_uses_result_set_when_no_raw() -> None:
    store = MagicMock()
    store.execute_query = AsyncMock(
        return_value=MagicMock(spec=["result_set"], raw=None, result_set=(["u2", "n2", "", "z.py"],))
    )
    writer = BusinessFlowWriter(store, MagicMock(), MagicMock())
    chain = await writer.build_call_chain({"uid": "u1", "name": "a", "business_summary": "", "file": "a.py"})
    assert len(chain) == 2


@pytest.mark.asyncio
async def test_persist_flow_no_store() -> None:
    writer = BusinessFlowWriter(None, MagicMock(), MagicMock())
    await writer.persist_flow({"flow_name": "x"}, "repo")
    # no exception


@pytest.mark.asyncio
async def test_persist_flow_writes_merge_query() -> None:
    store = MagicMock()
    store.execute_query = AsyncMock()
    writer = BusinessFlowWriter(store, MagicMock(), MagicMock())
    flow = {
        "flow_name": "checkout",
        "description": "desc",
        "category": "core",
        "steps": [{"n": 1}],
    }
    await writer.persist_flow(flow, "svc")

    store.execute_query.assert_awaited_once()
    kwargs = store.execute_query.await_args.args[1]
    assert kwargs["uid"] == "BusinessFlow:svc:checkout"
    assert kwargs["repo"] == "svc"
    assert "steps" in kwargs
