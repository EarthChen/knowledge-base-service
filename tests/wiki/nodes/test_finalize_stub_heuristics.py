"""Tests for stub topic detection heuristics in finalize (T2-11)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from wiki.nodes.finalize import (
    _detect_stub_topic,
    _heading_line_ratio,
    finalize_node,
)


def _topic_page(path: str, content: str, *, lang: str = "zh") -> dict:
    return {
        "title": "Topic",
        "path": path,
        "page_type": "topic",
        "content": content,
        "content_language": lang,
        "metadata": {},
    }


def _mock_settings(**overrides: object) -> MagicMock:
    wiki = MagicMock()
    wiki.topic_min_content_chars = 1000
    wiki.topic_min_publish_chars = 500
    wiki.overview_min_content_chars = 2000
    wiki.cn_ratio_hard_min = 0.15
    wiki.topic_stub_heading_ratio_max = 0.5
    for key, value in overrides.items():
        setattr(wiki, key, value)
    return MagicMock(wiki=wiki)


def test_heading_line_ratio_mostly_headings() -> None:
    content = "\n".join(
        [
            "# Title",
            "## Section A",
            "### Sub A",
            "## Section B",
            "### Sub B",
            "One line of body.",
        ]
    )
    assert _heading_line_ratio(content) > 0.5


def test_heading_line_ratio_normal_content() -> None:
    paragraphs = "\n\n".join("这是一段完整的中文文档内容。" * 5 for _ in range(8))
    content = f"## 概述\n\n{paragraphs}\n\n## 实现细节\n\n{paragraphs}"
    assert _heading_line_ratio(content) < 0.5


def test_detect_stub_placeholder() -> None:
    content = "## 概述\n\n" + ("正常段落。" * 120) + "\n\nTODO: 待补充详细设计。"
    is_stub, reason = _detect_stub_topic(
        content,
        raw_len=len(content),
        wiki=_mock_settings(topic_min_publish_chars=100).wiki,
    )
    assert is_stub
    assert reason == "placeholder"


def test_detect_stub_heading_ratio() -> None:
    lines = ["# H1", "## H2", "### H3", "## H4", "### H5", "## H6"]
    content = "\n".join(lines) + "\n\n" + ("说明段落。" * 80)
    is_stub, reason = _detect_stub_topic(
        content,
        raw_len=len(content),
        wiki=_mock_settings(topic_min_publish_chars=100).wiki,
    )
    assert is_stub
    assert reason == "heading_ratio"


def test_detect_stub_valid_content_passes() -> None:
    body = "这是一段完整的中文文档内容，涵盖模块职责与调用关系。" * 50
    content = f"## 概述\n\n{body}\n\n## 实现\n\n{body}"
    assert len(content) >= 1500
    is_stub, reason = _detect_stub_topic(content, raw_len=len(content), wiki=_mock_settings().wiki)
    assert not is_stub
    assert reason == ""


@pytest.mark.asyncio
async def test_stub_topic_heading_ratio_rejected() -> None:
    lines = [
        "## 概述",
        "短注。",
        "## 架构设计",
        "### 子架构甲",
        "### 子架构乙",
        "## 核心流程",
        "### 流程一",
        "### 流程二",
        "## 关键实现",
    ]
    content = "\n".join(lines) + "\n\n" + ("说明段落。" * 120)
    state = {"pages": [_topic_page("/__domains__/test/_topic/heading-stub", content)]}

    with patch(
        "core.config.get_settings",
        return_value=_mock_settings(topic_min_publish_chars=100, topic_min_content_chars=100),
    ):
        with patch("wiki.nodes.finalize.log") as mock_log:
            result = await finalize_node(state)

    rejected = next(p for p in result["pages"] if p["path"] == "/__domains__/test/_topic/heading-stub")
    assert rejected.get("__rejected__") is True
    ratio_calls = [
        c
        for c in mock_log.warning.call_args_list
        if c[0][0] == "stub_topic_rejected" and c[1].get("reason") == "heading_ratio"
    ]
    assert len(ratio_calls) == 1


@pytest.mark.asyncio
async def test_stub_topic_placeholder_detected() -> None:
    body = "模块说明段落。" * 100
    content = f"## 概述\n\n{body}\n\n待补充：详细 API 列表。"
    state = {"pages": [_topic_page("/__domains__/test/_topic/placeholder-stub", content)]}

    with patch(
        "core.config.get_settings",
        return_value=_mock_settings(topic_min_publish_chars=100, topic_min_content_chars=100),
    ):
        with patch("wiki.nodes.finalize.log") as mock_log:
            result = await finalize_node(state)

    rejected = next(p for p in result["pages"] if p["path"] == "/__domains__/test/_topic/placeholder-stub")
    assert rejected.get("__rejected__") is True
    placeholder_calls = [
        c
        for c in mock_log.warning.call_args_list
        if c[0][0] == "stub_topic_rejected" and c[1].get("reason") == "placeholder"
    ]
    assert len(placeholder_calls) == 1


@pytest.mark.asyncio
async def test_stub_topic_valid_content_passes() -> None:
    body = "这是一段完整的中文文档内容。" * 120
    content = f"## 概述\n\n{body}\n\n## 架构\n\n{body}"
    state = {"pages": [_topic_page("/__domains__/test/_topic/valid-topic", content)]}

    with patch("core.config.get_settings", return_value=_mock_settings()):
        result = await finalize_node(state)

    published = next(p for p in result["pages"] if p["path"] == "/__domains__/test/_topic/valid-topic")
    assert not published.get("__rejected__")
    assert published.get("content")
