"""Tests for terminal fence repair in finalize."""
from __future__ import annotations

import re


def test_terminal_repair_closes_fence_after_h2_strip():
    """If strip_unauthorized_sections removes a closing fence, terminal repair fixes it."""
    from wiki.content_guards import repair_unclosed_code_blocks

    content_after_strip = "## 概述\n\n正文内容\n\n```java\ncode here\n\n## 模块列表\n\n更多内容"
    # This has 1 opening ``` but no closing — odd fence count
    fences = re.findall(r"```", content_after_strip)
    assert len(fences) % 2 != 0  # Pre-condition: odd fences

    repaired = repair_unclosed_code_blocks(content_after_strip)
    fences_after = re.findall(r"```", repaired)
    assert len(fences_after) % 2 == 0  # Post-condition: even fences


def test_terminal_repair_no_change_when_balanced():
    from wiki.content_guards import repair_unclosed_code_blocks

    content = "## 概述\n\n```java\ncode\n```\n\n正常内容"
    result = repair_unclosed_code_blocks(content)
    assert result == content  # No change needed
