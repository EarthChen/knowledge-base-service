import pytest
from unittest.mock import AsyncMock

from store.schema import GraphNode, NodeLabel
from wiki.cross_repo_domain_planner import CrossRepoBusinessDomainPlanner


def _make_module(name: str, summary: str = "", docstring: str = "") -> GraphNode:
    props: dict[str, str] = {"name": name, "path": name}
    if summary:
        props["business_summary"] = summary
    if docstring:
        props["docstring"] = docstring
    return GraphNode(
        uid=f"Module:test:{name}",
        label=NodeLabel.MODULE,
        properties=props,
    )


@pytest.mark.asyncio
async def test_classify_small_batch_single_llm_call():
    """When total modules <= batch_threshold, one LLM call classifies all repos."""
    llm = AsyncMock()
    llm.generate = AsyncMock(
        return_value=(
            '{"支付域": [["repo-a", "billing"], ["repo-b", "payments"]], '
            '"__infrastructure__": [["repo-a", "utils"]]}'
        )
    )
    planner = CrossRepoBusinessDomainPlanner(llm, batch_threshold=100)
    all_modules = {
        "repo-a": [
            _make_module("billing", summary="Billing core"),
            _make_module("utils", docstring="Shared helpers"),
        ],
        "repo-b": [_make_module("payments", summary="Payment gateway")],
    }
    result = await planner.classify("biz-1", all_modules)
    assert llm.generate.await_count == 1
    assert "支付域" in result
    assert set(result["支付域"]) == {("repo-a", "billing"), ("repo-b", "payments")}
    assert result["__infrastructure__"] == [("repo-a", "utils")]


@pytest.mark.asyncio
async def test_classify_large_batch_splits_by_repo():
    """When total modules > batch_threshold, per-repo planner runs then one merge LLM call."""
    llm = AsyncMock()
    llm.generate = AsyncMock(
        side_effect=[
            '{"域A": ["a1"], "__infrastructure__": ["a2"]}',
            '{"域A": ["b1"], "__infrastructure__": ["b2"]}',
            '{"域A": [["r1", "a1"], ["r2", "b1"]], "__infrastructure__": [["r1", "a2"], ["r2", "b2"]]}',
        ]
    )
    planner = CrossRepoBusinessDomainPlanner(llm, batch_threshold=3)
    all_modules = {
        "r1": [_make_module("a1"), _make_module("a2")],
        "r2": [_make_module("b1"), _make_module("b2")],
    }
    result = await planner.classify("biz-2", all_modules)
    assert llm.generate.await_count == 3
    assert "域A" in result
    assert set(result["域A"]) == {("r1", "a1"), ("r2", "b1")}
    infra = set(result["__infrastructure__"])
    assert infra == {("r1", "a2"), ("r2", "b2")}


@pytest.mark.asyncio
async def test_classify_without_llm_all_infrastructure():
    """Without LLM, every module is placed under the infrastructure label with (repo, name)."""
    planner = CrossRepoBusinessDomainPlanner(llm=None)
    all_modules = {
        "repo-x": [_make_module("m1"), _make_module("m2")],
        "repo-y": [_make_module("m3")],
    }
    result = await planner.classify("biz-3", all_modules)
    assert list(result.keys()) == ["__infrastructure__"]
    pairs = set(result["__infrastructure__"])
    assert pairs == {("repo-x", "m1"), ("repo-x", "m2"), ("repo-y", "m3")}


@pytest.mark.asyncio
async def test_classify_llm_failure_degrades():
    """LLM errors degrade to all modules under infrastructure."""
    llm = AsyncMock()
    llm.generate = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
    planner = CrossRepoBusinessDomainPlanner(llm)
    all_modules = {"repo-z": [_make_module("u1"), _make_module("u2")]}
    result = await planner.classify("biz-4", all_modules)
    assert set(result["__infrastructure__"]) == {("repo-z", "u1"), ("repo-z", "u2")}


@pytest.mark.asyncio
async def test_classify_empty_repos():
    """No modules anywhere yields an empty dict."""
    planner = CrossRepoBusinessDomainPlanner(llm=AsyncMock())
    assert await planner.classify("biz-5", {}) == {}
    assert await planner.classify("biz-5", {"r": []}) == {}


@pytest.mark.asyncio
async def test_classify_unclassified_modules_go_to_infra():
    """Pairs absent from the LLM JSON are bucketed into infrastructure."""
    llm = AsyncMock()
    llm.generate = AsyncMock(
        return_value='{"核心": [["repo-p", "seen"]]}'
    )
    planner = CrossRepoBusinessDomainPlanner(llm, batch_threshold=50)
    all_modules = {
        "repo-p": [_make_module("seen"), _make_module("missing")],
    }
    result = await planner.classify("biz-6", all_modules)
    assert "核心" in result
    assert result["核心"] == [("repo-p", "seen")]
    assert "missing" in {m for _, m in result["__infrastructure__"]}
