import pytest
from unittest.mock import AsyncMock
from store.schema import GraphNode, NodeLabel
from wiki.business_domain_planner import BusinessDomainPlanner


def _make_module(name: str, summary: str = "") -> GraphNode:
    return GraphNode(
        uid=f"Module:test-repo:{name}",
        label=NodeLabel.MODULE,
        properties={"name": name, "business_summary": summary, "path": name},
    )


@pytest.mark.asyncio
async def test_classify_with_llm():
    """With LLM, modules should be classified into business domains."""
    llm = AsyncMock(spec=["generate"])
    llm.generate = AsyncMock(return_value='{"用户管理": ["user_service", "auth_module"], "__infrastructure__": ["utils"]}')
    planner = BusinessDomainPlanner(llm)
    modules = [
        _make_module("user_service", "Handles user registration and profile management"),
        _make_module("auth_module", "Authentication and authorization"),
        _make_module("utils", "General utility functions"),
    ]
    result = await planner.classify("test-repo", modules)
    assert "用户管理" in result
    assert "__infrastructure__" in result


@pytest.mark.asyncio
async def test_classify_without_llm():
    """Without LLM, all modules go to __infrastructure__."""
    planner = BusinessDomainPlanner(llm=None)
    modules = [_make_module("user_service"), _make_module("utils")]
    result = await planner.classify("test-repo", modules)
    assert "__infrastructure__" in result
    assert len(result["__infrastructure__"]) == 2


@pytest.mark.asyncio
async def test_classify_llm_failure_degrades():
    """LLM failure should degrade to all-infrastructure classification."""
    llm = AsyncMock(spec=["generate"])
    llm.generate = AsyncMock(side_effect=Exception("LLM error"))
    planner = BusinessDomainPlanner(llm)
    modules = [_make_module("user_service"), _make_module("utils")]
    result = await planner.classify("test-repo", modules)
    assert "__infrastructure__" in result
    assert len(result["__infrastructure__"]) == 2


@pytest.mark.asyncio
async def test_classify_empty_modules():
    """Empty module list should return empty result."""
    planner = BusinessDomainPlanner(llm=AsyncMock(spec=["generate"]))
    result = await planner.classify("test-repo", [])
    assert result == {}


@pytest.mark.asyncio
async def test_classify_llm_invalid_json_degrades():
    """Invalid LLM JSON response should degrade gracefully."""
    llm = AsyncMock(spec=["generate"])
    llm.generate = AsyncMock(return_value="This is not JSON")
    planner = BusinessDomainPlanner(llm)
    modules = [_make_module("user_service")]
    result = await planner.classify("test-repo", modules)
    assert "__infrastructure__" in result


@pytest.mark.asyncio
async def test_classify_custom_infrastructure_label():
    """Custom infrastructure label should be used."""
    planner = BusinessDomainPlanner(llm=None, infrastructure_label="基础设施")
    modules = [_make_module("utils")]
    result = await planner.classify("test-repo", modules)
    assert "基础设施" in result


@pytest.mark.asyncio
async def test_classify_unclassified_modules_go_to_infrastructure():
    """Modules not in LLM output should be added to infrastructure."""
    llm = AsyncMock(spec=["generate"])
    llm.generate = AsyncMock(return_value='{"用户管理": ["user_service"]}')
    planner = BusinessDomainPlanner(llm)
    modules = [
        _make_module("user_service", "User management"),
        _make_module("orphan_module", "Some orphan"),
    ]
    result = await planner.classify("test-repo", modules)
    assert "用户管理" in result
    assert "__infrastructure__" in result
    assert "orphan_module" in result["__infrastructure__"]


@pytest.mark.asyncio
async def test_classify_large_repo_splits_into_batches():
    """When modules exceed sub_batch_size, multiple LLM calls should be made concurrently."""
    llm = AsyncMock(spec=["generate"])
    llm.generate = AsyncMock(
        side_effect=[
            '{"用户域": ["mod_0", "mod_1", "mod_2"]}',
            '{"支付域": ["mod_3", "mod_4"]}',
        ]
    )
    planner = BusinessDomainPlanner(llm)
    modules = [_make_module(f"mod_{i}", f"summary {i}") for i in range(5)]
    result = await planner.classify("test-repo", modules, sub_batch_size=3, max_concurrency=2)
    assert llm.generate.await_count == 2
    assert set(result["用户域"]) == {"mod_0", "mod_1", "mod_2"}
    assert set(result["支付域"]) == {"mod_3", "mod_4"}


@pytest.mark.asyncio
async def test_classify_batch_failure_isolates_to_infrastructure():
    """If one batch fails, its modules go to infrastructure; other batches succeed."""
    llm = AsyncMock(spec=["generate"])
    llm.generate = AsyncMock(
        side_effect=[
            '{"域A": ["mod_0", "mod_1"]}',
            RuntimeError("LLM timeout on batch 2"),
            '{"域B": ["mod_4", "mod_5"]}',
        ]
    )
    planner = BusinessDomainPlanner(llm)
    modules = [_make_module(f"mod_{i}") for i in range(6)]
    result = await planner.classify("test-repo", modules, sub_batch_size=2, max_concurrency=1)
    assert llm.generate.await_count == 3
    assert set(result["域A"]) == {"mod_0", "mod_1"}
    assert set(result["域B"]) == {"mod_4", "mod_5"}
    assert "mod_2" in result["__infrastructure__"]
    assert "mod_3" in result["__infrastructure__"]


@pytest.mark.asyncio
async def test_classify_merges_same_domain_across_batches():
    """Same domain name across batches should merge module lists."""
    llm = AsyncMock(spec=["generate"])
    llm.generate = AsyncMock(
        side_effect=[
            '{"用户域": ["mod_0", "mod_1"]}',
            '{"用户域": ["mod_2", "mod_3"]}',
        ]
    )
    planner = BusinessDomainPlanner(llm)
    modules = [_make_module(f"mod_{i}") for i in range(4)]
    result = await planner.classify("test-repo", modules, sub_batch_size=2, max_concurrency=2)
    assert set(result["用户域"]) == {"mod_0", "mod_1", "mod_2", "mod_3"}


@pytest.mark.asyncio
async def test_classify_all_batches_fail_degrades_to_infrastructure():
    """If all batches fail, all modules go to infrastructure."""
    llm = AsyncMock(spec=["generate"])
    llm.generate = AsyncMock(side_effect=RuntimeError("LLM down"))
    planner = BusinessDomainPlanner(llm)
    modules = [_make_module(f"mod_{i}") for i in range(5)]
    result = await planner.classify("test-repo", modules, sub_batch_size=2, max_concurrency=2)
    assert list(result.keys()) == ["__infrastructure__"]
    assert len(result["__infrastructure__"]) == 5


@pytest.mark.asyncio
async def test_classify_small_repo_single_batch_unchanged():
    """Modules within sub_batch_size should still use a single LLM call (regression guard)."""
    llm = AsyncMock(spec=["generate"])
    llm.generate = AsyncMock(return_value='{"域X": ["a", "b"]}')
    planner = BusinessDomainPlanner(llm)
    modules = [_make_module("a"), _make_module("b")]
    result = await planner.classify("test-repo", modules, sub_batch_size=80)
    assert llm.generate.await_count == 1
    assert set(result["域X"]) == {"a", "b"}
