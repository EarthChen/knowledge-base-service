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
from wiki.harness_evaluator import WikiPageEvaluator
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


def test_structural_check_agent_headings_pass():
    """Agent prompt output uses ## 关键实现 / ## 依赖关系; structural_check must accept."""
    long_body = "详细说明。" * 50  # > 200 chars
    page = WikiPage(
        path="/__domains__/TestDomain/_overview",
        title="TestDomain",
        page_type=PageType.DOMAIN_OVERVIEW,
        content=(
            "# TestDomain\n\n## 概述\n\n" + long_body
            + "\n\n## 关键实现\n\nread_code 获取的核心代码。"
            + "\n\n## 依赖关系\n\n跨域调用关系。"
        ),
        diagrams=[],
        source_locations=[],
        metadata=WikiPageMetadata(1, 1),
    )
    evaluator = WikiQualityEvaluator(llm=None)
    score = evaluator.structural_check(page)
    assert "missing_components" not in score.issues, f"Unexpected issues: {score.issues}"
    assert "missing_relationships" not in score.issues, f"Unexpected issues: {score.issues}"


def test_structural_check_mermaid_in_content_counts_as_diagram():
    """Agent embeds mermaid in content body; structural_check should not penalize no_diagrams."""
    long_body = "详细说明。" * 50
    page = WikiPage(
        path="test_mermaid.md",
        title="Test",
        page_type=PageType.DOMAIN_OVERVIEW,
        content=(
            "# Test\n\n## 概述\n\n" + long_body
            + "\n\n## 核心服务要点\n\n要点。"
            + "\n\n## 关联主题\n\n[[Other]]"
            + "\n\n```mermaid\nflowchart TD\n  A --> B\n```"
        ),
        diagrams=[],  # empty — diagrams are in content
        source_locations=[],
        metadata=WikiPageMetadata(1, 1),
    )
    evaluator = WikiQualityEvaluator(llm=None)
    score = evaluator.structural_check(page)
    assert "no_diagrams" not in score.issues, f"Unexpected issues: {score.issues}"


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
    llm.generate = AsyncMock(
        return_value='{"completeness": 4, "accuracy": 3, "readability": 5, "structure": 2}',
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
    # Normalized from 1–5: (x - 1) / 4
    assert score.completeness == 0.75  # (4-1)/4
    assert score.truthfulness == 0.5  # accuracy (3-1)/4
    assert score.helpfulness == 0.625  # average of readability 1.0 and structure 0.25
    assert score.overall == 0.625  # mean 1–5 = 3.5 -> (3.5-1)/4
    assert score.l3_dimensions == {
        "completeness": 4.0,
        "accuracy": 3.0,
        "readability": 5.0,
        "structure": 2.0,
    }


@pytest.mark.asyncio
async def test_llm_judge_evaluate_matches_evaluate_l3_dimensions():
    """WikiQualityEvaluator.llm_judge_evaluate must use the same L3 judge as WikiPageEvaluator."""
    raw = '{"completeness": 2, "accuracy": 5, "readability": 3, "structure": 4}'
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value=raw)
    page = WikiPage(
        path="p.md",
        title="MyMod",
        page_type=PageType.MODULE_OVERVIEW,
        content="# Doc\n\n## Overview\n\n" + "body " * 80,
        diagrams=[],
        source_locations=[],
        metadata=WikiPageMetadata(1, 1),
    )
    harness = WikiPageEvaluator()
    l3 = await harness.evaluate_l3(page.content, [page.title], llm, model=None)
    llm.generate.reset_mock()
    llm.generate = AsyncMock(return_value=raw)
    score = await WikiQualityEvaluator(llm=llm).llm_judge_evaluate(page)

    assert l3.dimensions == score.l3_dimensions
    avg_15 = sum(l3.dimensions.values()) / 4.0
    assert score.overall == round((avg_15 - 1.0) / 4.0, 3)


@pytest.mark.asyncio
async def test_llm_judge_fallback_on_parse_error():
    llm = AsyncMock()
    llm.generate = AsyncMock(side_effect=ValueError("bad json"))
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
