from __future__ import annotations

import pytest


class TestHeartbeatInAgentLoop:
    def test_loop_config_has_heartbeat_field(self):
        from wiki.agents.runner import LoopConfig

        config = LoopConfig()
        assert hasattr(config, "heartbeat"), "LoopConfig must have heartbeat field"
        assert config.heartbeat is None

    def test_compose_node_accepts_runtime(self):
        import inspect

        from wiki.nodes.domain_compose import compose_domain_agents_node

        sig = inspect.signature(compose_domain_agents_node)
        param_names = [p.name for p in sig.parameters.values()]
        assert "runtime" in param_names

    @pytest.mark.asyncio
    async def test_heartbeat_called_during_agent_loop(self):
        """Verify heartbeat is called during LLM + tool interactions."""
        from unittest.mock import AsyncMock, MagicMock

        from wiki.agents.runner import LoopConfig, run_agent_loop

        calls: list[int] = []

        def fake_heartbeat() -> None:
            calls.append(1)

        agent = MagicMock()
        agent._llm = AsyncMock()
        agent._llm.complete_with_tools = AsyncMock(
            return_value={"content": "done", "tool_calls": None},
        )
        agent._tool_registry = MagicMock()
        agent._tool_registry.has_tools = MagicMock(return_value=True)
        agent._tool_registry.get_tools_for_round = MagicMock(
            return_value=[{"function": {"name": "test"}}],
        )

        config = LoopConfig(max_rounds=1, heartbeat=fake_heartbeat)
        memory = MagicMock()

        try:
            await run_agent_loop(agent, "system", "user", memory, config=config)
        except Exception:
            pass  # may fail due to mocking, that's OK

        assert len(calls) >= 1, f"heartbeat should be called at least once, got {len(calls)} calls"


class TestMakeErrorPlaceholder:
    """Tests for _make_error_placeholder error message formatting."""

    def test_timeout_error_has_non_empty_message(self):
        from wiki.nodes.domain_compose import _make_error_placeholder

        domain = {"name": "test-domain", "display_name": "测试域", "modules": ["ModA", "ModB"]}
        error = TimeoutError()

        result = _make_error_placeholder(domain, error)

        assert "TimeoutError" in result["content"]
        assert result["metadata"]["generation_mode"] == "agent_error"
        assert result["metadata"].get("error_type") == "TimeoutError"

    def test_regular_error_preserves_message(self):
        from wiki.nodes.domain_compose import _make_error_placeholder

        domain = {"name": "x", "display_name": "X", "modules": []}
        error = RuntimeError("LLM rate limit exceeded")

        result = _make_error_placeholder(domain, error)

        assert "LLM rate limit exceeded" in result["content"]
        assert result["metadata"]["error_type"] == "RuntimeError"

    def test_error_placeholder_includes_modules_list(self):
        from wiki.nodes.domain_compose import _make_error_placeholder

        domain = {"name": "family-ecosystem", "display_name": "家族生态", "modules": ["FamilyA", "FamilyB", "FamilyC"]}
        error = TimeoutError()

        result = _make_error_placeholder(domain, error)

        assert "- FamilyA" in result["content"]
        assert "- FamilyB" in result["content"]
        assert "- FamilyC" in result["content"]


class TestComposeNoWaitFor:
    """Verify compose node no longer uses asyncio.wait_for."""

    def test_domain_compose_source_no_wait_for(self):
        """domain_compose.py must not contain asyncio.wait_for in the compose function."""
        import ast
        from pathlib import Path

        source = Path("wiki/nodes/domain_compose.py").read_text()
        tree = ast.parse(source)

        # Find the compose_domain_agents_node function
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "compose_domain_agents_node":
                body_source = ast.get_source_segment(source, node)
                assert "wait_for" not in body_source, (
                    "compose_domain_agents_node should not use asyncio.wait_for; "
                    "timeout is managed by LangGraph node-level TimeoutPolicy"
                )
                break


class TestComposeDomainAgentsRetryPolicy:
    """Verify compose_domain_agents node retries on LangGraph idle timeout."""

    def test_pipeline_graph_retry_on_includes_node_timeout_error(self):
        from pathlib import Path

        source = Path("wiki/pipeline_graph.py").read_text()
        assert "NodeTimeoutError" in source
        assert "retry_on=(NodeTimeoutError, TimeoutError)" in source

    def test_node_timeout_error_not_subclass_of_builtin_timeout(self):
        try:
            from langgraph.errors import NodeTimeoutError
        except ImportError:
            return

        assert not issubclass(NodeTimeoutError, TimeoutError)


class TestWithProgressForwardsRuntime:
    def test_with_progress_forwards_runtime_when_inner_accepts_it(self):
        import asyncio

        from wiki.pipeline_graph import _with_progress

        received = {}

        async def _fake_node(state, config=None, *, runtime=None):
            received["runtime"] = runtime
            return {}

        wrapper = _with_progress("finalize", _fake_node)

        class FakeRuntime:
            pass

        asyncio.run(wrapper({"node_statuses": {}}, None, runtime=FakeRuntime()))
        assert received.get("runtime") is not None, "runtime must be forwarded"

    def test_with_progress_works_without_runtime(self):
        import asyncio

        from wiki.pipeline_graph import _with_progress

        called = {"yes": False}

        async def _fake_node(state, config=None):
            called["yes"] = True
            return {}

        wrapper = _with_progress("quality_gate", _fake_node)
        asyncio.run(wrapper({"node_statuses": {}}, None))
        assert called["yes"], "non-runtime nodes must still work"
