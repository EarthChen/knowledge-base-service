"""Tests that DomainDocAgent verifies code blocks after writing."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_verify_code_blocks_called_after_write():
    """DomainDocAgent should call _verify_code_blocks after each write iteration."""
    from wiki.domain_doc_agent import DomainDocAgent

    mock_page_agent = MagicMock()
    mock_page_agent.explore = AsyncMock()
    mock_page_agent.write = AsyncMock(return_value="# Domain\n\n```python\nprint('hello')\n```\n")

    agent = DomainDocAgent.__new__(DomainDocAgent)
    agent.domain_name = "test-domain"
    agent.domain_display_name = "Test Domain"
    agent._page_agent = mock_page_agent
    agent._max_iterations = 1
    agent.iteration_history = []
    agent._output_guardrail = MagicMock()
    agent._output_guardrail.evaluate = AsyncMock(
        return_value=MagicMock(passed=True, total_score=0.9)
    )

    mock_outline = MagicMock()
    mock_outline.should_split = False
    mock_outline.topics = []
    agent._plan_topics = AsyncMock(return_value=mock_outline)

    # Patch _verify_code_blocks to track calls
    with patch.object(
        DomainDocAgent, "_verify_code_blocks",
        new_callable=AsyncMock,
        return_value="# Domain\n\n```python\nprint('hello')\n```\n",
    ) as mock_verify:
        with patch("wiki.domain_doc_agent.evaluate_quality") as mock_eval:
            mock_eval.return_value = MagicMock(
                coverage=0.99, citation_density=0.5,
                context_gap_count=0, uncovered_modules=[],
                implementation_depth=0.8,
            )
            with patch("wiki.domain_doc_agent._maybe_split") as mock_split:
                mock_split.return_value = [{"path": "/__domains__/test/overview", "content": "ok"}]
                with patch("wiki.domain_doc_agent.WorkingMemory") as mock_wm_cls:
                    mock_wm = MagicMock()
                    mock_wm._total_chars.return_value = 100
                    mock_wm.code_snippets = [{"code": "print('hello')"}]
                    mock_wm.discovered_entity_uids = set()
                    mock_wm.topic_outline = None
                    mock_wm_cls.return_value = mock_wm
                    agent._pre_fill_snippets = AsyncMock()

                    with patch("wiki.domain_doc_agent.os.environ.get", return_value="900"):
                        with patch("wiki.domain_doc_agent.time.monotonic", return_value=0):
                            with patch("core.config.get_settings") as mock_settings:
                                mock_settings.return_value = MagicMock(
                                    wiki=MagicMock(
                                        domain_agent_early_exit_quality=0.6,
                                        domain_agent_early_exit_min_chars=500,
                                        domain_agent_timeout_sec=600,
                                        use_orchestrator_template=False,
                                    )
                                )
                                pages = await agent.generate_with_iterations(
                                    module_names=["UserService"],
                                    baseline_context="test context",
                                )

        # _verify_code_blocks should have been called at least once
        assert mock_verify.called


@pytest.mark.asyncio
async def test_verify_code_blocks_method_exists():
    """DomainDocAgent should have a _verify_code_blocks method."""
    from wiki.domain_doc_agent import DomainDocAgent
    assert hasattr(DomainDocAgent, "_verify_code_blocks")
