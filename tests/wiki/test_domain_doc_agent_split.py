"""Tests for fence-aware _maybe_split (SB4)."""
from __future__ import annotations

import pytest


class TestFenceAwareH2Split:
    def test_split_respects_fence(self):
        from wiki.domain_doc_agent import _fence_aware_h2_split

        content = """## Section 1

Some text.

```java
## This is NOT a heading
public class Foo {}
```

## Section 2

More text."""
        sections = _fence_aware_h2_split(content)
        assert len(sections) == 2
        assert "## Section 1" in sections[0]
        assert "## This is NOT a heading" in sections[0]  # stays in section 1
        assert "## Section 2" in sections[1]

    def test_split_without_fences_works_normally(self):
        from wiki.domain_doc_agent import _fence_aware_h2_split

        content = """## A

text a

## B

text b

## C

text c"""
        sections = _fence_aware_h2_split(content)
        assert len(sections) == 3
        assert "## A" in sections[0]
        assert "## B" in sections[1]
        assert "## C" in sections[2]

    def test_content_before_first_h2(self):
        from wiki.domain_doc_agent import _fence_aware_h2_split

        content = """# Title

Intro paragraph.

## Section 1

Content."""
        sections = _fence_aware_h2_split(content)
        assert len(sections) == 2
        assert "# Title" in sections[0]
        assert "## Section 1" in sections[1]

    def test_nested_fences(self):
        from wiki.domain_doc_agent import _fence_aware_h2_split

        content = """## Overview

```markdown
## Nested heading in markdown fence
```

## Implementation

Code here."""
        sections = _fence_aware_h2_split(content)
        assert len(sections) == 2
        assert "## Nested heading in markdown fence" in sections[0]
        assert "## Implementation" in sections[1]

    def test_unclosed_fence_keeps_rest_together(self):
        from wiki.domain_doc_agent import _fence_aware_h2_split

        content = """## Part 1

```java
class Foo {
## Not a heading
}

## Part 2

Should stay with Part 1 due to unclosed fence."""
        sections = _fence_aware_h2_split(content)
        # Since the fence never closes, ## Part 2 is inside a fence
        assert len(sections) == 1


class TestMaybeSplitFenceAware:
    def test_no_split_inside_fence(self):
        from wiki.domain_doc_agent import _maybe_split

        # Create content large enough to trigger split (> MAX_PAGE_TOKENS * 4 chars)
        large_code = "x = 1\n" * 2000
        content = f"""## Overview

Short intro.

```java
## Fake heading inside code
{large_code}
```

## Implementation

{large_code}"""
        pages = _maybe_split(content, "test-domain", "测试域")
        # The fake heading should NOT create its own page
        for page in pages:
            page_content = page.get("content", "")
            # No page should start with the fake heading
            if "## Fake heading inside code" in page_content:
                # It should also contain the opening fence
                assert "```java" in page_content
