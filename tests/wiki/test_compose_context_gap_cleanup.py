from wiki.nodes.compose import cleanup_context_gaps


def test_cleanup_context_gaps_replaces_marker():
    content = "## Overview\n\nSome text.\n\n<!-- CONTEXT_GAP: 缺少外部调用者信息 -->\n\nMore text."
    result = cleanup_context_gaps(content)
    assert "CONTEXT_GAP" not in result
    assert "Some text." in result
    assert "More text." in result


def test_cleanup_context_gaps_handles_multiple():
    content = "<!-- CONTEXT_GAP: gap1 -->\n\ntext\n\n<!-- CONTEXT_GAP: gap2 -->"
    result = cleanup_context_gaps(content)
    assert "text" in result
    assert "CONTEXT_GAP" not in result


def test_cleanup_context_gaps_no_markers():
    content = "## Clean page\n\nNo gaps here."
    result = cleanup_context_gaps(content)
    assert result == content


def test_cleanup_context_gaps_chinese_colon_variant():
    content = "text\n\n<!-- CONTEXT_GAP 已补充：补充了接口信息 -->\n\nmore"
    result = cleanup_context_gaps(content)
    assert "CONTEXT_GAP" not in result
    assert "text" in result
    assert "more" in result
