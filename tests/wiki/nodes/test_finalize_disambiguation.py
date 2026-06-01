from __future__ import annotations


def test_extract_first_h2_theme():
    from wiki.nodes.finalize import _extract_first_h2_theme

    page = {"content": "# Title\n\n## 排名计算\n\nContent here\n\n## 总结\n\nEnd"}
    result = _extract_first_h2_theme(page)
    assert result == "排名计算"


def test_extract_first_h2_theme_skips_generic():
    from wiki.nodes.finalize import _extract_first_h2_theme

    page = {"content": "# Title\n\n## 概述\n\nContent\n\n## 核心逻辑\n\nDetails"}
    result = _extract_first_h2_theme(page)
    assert result == "核心逻辑"


def test_extract_first_h2_theme_empty():
    from wiki.nodes.finalize import _extract_first_h2_theme

    page = {"content": "# Title\n\nJust text, no H2"}
    result = _extract_first_h2_theme(page)
    assert result == ""


def test_extract_first_h2_theme_all_generic():
    from wiki.nodes.finalize import _extract_first_h2_theme

    page = {"content": "# Title\n\n## 概述\n\n## 总结\n\n"}
    result = _extract_first_h2_theme(page)
    assert result == ""
