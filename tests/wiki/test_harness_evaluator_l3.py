import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_quality_gate_uses_harness_evaluator_l3():
    """quality_gate_node should use WikiPageEvaluator.evaluate_l3 for L3 scoring."""
    from wiki.nodes.quality_gate import quality_gate_node

    state = {
        "pages": [
            {
                "path": "core-auth",
                "title": "Auth Module",
                "content": "# Auth Module\n\n## 概述\nHandles authentication for the platform, including session lifecycle and credential validation for all services.\n\n## 核心业务流程\nLogin flow via JWT tokens.\n\n## 关联关系\nRelated modules.\n\n## 关键实现\n```python\ndef login(): pass\n```",
                "page_type": "module_overview",
                "diagrams": [],
                "source_locations": [],
                "method_locations": [],
                "metadata": {"node_count": 1, "edge_count": 0, "generation_mode": "structure"},
            }
        ],
        "config": {"importance_tiers": {"core-auth": "core"}, "quality_levels": ["L1", "L2", "L3"]},
        "modules": {},
        "heal_attempts": {},
    }

    mock_llm = AsyncMock()

    with patch("wiki.nodes.quality_gate.WikiPageEvaluator") as MockEval:
        from wiki.harness_evaluator import EvalResult
        mock_eval_instance = MagicMock()
        mock_eval_instance.evaluate_l3 = AsyncMock(return_value=EvalResult(
            score=3.5,
            passed=True,
            dimensions={"completeness": 4.0, "accuracy": 3.0, "readability": 4.0, "structure": 3.0},
        ))
        MockEval.return_value = mock_eval_instance

        config = {"configurable": {"llm": mock_llm}}
        result = await quality_gate_node(state, config)

    scores = result.get("quality_scores", {})
    assert "core-auth" in scores
    l3_score = scores["core-auth"].get("l3_llm_judge")
    assert l3_score is not None
    assert 0.0 <= l3_score <= 1.0
