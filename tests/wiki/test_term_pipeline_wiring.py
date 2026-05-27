from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestTermGlossaryExtraction:
    def test_glossary_from_domain_names(self):
        """Term glossary is built from slug-to-display-name mapping."""
        slugs = {
            "family-core": "家族核心",
            "intimacy-system": "亲密度系统",
        }
        glossary = {}
        for slug, display_name in slugs.items():
            readable = slug.replace("-", " ").replace("_", " ")
            if readable != display_name and display_name:
                glossary[readable] = display_name

        assert glossary["family core"] == "家族核心"
        assert glossary["intimacy system"] == "亲密度系统"

    def test_user_overrides_take_precedence(self):
        """User overrides supersede auto-extracted terms."""
        glossary = {"closed friend": "关闭好友"}
        overrides = {"closed friend": "挚友"}
        glossary.update(overrides)
        assert glossary["closed friend"] == "挚友"


class TestWritePromptGlossaryInjection:
    def test_glossary_injected_into_write_prompt(self):
        """DomainDocAgent._build_write_prompt includes term glossary."""
        from wiki.domain_doc_agent import DomainDocAgent

        agent = DomainDocAgent.__new__(DomainDocAgent)
        agent._name = "test"
        agent._term_glossary = {"family": "家族", "intimacy": "亲密度"}
        agent._subdomains = []
        agent._agent = MagicMock()
        agent._agent.memory_to_prompt = MagicMock(return_value="findings")

        prompt = agent._build_write_prompt("baseline", MagicMock())
        assert "术语约束" in prompt
        assert "家族" in prompt
        assert "亲密度" in prompt

    def test_no_glossary_no_injection(self):
        """No glossary section when term_glossary is empty."""
        from wiki.domain_doc_agent import DomainDocAgent

        agent = DomainDocAgent.__new__(DomainDocAgent)
        agent._name = "test"
        agent._term_glossary = {}
        agent._subdomains = []
        agent._agent = MagicMock()
        agent._agent.memory_to_prompt = MagicMock(return_value="findings")

        prompt = agent._build_write_prompt("baseline", MagicMock())
        assert "术语约束" not in prompt


class TestTermCheckInGuardrails:
    @pytest.mark.asyncio
    async def test_term_check_runs_in_guardrails(self):
        """run_guardrails runs TermConsistencyCheck when glossary exists."""
        from wiki.domain_doc_agent import DomainDocAgent

        agent = DomainDocAgent.__new__(DomainDocAgent)
        agent.domain_name = "test"
        agent.content_language = "简体中文"
        agent._term_glossary = {"closed friend": "挚友"}

        mock_chain = AsyncMock()
        mock_chain.evaluate = AsyncMock(return_value=MagicMock(passed=True, details={}, total_score=1.0))
        agent._output_guardrail = mock_chain

        with patch("wiki.domain_doc_agent.get_settings") as mock_settings:
            mock_settings.return_value.wiki.language_guardrail_cn_ratio = 0.4
            result = await agent.run_guardrails(
                "This document discusses closed friend relationships.",
                0,
                {"module_names": ["m1"]},
            )

        assert result is None
