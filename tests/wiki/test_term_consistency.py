from __future__ import annotations

import pytest


class TestBuildTermGlossaryPrompt:
    def test_builds_glossary_section(self):
        """Glossary dict produces formatted prompt section."""
        from wiki.agent_prompts import build_term_glossary_prompt

        glossary = {"closed-friend": "挚友", "family": "家族", "intimacy": "亲密度"}
        result = build_term_glossary_prompt(glossary)
        assert "挚友" in result
        assert "家族" in result
        assert "亲密度" in result
        assert "术语约束" in result

    def test_empty_glossary_returns_empty(self):
        """Empty glossary produces empty string."""
        from wiki.agent_prompts import build_term_glossary_prompt

        result = build_term_glossary_prompt({})
        assert result == ""


class TestTermConsistencyCheck:
    @pytest.mark.asyncio
    async def test_detects_mismatch(self):
        """Detects when English term appears without Chinese equivalent."""
        from wiki.output_guardrail import TermConsistencyCheck

        check = TermConsistencyCheck()
        content = "这是一篇关于 closed friend 关系管理的文档。"
        glossary = {"closed-friend": "挚友", "closed friend": "挚友"}
        result = await check.evaluate(content, {"term_glossary": glossary})
        assert result.has_violations

    @pytest.mark.asyncio
    async def test_passes_when_consistent(self):
        """No violation when Chinese term is used correctly."""
        from wiki.output_guardrail import TermConsistencyCheck

        check = TermConsistencyCheck()
        content = "这是一篇关于挚友关系管理的文档。closed friend 对应的中文是挚友。"
        glossary = {"closed friend": "挚友"}
        result = await check.evaluate(content, {"term_glossary": glossary})
        assert not result.has_violations

    @pytest.mark.asyncio
    async def test_empty_glossary_passes(self):
        """Empty glossary always passes."""
        from wiki.output_guardrail import TermConsistencyCheck

        check = TermConsistencyCheck()
        content = "任意内容"
        result = await check.evaluate(content, {"term_glossary": {}})
        assert not result.has_violations


class TestTermOverrideConfig:
    def test_term_overrides_in_config(self):
        """term_overrides field exists in AppWikiFlags."""
        from core.config import AppWikiFlags

        flags = AppWikiFlags()
        assert hasattr(flags, "term_overrides")
        assert isinstance(flags.term_overrides, dict)
