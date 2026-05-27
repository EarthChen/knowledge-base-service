"""Tests for output guardrail checks."""

import pytest

from wiki.output_guardrail import (
    CoverageCheck,
    FormatCheck,
    LengthCheck,
    OutputGuardrailChain,
    SensitiveContentCheck,
)


class TestFormatCheck:
    @pytest.mark.asyncio
    async def test_passes_valid_markdown(self):
        content = "# Title\n\n## Overview\n\nSome content here.\n\n## Details\n\nMore content."
        result = await FormatCheck().check(content, {})
        assert result.passed

    @pytest.mark.asyncio
    async def test_fails_without_heading(self):
        content = "Just some text without any heading structure."
        result = await FormatCheck().check(content, {})
        assert not result.passed

    @pytest.mark.asyncio
    async def test_detects_thinking_leak(self):
        content = "# Title\n\n<think>internal reasoning</think>\n\n## Section\n\nContent."
        result = await FormatCheck().check(content, {})
        assert not result.passed
        assert any("think" in issue.lower() for issue in result.issues)


class TestCoverageCheck:
    @pytest.mark.asyncio
    async def test_passes_full_coverage(self):
        content = "# Auth\n\nThe AuthService handles login. The UserRepo stores data."
        ctx = {"module_names": ["AuthService", "UserRepo"]}
        result = await CoverageCheck().check(content, ctx)
        assert result.passed
        assert result.score >= 0.9

    @pytest.mark.asyncio
    async def test_fails_low_coverage(self):
        content = "# Auth\n\nSome generic description."
        ctx = {"module_names": ["AuthService", "UserRepo", "TokenManager"]}
        result = await CoverageCheck().check(content, ctx)
        assert not result.passed

    @pytest.mark.asyncio
    async def test_empty_modules_passes(self):
        content = "# Page\n\nContent."
        ctx = {"module_names": []}
        result = await CoverageCheck().check(content, ctx)
        assert result.passed


class TestLengthCheck:
    @pytest.mark.asyncio
    async def test_passes_normal_length(self):
        content = "# Title\n\n" + "word " * 200
        result = await LengthCheck().check(content, {})
        assert result.passed

    @pytest.mark.asyncio
    async def test_fails_too_short(self):
        content = "# Title\n\nToo short."
        result = await LengthCheck().check(content, {})
        assert not result.passed

    @pytest.mark.asyncio
    async def test_fails_too_long(self):
        content = "# Title\n\n" + "word " * 20000
        result = await LengthCheck().check(content, {})
        assert not result.passed


class TestSensitiveContentCheck:
    @pytest.mark.asyncio
    async def test_detects_internal_url(self):
        content = "# API\n\nConnect at http://192.168.1.10:8080/api for details."
        result = await SensitiveContentCheck().check(content, {})
        assert not result.passed
        assert result.score == 0.0

    @pytest.mark.asyncio
    async def test_detects_credentials(self):
        content = "# Config\n\nSet api_key=sk-live-abc123 in production."
        result = await SensitiveContentCheck().check(content, {})
        assert not result.passed
        assert "Sensitive patterns" in result.issues[0]

    @pytest.mark.asyncio
    async def test_passes_normal_content(self):
        content = "# Overview\n\nSee https://example.com/docs for public API reference."
        result = await SensitiveContentCheck().check(content, {})
        assert result.passed
        assert result.score == 1.0


class TestOutputGuardrailChain:
    @pytest.mark.asyncio
    async def test_all_pass(self):
        chain = OutputGuardrailChain([FormatCheck(), LengthCheck()])
        content = "# Title\n\n## Overview\n\n" + "Good content. " * 50
        result = await chain.evaluate(content, {})
        assert result.passed

    @pytest.mark.asyncio
    async def test_one_fails(self):
        chain = OutputGuardrailChain([FormatCheck(), LengthCheck()])
        content = "no heading, too short"
        result = await chain.evaluate(content, {})
        assert not result.passed
        assert len(result.details) == 2

    @pytest.mark.asyncio
    async def test_sensitive_content_check_in_chain(self):
        chain = OutputGuardrailChain([
            FormatCheck(),
            SensitiveContentCheck(),
            LengthCheck(),
        ])
        content = "# API\n\nConnect at http://192.168.1.10:8080/api.\n\n" + "detail " * 200
        result = await chain.evaluate(content, {})
        assert not result.passed
        assert "sensitive_content" in result.details
        assert not result.details["sensitive_content"].passed
        assert result.details["format"].passed
