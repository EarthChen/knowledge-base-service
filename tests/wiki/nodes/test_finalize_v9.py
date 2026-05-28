"""Tests for V9 Batch C finalize integration (F10)."""

from __future__ import annotations

from wiki.nodes.finalize import _sanitize_published_content


def test_finalize_strips_h1():
    content = "# 家族系统\n## 概述\n内容"
    result = _sanitize_published_content(content)
    assert not result.startswith("# 家族系统")
    assert result.startswith("## 概述")


def test_finalize_strips_repeated_blockquotes():
    quote = "> 本模块采用事件驱动架构实现异步处理。"
    content = f"{quote}\n{quote}\n{quote}\n\n## 概述\n内容"
    result = _sanitize_published_content(content)
    assert result.count("> 本模块采用事件驱动架构实现异步处理。") == 1
    assert "## 概述" in result


def test_finalize_dedup_code_fences():
    block = "```java\npublic class Foo {}\n```"
    content = f"## 概述\n\n{block}\n\n更多内容。\n\n{block}\n\n{block}"
    result = _sanitize_published_content(content)
    assert result.count("public class Foo") == 1
    assert "更多内容" in result


def test_finalize_strips_english_self_reflection():
    content = "> **Note**: The headings in this document are placeholders.\n\n## Overview\n\nActual content."
    result = _sanitize_published_content(content)
    assert "**Note**: The headings" not in result
    assert "## Overview" in result
    assert "Actual content." in result


def test_finalize_integration_all_v9():
    block = "```java\npublic class Foo {}\n```"
    quote = "> 本模块采用事件驱动架构实现异步处理。"
    content = (
        f"# 泄漏标题\n"
        f"{quote}\n{quote}\n"
        f"> **Note**: The headings in this document are placeholders.\n\n"
        f"## 概述\n\n{block}\n\n{block}\n\n"
        f"## 章节导航\n\n应删除的元节。\n\n"
        f"## 核心流程\n\n保留内容。"
    )
    result = _sanitize_published_content(content)
    assert not result.startswith("# 泄漏标题")
    assert result.count("> 本模块采用事件驱动架构实现异步处理。") == 1
    assert "**Note**: The headings" not in result
    assert result.count("public class Foo") == 1
    assert "章节导航" not in result
    assert "应删除的元节" not in result
    assert "保留内容" in result
