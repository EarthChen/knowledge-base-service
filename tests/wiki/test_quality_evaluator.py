from unittest.mock import AsyncMock

import pytest

from wiki.models import (
    DiagramType,
    ImportanceTier,
    PageType,
    WikiDiagram,
    WikiPage,
    WikiPageMetadata,
    WikiPageQualityScore,
)
from wiki.quality_evaluator import WikiQualityEvaluator


def test_structural_check_complete_page():
    page = WikiPage(
        path="test.md",
        title="Test",
        page_type=PageType.CLASS_DETAIL,
        content=(
            "# Test\n\n## Overview\n\nDescription.\n\n## Key components\n\nMethods.\n\n## Relationships\n\nCalls X."
        ),
        diagrams=[
            WikiDiagram(
                diagram_type=DiagramType.CLASS_DIAGRAM,
                content="classDiagram\n  A --> B",
                title="Relations",
            )
        ],
        source_locations=[],
        metadata=WikiPageMetadata(1, 1),
    )
    evaluator = WikiQualityEvaluator(llm=None)
    score = evaluator.structural_check(page)
    assert score.completeness >= 0.7
    assert not any(i in score.issues for i in ["missing_overview", "missing_components", "missing_relationships"])


def test_structural_check_empty_page():
    page = WikiPage(
        path="test.md",
        title="Test",
        page_type=PageType.CLASS_DETAIL,
        content="# Test\n\n_No content._",
        diagrams=[],
        source_locations=[],
        metadata=WikiPageMetadata(0, 0),
    )
    evaluator = WikiQualityEvaluator(llm=None)
    score = evaluator.structural_check(page)
    assert score.completeness < 0.5
    assert len(score.issues) > 0


def test_structural_check_partial():
    page = WikiPage(
        path="test.md",
        title="Test",
        page_type=PageType.CLASS_DETAIL,
        content="# Test\n\n## Overview\n\nThis is a long description that exceeds 200 characters. " + "x" * 200,
        diagrams=[],
        source_locations=[],
        metadata=WikiPageMetadata(1, 0),
    )
    evaluator = WikiQualityEvaluator(llm=None)
    score = evaluator.structural_check(page)
    assert "missing_overview" not in score.issues
    assert "content_too_short" not in score.issues
    assert "missing_components" in score.issues


@pytest.mark.asyncio
async def test_llm_judge_evaluate_parses_json():
    llm = AsyncMock()
    llm.generate = AsyncMock(
        return_value='{"completeness": 0.8, "helpfulness": 0.7, "truthfulness": 0.9, "issues": ["minor_gap"]}'
    )
    evaluator = WikiQualityEvaluator(llm=llm)
    page = WikiPage(
        path="test.md",
        title="Test",
        page_type=PageType.CLASS_DETAIL,
        content="# Test\n\nSome content.",
        diagrams=[],
        source_locations=[],
        metadata=WikiPageMetadata(1, 1),
    )
    score = await evaluator.llm_judge_evaluate(page)
    assert score.completeness == 0.8
    assert score.helpfulness == 0.7
    assert score.truthfulness == 0.9
    assert "minor_gap" in score.issues


@pytest.mark.asyncio
async def test_llm_judge_fallback_on_parse_error():
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value="not valid json")
    evaluator = WikiQualityEvaluator(llm=llm)
    page = WikiPage(
        path="test.md",
        title="Test",
        page_type=PageType.CLASS_DETAIL,
        content="# Test\n\n_Short._",
        diagrams=[],
        source_locations=[],
        metadata=WikiPageMetadata(0, 0),
    )
    score = await evaluator.llm_judge_evaluate(page)
    assert score.truthfulness == 1.0  # structural fallback


def test_aggregate_scores_with_tier_weights():
    evaluator = WikiQualityEvaluator(llm=None)
    scores = [
        WikiPageQualityScore("core.md", 0.9, 0.9, 0.9, 0.9, []),
        WikiPageQualityScore("std.md", 0.5, 0.5, 0.5, 0.5, []),
        WikiPageQualityScore("skel.md", 0.3, 0.3, 0.3, 0.3, []),
    ]
    tier_map = {
        "core.md": ImportanceTier.CORE,
        "std.md": ImportanceTier.STANDARD,
        "skel.md": ImportanceTier.SKELETON,
    }
    result = evaluator.aggregate_scores(scores, tier_map)
    assert result["overall"] > 0.6  # CORE weighted 3x
    assert result["page_count"] == 3


def test_aggregate_scores_empty():
    evaluator = WikiQualityEvaluator(llm=None)
    result = evaluator.aggregate_scores([], {})
    assert result["overall"] == 0
    assert result["page_count"] == 0
