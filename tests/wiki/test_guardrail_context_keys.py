from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


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
