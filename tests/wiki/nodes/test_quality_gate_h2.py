from __future__ import annotations


def test_h2_check_topic_insufficient():
    from wiki.nodes.quality_gate import _check_h2_structure

    content = "# Title\n\n## Only One Section\n\nContent"
    result = _check_h2_structure(content, "topic")
    assert result is not None
    assert "insufficient" in result.code


def test_h2_check_topic_sufficient():
    from wiki.nodes.quality_gate import _check_h2_structure

    content = "# Title\n\n## Section 1\n\nContent\n\n## Section 2\n\nMore\n\n## Section 3\n\nEnd"
    result = _check_h2_structure(content, "topic")
    assert result is None


def test_h2_check_overview_sufficient():
    from wiki.nodes.quality_gate import _check_h2_structure

    content = "# Title\n\n## Section 1\n\nContent\n\n## Section 2\n\nMore"
    result = _check_h2_structure(content, "overview")
    assert result is None


def test_h2_check_overview_insufficient():
    from wiki.nodes.quality_gate import _check_h2_structure

    content = "# Title\n\nJust a paragraph with no sections"
    result = _check_h2_structure(content, "overview")
    assert result is not None
    assert "insufficient" in result.code
