from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestGuardrailContextKeys:
    @pytest.mark.asyncio
    async def test_run_guardrails_passes_target_language(self):
        """run_guardrails passes target_language (not content_language) to chain."""
        from wiki.domain_doc_agent import DomainDocAgent

        agent = DomainDocAgent.__new__(DomainDocAgent)
        agent.domain_name = "test"
        agent.content_language = "简体中文"
        mock_chain = AsyncMock()
        mock_chain.evaluate = AsyncMock(return_value=MagicMock(passed=True, details={}, total_score=1.0))
        agent._output_guardrail = mock_chain

        with patch("wiki.domain_doc_agent.get_settings") as mock_settings:
            mock_settings.return_value.wiki.language_guardrail_cn_ratio = 0.4
            await agent.run_guardrails("content", 0, {"module_names": ["m1"]})

        call_ctx = mock_chain.evaluate.call_args[0][1]
        assert "target_language" in call_ctx
        assert call_ctx["target_language"] == "简体中文"
        assert "cn_ratio_threshold" in call_ctx
        assert "content_language" not in call_ctx

    @pytest.mark.asyncio
    async def test_run_guardrails_returns_result_when_should_heal(self):
        """Failed guardrail with should_heal=True returns result for caller heal path."""
        from wiki.domain_doc_agent import DomainDocAgent
        from wiki.output_guardrail import CheckResult, GuardrailResult

        agent = DomainDocAgent.__new__(DomainDocAgent)
        agent.domain_name = "test"
        agent.content_language = "简体中文"
        agent._term_glossary = {"API": "接口"}

        lang_fail = CheckResult(
            name="language_consistency",
            passed=False,
            score=0.1,
            issues=["CN ratio below threshold"],
            should_heal=True,
        )
        guard_result = GuardrailResult(passed=False, details={"language_consistency": lang_fail})

        mock_chain = AsyncMock()
        mock_chain.evaluate = AsyncMock(return_value=guard_result)
        agent._output_guardrail = mock_chain

        with patch("wiki.domain_doc_agent.get_settings") as mock_settings:
            mock_settings.return_value.wiki.language_guardrail_cn_ratio = 0.4
            with patch("wiki.output_guardrail.TermConsistencyCheck") as mock_term_cls:
                result = await agent.run_guardrails(
                    "content",
                    1,
                    {"module_names": [], "page_type": "topic"},
                )

        assert result is guard_result
        mock_term_cls.assert_not_called()
