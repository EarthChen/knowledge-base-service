from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wiki.domain_doc_agent import DomainDocAgent


@pytest.mark.asyncio
async def test_skip_shell_domain():
    """Empty module_names skips domain generation and returns empty list."""
    llm = AsyncMock()
    agent = DomainDocAgent(
        domain_name="shell-domain",
        domain_display_name="Shell Domain",
        llm=llm,
        graph_store=MagicMock(),
    )

    with patch("wiki.domain_doc_agent.log") as mock_log:
        result = await agent.generate([], "baseline context")

    assert result == []
    mock_log.info.assert_any_call("skip_shell_domain_no_modules", domain="shell-domain")
