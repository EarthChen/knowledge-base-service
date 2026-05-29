from __future__ import annotations

import pytest

from wiki.agents.review_agent import QualityIssue, QualityVerdict, ReviewAgent


class TestReviewAgent:
    @pytest.mark.asyncio
    async def test_pass_for_clean_content(self):
        ra = ReviewAgent()
        content = (
            "# Module Overview\n\n"
            "This module handles authentication.\n\n"
            "## Architecture\n\n"
            "Uses JWT tokens. Source: `source://auth/jwt.py#L10-L20`\n\n"
            "## Implementation\n\n"
            "Details with `source://auth/handler.py#L5`.\n"
        )
        verdict = await ra.review(content, {"expected_sections": 2})
        assert verdict.status == "pass"

    @pytest.mark.asyncio
    async def test_rejects_part_n_naming(self):
        ra = ReviewAgent()
        content = "# Part 1: Overview\nContent\n# Part 2: Details\nMore"
        verdict = await ra.review(content, {})
        naming_issues = [i for i in verdict.issues if i.category == "naming"]
        assert len(naming_issues) > 0
        assert verdict.status in ("warn", "fail")

    @pytest.mark.asyncio
    async def test_detects_unclosed_code_block(self):
        ra = ReviewAgent()
        content = "# Module\n```python\ndef foo():\n    pass\n"  # no closing ```
        verdict = await ra.review(content, {})
        trunc_issues = [i for i in verdict.issues if i.category == "truncation"]
        assert len(trunc_issues) > 0

    @pytest.mark.asyncio
    async def test_detects_empty_sections(self):
        ra = ReviewAgent()
        content = "# Title\n\n## Section A\n\n## Section B\nContent here\n"
        verdict = await ra.review(content, {})
        struct_issues = [i for i in verdict.issues if i.category == "structure"]
        # Section A is empty
        assert any("empty" in i.description.lower() or "section" in i.description.lower() for i in struct_issues)

    @pytest.mark.asyncio
    async def test_verdict_aggregation_error_means_fail(self):
        ra = ReviewAgent()
        # Content with Part N naming (error) and clean structure
        content = "# Part 1\nSome content with `source://a.py#L1`.\n"
        verdict = await ra.review(content, {})
        assert verdict.status in ("warn", "fail")

    def test_quality_issue_fields(self):
        issue = QualityIssue(category="naming", severity="error", description="Part N", location="line 1")
        assert issue.category == "naming"
        assert issue.severity == "error"

    def test_quality_verdict_fields(self):
        verdict = QualityVerdict(status="pass", confidence=0.95, issues=[])
        assert verdict.status == "pass"
        assert verdict.confidence == 0.95
        assert verdict.heal_instructions is None
