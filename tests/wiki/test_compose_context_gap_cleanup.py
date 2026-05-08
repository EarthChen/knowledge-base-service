from wiki.nodes.compose import cleanup_context_gaps


def test_cleanup_context_gaps_replaces_marker():
    content = "## Overview\n\nSome text.\n\n<!-- CONTEXT_GAP: 缺少外部调用者信息 -->\n\nMore text."
    result = cleanup_context_gaps(content)
    assert "CONTEXT_GAP" not in result
    assert "缺少外部调用者信息" in result
    assert "> ℹ️" in result


def test_cleanup_context_gaps_handles_multiple():
    content = "<!-- CONTEXT_GAP: gap1 -->\n\ntext\n\n<!-- CONTEXT_GAP: gap2 -->"
    result = cleanup_context_gaps(content)
    assert result.count("ℹ️") == 2
    assert "CONTEXT_GAP" not in result


def test_cleanup_context_gaps_no_markers():
    content = "## Clean page\n\nNo gaps here."
    result = cleanup_context_gaps(content)
    assert result == content
