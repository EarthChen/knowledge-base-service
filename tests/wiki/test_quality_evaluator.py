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


def test_structural_check_chinese_topic_headings_pass():
    """TopicPageComposer uses Chinese section titles; structural_check must accept them."""
    long_body = "说明正文。" * 50  # > 200 chars
    page = WikiPage(
        path="topic.md",
        title="Topic",
        page_type=PageType.TOPIC,
        content=(
            "# 主题\n\n## 业务概述\n\n"
            + long_body
            + "\n\n## 核心业务流程\n\n步骤与协作。\n\n## 关联主题\n\n[[Other]]"
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
    assert not any(
        i in score.issues
        for i in ["missing_overview", "missing_components", "missing_relationships"]
    )


def test_structural_check_chinese_heading_variants():
    """Alternate Chinese labels from composer / docs still satisfy structure."""
    long_body = "x" * 220
    page = WikiPage(
        path="topic2.md",
        title="T",
        page_type=PageType.TOPIC,
        content=(
            "# T\n\n## 概述\n\n"
            + long_body
            + "\n\n## 核心服务要点\n\n细节。\n\n## 关联关系\n\n—"
        ),
        diagrams=[
            WikiDiagram(
                diagram_type=DiagramType.FLOWCHART,
                content="flowchart TD\n  A --> B",
                title="F",
            )
        ],
        source_locations=[],
        metadata=WikiPageMetadata(1, 1),
    )
    evaluator = WikiQualityEvaluator(llm=None)
    score = evaluator.structural_check(page)
    assert "missing_overview" not in score.issues
    assert "missing_components" not in score.issues
    assert "missing_relationships" not in score.issues


def test_structural_check_chinese_core_service_detail_and_related_topics():
    """P0-1: ## 核心服务详情 and ## 关联主题 must count as components / relationships."""
    long_body = "y" * 220
    page = WikiPage(
        path="topic-detail.md",
        title="T",
        page_type=PageType.TOPIC,
        content=(
            "# T\n\n## 业务概述\n\n"
            + long_body
            + "\n\n## 核心服务详情\n\n服务说明。\n\n## 关联主题\n\n[[Wiki]]"
        ),
        diagrams=[
            WikiDiagram(
                diagram_type=DiagramType.SEQUENCE_DIAGRAM,
                content="sequenceDiagram\n  A->>B: x",
                title="S",
            )
        ],
        source_locations=[],
        metadata=WikiPageMetadata(1, 1),
    )
    evaluator = WikiQualityEvaluator(llm=None)
    score = evaluator.structural_check(page)
    assert "missing_overview" not in score.issues
    assert "missing_components" not in score.issues
    assert "missing_relationships" not in score.issues


def test_structural_check_chinese_core_service_detail_and_related_topics():
    """P0-1: ## 核心服务详情 and ## 关联主题 must count as components / relationships."""
    long_body = "y" * 220
    page = WikiPage(
        path="topic-detail.md",
        title="T",
        page_type=PageType.TOPIC,
        content=(
            "# T\n\n## 业务概述\n\n"
            + long_body
            + "\n\n## 核心服务详情\n\n服务说明。\n\n## 关联主题\n\n[[Wiki]]"
        ),
        diagrams=[
            WikiDiagram(
                diagram_type=DiagramType.SEQUENCE_DIAGRAM,
                content="sequenceDiagram\n  A->>B: x",
                title="S",
            )
        ],
        source_locations=[],
        metadata=WikiPageMetadata(1, 1),
    )
    evaluator = WikiQualityEvaluator(llm=None)
    score = evaluator.structural_check(page)
    assert "missing_overview" not in score.issues
    assert "missing_components" not in score.issues
    assert "missing_relationships" not in score.issues


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
    llm.complete_json = AsyncMock(
        return_value={
            "completeness": 0.8,
            "helpfulness": 0.7,
            "truthfulness": 0.9,
            "issues": ["minor_gap"],
        },
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
    llm.complete_json = AsyncMock(side_effect=ValueError("bad json"))
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


def test_select_sample_all_core_included():
    evaluator = WikiQualityEvaluator(llm=None)
    pages = [
        WikiPage(path=f"p{i}.md", title=f"P{i}", page_type=PageType.CLASS_DETAIL,
                 content="# Test", diagrams=[], source_locations=[],
                 metadata=WikiPageMetadata(1, 1))
        for i in range(50)
    ]
    tier_map = {"p0.md": ImportanceTier.CORE, "p1.md": ImportanceTier.CORE, "p2.md": ImportanceTier.CORE}
    for i in range(3, 50):
        tier_map[f"p{i}.md"] = ImportanceTier.STANDARD
    sample = evaluator.select_sample_pages(pages, tier_map, sample_size=10)
    assert len(sample) == 10
    core_in_sample = [p for p in sample if tier_map[p.path] == ImportanceTier.CORE]
    assert len(core_in_sample) == 3


def test_identify_pages_for_heal():
    evaluator = WikiQualityEvaluator(llm=None)
    scores = [
        WikiPageQualityScore("a.md", 0.9, 0.8, 0.9, 0.87, []),
        WikiPageQualityScore("b.md", 0.3, 0.4, 0.5, 0.4, ["missing_overview", "content_too_short"]),
        WikiPageQualityScore("c.md", 0.5, 0.5, 0.6, 0.53, ["no_diagrams"]),
    ]
    to_heal = evaluator.identify_pages_for_heal(scores, min_score=0.6)
    assert "b.md" in to_heal
    assert "c.md" in to_heal
    assert "a.md" not in to_heal


def test_build_heal_prompt_includes_issues():
    evaluator = WikiQualityEvaluator(llm=None)
    score = WikiPageQualityScore("b.md", 0.3, 0.4, 0.5, 0.4, ["missing_overview", "content_too_short"])
    prompt_hint = evaluator.build_heal_prompt_hint(score)
    assert "missing_overview" in prompt_hint or "Overview" in prompt_hint
    assert "content_too_short" in prompt_hint or "Expand" in prompt_hint


def test_build_heal_prompt_no_issues():
    evaluator = WikiQualityEvaluator(llm=None)
    score = WikiPageQualityScore("a.md", 0.9, 0.9, 0.9, 0.9, [])
    assert evaluator.build_heal_prompt_hint(score) == ""
