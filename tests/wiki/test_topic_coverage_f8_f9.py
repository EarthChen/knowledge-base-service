"""Tests for F8 (topic coverage threshold) and F9 (plan context + schema + wikilinks)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wiki.domain_doc_agent import (
    DomainDocAgent,
    DomainTopicOutline,
    OutlineTopicItem,
    _format_full_plan_context,
    _parse_topic_outline,
)
from wiki.llm_schemas import TopicItem
from wiki.nodes.finalize import _remove_invalid_wikilinks


def test_topic_item_schema_has_description() -> None:
    item = TopicItem(title="T", slug="t", modules=["m1"], description="desc")
    assert item.description == "desc"
    assert item.modules == ["m1"]


def test_parse_topic_outline_accepts_module_keys() -> None:
    raw = '{"should_split": true, "topics": [{"title": "A", "slug": "a", "module_keys": ["ModA"]}]}'
    outline = _parse_topic_outline(raw)
    assert outline is not None
    assert outline.topics[0].modules == ["ModA"]


def test_format_full_plan_context_marks_current() -> None:
    outline = DomainTopicOutline(
        should_split=True,
        topics=[
            OutlineTopicItem(title="Topic A", modules=["a"], description="desc a"),
            OutlineTopicItem(title="Topic B", modules=["b"], description="desc b"),
        ],
    )
    result = _format_full_plan_context(outline, outline.topics[1])
    assert "**Topic B** ← 当前撰写" in result
    assert "**Topic A**" in result
    assert result.count("← 当前撰写") == 1


def test_format_full_plan_context_includes_siblings() -> None:
    outline = DomainTopicOutline(
        should_split=True,
        topics=[
            OutlineTopicItem(title="Topic A", modules=["a"], description=""),
            OutlineTopicItem(title="Topic B", modules=["b"], description=""),
        ],
    )
    result = _format_full_plan_context(outline, outline.topics[0])
    assert "相关主题" in result
    assert "- Topic B" in result
    assert "Topic A" not in result.split("相关主题")[-1] or "- Topic A" not in result


@pytest.mark.asyncio
async def test_2_module_domain_gets_topic() -> None:
    """2-module domain with LLM decline gets force-split into topics."""
    llm = AsyncMock()
    agent = DomainDocAgent(
        domain_name="two-modules",
        domain_display_name="Two Modules",
        llm=llm,
        graph_store=MagicMock(),
    )

    module_names = ["ModA", "ModB"]
    llm_declined = DomainTopicOutline(
        should_split=False,
        topics=[OutlineTopicItem(title="All", modules=module_names, description="single topic")],
    )
    agent._plan_topics = AsyncMock(return_value=llm_declined)

    with patch("wiki.domain_doc_agent.get_settings") as mock_settings:
        mock_settings.return_value.wiki.enable_topic_pages = True
        mock_settings.return_value.wiki.topic_force_split_threshold = 10
        mock_settings.return_value.wiki.max_topics_per_domain = 4
        mock_settings.return_value.wiki.plan_topics_min_modules = 2
        mock_settings.return_value.wiki.min_overview_len_for_topics = 99999
        result = await agent.plan_topics(MagicMock(), module_names)

    assert result is not None
    assert len(result) == 2
    assert agent._topic_split_done is True


@pytest.mark.asyncio
async def test_write_with_outline_injects_full_plan() -> None:
    """Each topic write receives full plan context with sibling titles."""
    llm = AsyncMock()
    agent = DomainDocAgent(
        domain_name="plan-domain",
        domain_display_name="Plan Domain",
        llm=llm,
        graph_store=MagicMock(),
    )

    outline = DomainTopicOutline(
        should_split=True,
        topics=[
            OutlineTopicItem(title="Topic A", modules=["ModA"], description="desc a", slug="a"),
            OutlineTopicItem(title="Topic B", modules=["ModB"], description="desc b", slug="b"),
        ],
    )
    captured_contexts: list[str] = []

    async def capture_write(domain: str, context: str, memory: object, **kwargs: object) -> str:
        captured_contexts.append(context)
        return "## 概述\n\n内容。" * 50

    agent._page_agent = MagicMock()
    agent._page_agent.write = AsyncMock(side_effect=capture_write)
    agent._verify_code_blocks = AsyncMock(side_effect=lambda c, m: c)
    agent.run_guardrails = AsyncMock(return_value=None)

    memory = MagicMock()
    with patch("wiki.domain_doc_agent.get_settings") as mock_settings:
        mock_settings.return_value.wiki.enable_topic_pages = True
        await agent._write_with_outline(outline, "baseline", memory, ["ModA", "ModB"])

    plan_contexts = [c for c in captured_contexts if "域主题规划" in c]
    assert len(plan_contexts) == 2
    for ctx in plan_contexts:
        assert "Topic A" in ctx
        assert "Topic B" in ctx
        assert "相关主题" in ctx


@pytest.mark.asyncio
async def test_quality_gate_warns_domain_overview_without_topics() -> None:
    from wiki.nodes.quality_gate import quality_gate_node

    state = {
        "pages": [
            {
                "path": "/__domains__/solo/_overview",
                "title": "Solo",
                "page_type": "domain_overview",
                "business_domain": "solo",
                "content": "## 概述\n\n" + ("内容。" * 200),
                "content_language": "zh",
            },
        ],
    }
    with patch("wiki.nodes.quality_gate.get_settings") as mock_settings:
        mock_settings.return_value.wiki.heal_l2_threshold = 0.0
        mock_settings.return_value.wiki.heal_on_l3_failure = False
        mock_settings.return_value.wiki.heal_l3_threshold = 0.5
        mock_settings.return_value.wiki.overview_min_content_chars = 2000
        mock_settings.return_value.wiki.topic_min_content_chars = 500
        mock_settings.return_value.wiki.language_guardrail_cn_ratio = 0.15
        with patch("wiki.nodes.quality_gate.log") as mock_log:
            await quality_gate_node(state)
            mock_log.warning.assert_any_call(
                "quality_gate_domain_no_topics",
                domain="solo",
                reason="domain has overview but no topic pages",
            )


def test_finalize_removes_variant_wikilinks() -> None:
    content = "参见 [[Domain - Part 5]] 与 [[Domain - Part 1]] 及 [[Part 2]]。"
    valid = {
        "domain - part 1",
        "domain - part 2",
        "domain - part 3",
        "domain - part 4",
    }
    result = _remove_invalid_wikilinks(content, valid)
    assert "[[Domain - Part 5]]" not in result
    assert "Domain - Part 5" in result
    assert "[[Domain - Part 1]]" in result
    assert "[[Part 2]]" in result
