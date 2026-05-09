import pytest
from unittest.mock import AsyncMock

from wiki.harness_evaluator import EvalResult, WikiPageEvaluator


@pytest.mark.asyncio
async def test_l3_returns_four_dimensions():
    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(
        return_value='{"completeness": 4, "accuracy": 3, "readability": 5, "structure": 4}'
    )

    evaluator = WikiPageEvaluator()
    result = await evaluator.evaluate_l3(
        "# Test Module\n\n## 概述\nThis is a test module.\n\n## 核心业务流程\nSome content here.",
        ["ModA", "ModB"],
        mock_llm,
    )
    assert isinstance(result, EvalResult)
    assert result.score > 0
    assert hasattr(result, "dimensions") or "dimensions" in (
        result.__dict__ if hasattr(result, "__dict__") else {}
    )


@pytest.mark.asyncio
async def test_l3_score_is_average_of_dimensions():
    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(
        return_value='{"completeness": 4, "accuracy": 4, "readability": 4, "structure": 4}'
    )

    evaluator = WikiPageEvaluator()
    result = await evaluator.evaluate_l3(
        "# Test\n\n## 概述\nContent.\n\n## 核心业务流程\nMore content.",
        ["ModA"],
        mock_llm,
    )
    assert abs(result.score - 4.0) < 0.1


@pytest.mark.asyncio
async def test_l3_handles_llm_error_gracefully():
    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(side_effect=Exception("LLM Error"))

    evaluator = WikiPageEvaluator()
    result = await evaluator.evaluate_l3(
        "# Test\n\nContent.",
        ["ModA"],
        mock_llm,
    )
    assert isinstance(result, EvalResult)
    assert result.score == 0.0
    assert not result.passed


@pytest.mark.asyncio
async def test_l3_handles_malformed_json():
    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value="not valid json")

    evaluator = WikiPageEvaluator()
    result = await evaluator.evaluate_l3(
        "# Test\n\nContent.",
        ["ModA"],
        mock_llm,
    )
    assert isinstance(result, EvalResult)
    assert result.score == 0.0
