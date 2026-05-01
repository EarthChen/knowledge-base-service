import pytest
from unittest.mock import AsyncMock


def _make_page(path: str, content: str, domain: str = "test") -> dict:
    return {
        "path": path,
        "title": path.split("/")[-1],
        "content": content,
        "page_type": "topic",
        "domain": domain,
        "diagrams": [{"type": "flowchart", "content": "graph TD\nA-->B"}],
        "source_locations": [],
        "metadata": {"domain": domain},
    }


GOOD_CONTENT = (
    "## 业务概述\nThis service handles payments and settlement for the platform. "
    "It coordinates with billing and ledger services for end-to-end money movement.\n\n"
    "## 核心业务流程\n- Validate request\n- Charge customer\n- Record transaction\n\n"
    "## 关联主题\n- [[billing]]\n- [[ledger]]\n\n"
    "```mermaid\ngraph TD\n    A-->B\n```\n"
)


@pytest.mark.asyncio
async def test_quality_gate_l1_only():
    from wiki.pipeline_graph import quality_gate_node

    state = {
        "pages": [_make_page("wiki/svc", GOOD_CONTENT)],
        "config": {"quality_levels": ["L1"]},
        "heal_attempts": {},
    }
    result = await quality_gate_node(state)
    scores = result.get("quality_scores", {})
    assert "wiki/svc" in scores
    score = scores["wiki/svc"]
    assert "l1_structural" in score
    assert "l2_bench" not in score


@pytest.mark.asyncio
async def test_quality_gate_l1_l2_default():
    from wiki.pipeline_graph import quality_gate_node

    state = {
        "pages": [_make_page("wiki/svc", GOOD_CONTENT)],
        "config": {},
        "heal_attempts": {},
    }
    result = await quality_gate_node(state)
    scores = result.get("quality_scores", {})
    score = scores["wiki/svc"]
    assert "l1_structural" in score
    assert "l2_bench" in score
    assert score.get("l3_llm_judge") is None


@pytest.mark.asyncio
async def test_quality_gate_l3_requires_llm_and_core():
    from wiki.pipeline_graph import quality_gate_node

    mock_llm = AsyncMock()
    mock_llm.generate.return_value = (
        '{"completeness": 0.9, "helpfulness": 0.8, "truthfulness": 0.95, "issues": []}'
    )
    state = {
        "pages": [_make_page("wiki/svc", GOOD_CONTENT)],
        "config": {
            "quality_levels": ["L1", "L2", "L3"],
            "importance_tiers": {"wiki/svc": "core"},
        },
        "heal_attempts": {},
    }
    config = {"configurable": {"llm": mock_llm}}
    result = await quality_gate_node(state, config)
    scores = result.get("quality_scores", {})
    score = scores["wiki/svc"]
    assert score.get("l3_llm_judge") is not None
    mock_llm.generate.assert_called_once()


@pytest.mark.asyncio
async def test_quality_gate_l3_skips_non_core():
    from wiki.pipeline_graph import quality_gate_node

    mock_llm = AsyncMock()
    state = {
        "pages": [_make_page("wiki/svc", GOOD_CONTENT)],
        "config": {
            "quality_levels": ["L1", "L2", "L3"],
            "importance_tiers": {"wiki/svc": "standard"},
        },
        "heal_attempts": {},
    }
    config = {"configurable": {"llm": mock_llm}}
    result = await quality_gate_node(state, config)
    scores = result.get("quality_scores", {})
    score = scores["wiki/svc"]
    assert score.get("l3_llm_judge") is None
    mock_llm.generate.assert_not_called()


@pytest.mark.asyncio
async def test_quality_gate_config_override_from_state():
    from wiki.pipeline_graph import quality_gate_node

    state = {
        "pages": [_make_page("wiki/svc", GOOD_CONTENT)],
        "config": {"quality_levels": ["L1"]},
        "heal_attempts": {},
    }
    config = {"configurable": {"quality_levels": ["L1", "L2"]}}
    result = await quality_gate_node(state, config)
    scores = result.get("quality_scores", {})
    score = scores["wiki/svc"]
    # State config takes priority over pipeline config
    assert "l2_bench" not in score
