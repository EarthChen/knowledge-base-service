from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from wiki.agents.context import WikiDeps
from wiki.agents.handoff import HandoffConfig, execute_handoff


@pytest.mark.asyncio
async def test_delegation_count_increments():
    """delegation_count should increment, not reset to 0 (D-06)."""
    captured_deps = {}

    def factory(deps):
        captured_deps["child"] = deps
        child_agent = MagicMock()
        child_agent.generate = AsyncMock(return_value="ok")
        return child_agent

    config = HandoffConfig(
        target_factory=factory,
        tool_name="delegate",
        description="Delegate",
    )
    parent_deps = WikiDeps(
        graph_store=MagicMock(),
        delegation_depth=0,
        delegation_count=2,
    )

    result = await execute_handoff(config, parent_deps, entity_names=["ModA"])

    assert result.output == "ok"
    assert captured_deps["child"].delegation_count == 3
    assert captured_deps["child"].delegation_depth == 1
