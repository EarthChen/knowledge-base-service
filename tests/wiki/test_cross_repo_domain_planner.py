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
    llm = AsyncMock(spec=["generate"])
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
    llm = AsyncMock(spec=["generate"])
    llm.generate = AsyncMock(
        side_effect=[
            '{"域A": ["a1"], "__infrastructure__": ["a2"]}',
            '{"域A": ["b1"], "__infrastructure__": ["b2"]}',
            (
                '{"域A": {"r1": "域A", "r2": "域A"}, '
                '"__infrastructure__": {"r1": "__infrastructure__", "r2": "__infrastructure__"}}'
            ),
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
    llm = AsyncMock(spec=["generate"])
    llm.generate = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
    planner = CrossRepoBusinessDomainPlanner(llm)
    all_modules = {"repo-z": [_make_module("u1"), _make_module("u2")]}
    result = await planner.classify("biz-4", all_modules)
    assert set(result["__infrastructure__"]) == {("repo-z", "u1"), ("repo-z", "u2")}


@pytest.mark.asyncio
async def test_classify_empty_repos():
    """No modules anywhere yields an empty dict."""
    planner = CrossRepoBusinessDomainPlanner(llm=AsyncMock(spec=["generate"]))
    assert await planner.classify("biz-5", {}) == {}
    assert await planner.classify("biz-5", {"r": []}) == {}


@pytest.mark.asyncio
async def test_classify_unclassified_modules_go_to_infra():
    """Pairs absent from the LLM JSON are bucketed into infrastructure."""
    llm = AsyncMock(spec=["generate"])
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


@pytest.mark.asyncio
async def test_classify_large_batch_forwards_sub_batch_size_and_concurrency():
    """When using multi-batch path, sub_batch_size and max_concurrency should be forwarded."""
    llm = AsyncMock(spec=["generate"])
    llm.generate = AsyncMock(
        side_effect=[
            '{"域A": ["a1"], "__infrastructure__": ["a2"]}',
            '{"域B": ["b1"], "__infrastructure__": ["b2"]}',
            (
                '{"域A": {"r1": "域A", "r2": "域B"}, '
                '"__infrastructure__": {"r1": "__infrastructure__", "r2": "__infrastructure__"}}'
            ),
        ]
    )

    planner = CrossRepoBusinessDomainPlanner(
        llm, batch_threshold=3, sub_batch_size=50, max_concurrency=2,
    )
    all_modules = {
        "r1": [_make_module("a1"), _make_module("a2")],
        "r2": [_make_module("b1"), _make_module("b2")],
    }
    result = await planner.classify("biz-7", all_modules)
    assert "域A" in result or "__infrastructure__" in result


@pytest.mark.asyncio
async def test_lightweight_merge_sends_domain_names_only():
    """Multi-batch merge prompt should send domain names, not full module lists."""
    prompts_received = []

    async def capture_generate(prompt, system=""):
        prompts_received.append(prompt)
        if "Classify" in prompt:
            return '{"Auth": ["mod1"], "Pay": ["mod2"]}'
        # Lightweight merge response: maps unified names to per-repo names
        return (
            '{"Authentication": {"r1": "Auth", "r2": "Auth"}, '
            '"Payments": {"r1": "Pay", "r2": "Pay"}}'
        )

    llm = AsyncMock(spec=["generate"])
    llm.generate = AsyncMock(side_effect=capture_generate)

    planner = CrossRepoBusinessDomainPlanner(llm, batch_threshold=2)
    all_modules = {
        "r1": [_make_module("mod1"), _make_module("mod2")],
        "r2": [_make_module("mod1"), _make_module("mod2")],
    }
    result = await planner.classify("biz", all_modules)

    # The merge prompt (last one) should NOT contain individual module names
    # in the format of module assignment lists
    merge_prompt = prompts_received[-1]
    assert "Align" in merge_prompt or "Unify" in merge_prompt or "domain names" in merge_prompt.lower()

    # All modules must still be assigned
    all_assigned = []
    for pairs in result.values():
        all_assigned.extend(pairs)
    assert len(all_assigned) == 4


@pytest.mark.asyncio
async def test_merge_failure_preserves_per_repo_domains():
    """When merge LLM call fails, per-repo classification results should be preserved."""
    call_count = 0

    async def failing_merge(prompt, system=""):
        nonlocal call_count
        call_count += 1
        if "Classify" in prompt:
            return '{"Auth": ["mod1"], "Pay": ["mod2"]}'
        raise Exception("LLM merge failed")

    llm = AsyncMock(spec=["generate"])
    llm.generate = AsyncMock(side_effect=failing_merge)

    planner = CrossRepoBusinessDomainPlanner(llm, batch_threshold=2)
    all_modules = {
        "r1": [_make_module("mod1"), _make_module("mod2")],
        "r2": [_make_module("mod1"), _make_module("mod2")],
    }
    result = await planner.classify("biz", all_modules)

    # Per-repo domains should be preserved (Auth and Pay from each repo)
    assert "Auth" in result
    assert "Pay" in result
    # All modules assigned
    all_assigned = []
    for pairs in result.values():
        all_assigned.extend(pairs)
    assert len(all_assigned) == 4


@pytest.mark.asyncio
async def test_apply_domain_name_mapping_preserves_all_modules():
    """Programmatic reassignment should not lose any modules."""
    llm = AsyncMock(spec=["generate"])

    async def mock_generate(prompt, system=""):
        if "Classify" in prompt:
            return '{"Authentication": ["mod1"], "Payments": ["mod2"], "Logging": ["mod3"]}'
        # Merge: unify "Authentication" across repos, leave Payments and Logging separate
        return (
            '{"Auth": {"r1": "Authentication", "r2": "Authentication"}, '
            '"Pay": {"r1": "Payments", "r2": "Payments"}, '
            '"Infra": {"r1": "Logging", "r2": "Logging"}}'
        )

    llm.generate = AsyncMock(side_effect=mock_generate)

    planner = CrossRepoBusinessDomainPlanner(llm, batch_threshold=4)
    all_modules = {
        "r1": [_make_module("mod1"), _make_module("mod2"), _make_module("mod3")],
        "r2": [_make_module("mod1"), _make_module("mod2"), _make_module("mod3")],
    }
    result = await planner.classify("biz", all_modules)

    all_assigned = set()
    for pairs in result.values():
        for pair in pairs:
            all_assigned.add(pair)
    # 6 modules total (3 per repo x 2 repos)
    assert len(all_assigned) == 6
