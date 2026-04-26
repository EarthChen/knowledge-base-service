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
    llm = AsyncMock()
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
    llm = AsyncMock()
    llm.generate = AsyncMock(side_effect=Exception("LLM error"))
    planner = BusinessDomainPlanner(llm)
    modules = [_make_module("user_service"), _make_module("utils")]
    result = await planner.classify("test-repo", modules)
    assert "__infrastructure__" in result
    assert len(result["__infrastructure__"]) == 2


@pytest.mark.asyncio
async def test_classify_empty_modules():
    """Empty module list should return empty result."""
    planner = BusinessDomainPlanner(llm=AsyncMock())
    result = await planner.classify("test-repo", [])
    assert result == {}


@pytest.mark.asyncio
async def test_classify_llm_invalid_json_degrades():
    """Invalid LLM JSON response should degrade gracefully."""
    llm = AsyncMock()
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
    llm = AsyncMock()
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
