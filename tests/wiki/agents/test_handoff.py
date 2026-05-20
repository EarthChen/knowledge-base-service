"""Tests for Handoff formalization (Layer 3)."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock


class TestHandoffConfig:
    def test_handoff_config_defaults(self):
        from wiki.agents.handoff import HandoffConfig

        config = HandoffConfig(
            target_factory=lambda deps: MagicMock(),
            tool_name="delegate",
            description="Delegate work",
        )
        assert config.max_depth == 2
        assert config.max_count == 3
        assert config.input_filter is None

    def test_handoff_config_custom_limits(self):
        from wiki.agents.handoff import HandoffConfig

        config = HandoffConfig(
            target_factory=lambda deps: MagicMock(),
            tool_name="delegate",
            description="Delegate",
            max_depth=5,
            max_count=10,
        )
        assert config.max_depth == 5
        assert config.max_count == 10


class TestHandoffResult:
    def test_handoff_result_fields(self):
        from wiki.agents.handoff import HandoffResult

        r = HandoffResult(output="# Content", metadata={"domain": "test"})
        assert r.output == "# Content"
        assert r.metadata["domain"] == "test"
        assert r.tool_calls_made == 0


class TestDelegateInput:
    def test_delegate_input_model(self):
        from wiki.agents.handoff import DelegateInput

        inp = DelegateInput(entity_names=["ModA", "ModB"], focus="core logic")
        assert inp.entity_names == ["ModA", "ModB"]
        assert inp.focus == "core logic"

    def test_delegate_input_default_focus(self):
        from wiki.agents.handoff import DelegateInput

        inp = DelegateInput(entity_names=["X"])
        assert inp.focus == ""


class TestHandoffExecutor:
    @pytest.mark.asyncio
    async def test_execute_handoff_success(self):
        from wiki.agents.handoff import HandoffConfig, HandoffResult, execute_handoff
        from wiki.agents.context import WikiDeps

        mock_agent = MagicMock()
        mock_agent.generate = AsyncMock(return_value="# Generated")

        config = HandoffConfig(
            target_factory=lambda deps: mock_agent,
            tool_name="delegate",
            description="Delegate",
            max_depth=2,
            max_count=3,
        )

        deps = WikiDeps(graph_store=MagicMock(), delegation_depth=0, delegation_count=0)
        result = await execute_handoff(
            config, deps,
            entity_names=["ModA"],
            focus="core",
        )

        assert isinstance(result, HandoffResult)
        assert result.output == "# Generated"
        mock_agent.generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_handoff_depth_exceeded(self):
        from wiki.agents.handoff import HandoffConfig, execute_handoff
        from wiki.agents.context import WikiDeps

        config = HandoffConfig(
            target_factory=lambda deps: MagicMock(),
            tool_name="delegate",
            description="Delegate",
            max_depth=2,
        )

        deps = WikiDeps(graph_store=MagicMock(), delegation_depth=2)
        result = await execute_handoff(config, deps, entity_names=["X"])
        assert "error" in result.metadata
        assert "depth" in result.metadata["error"]

    @pytest.mark.asyncio
    async def test_execute_handoff_count_exceeded(self):
        from wiki.agents.handoff import HandoffConfig, execute_handoff
        from wiki.agents.context import WikiDeps

        config = HandoffConfig(
            target_factory=lambda deps: MagicMock(),
            tool_name="delegate",
            description="Delegate",
            max_count=3,
        )

        deps = WikiDeps(graph_store=MagicMock(), delegation_count=3)
        result = await execute_handoff(config, deps, entity_names=["X"])
        assert "error" in result.metadata
        assert "count" in result.metadata["error"]

    @pytest.mark.asyncio
    async def test_execute_handoff_increments_depth(self):
        """Child agent should receive depth + 1 in its deps."""
        from wiki.agents.handoff import HandoffConfig, execute_handoff
        from wiki.agents.context import WikiDeps

        received_deps = {}

        def factory(deps):
            received_deps["deps"] = deps
            agent = MagicMock()
            agent.generate = AsyncMock(return_value="ok")
            return agent

        config = HandoffConfig(
            target_factory=factory,
            tool_name="delegate",
            description="Delegate",
        )

        deps = WikiDeps(graph_store=MagicMock(), delegation_depth=1)
        await execute_handoff(config, deps, entity_names=["X"])

        assert received_deps["deps"].delegation_depth == 2

    @pytest.mark.asyncio
    async def test_execute_handoff_error_handling(self):
        from wiki.agents.handoff import HandoffConfig, execute_handoff
        from wiki.agents.context import WikiDeps

        mock_agent = MagicMock()
        mock_agent.generate = AsyncMock(side_effect=RuntimeError("boom"))

        config = HandoffConfig(
            target_factory=lambda deps: mock_agent,
            tool_name="delegate",
            description="Delegate",
        )

        deps = WikiDeps(graph_store=MagicMock())
        result = await execute_handoff(config, deps, entity_names=["X"])
        assert result.output == ""
        assert "error" in result.metadata
