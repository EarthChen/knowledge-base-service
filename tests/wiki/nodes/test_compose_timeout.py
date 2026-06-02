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


class TestComposePerDomainTimeout:
    """Verify per-domain timeout scales dynamically by module count."""

    def test_per_domain_wait_for_exists(self):
        """_run_domain should use asyncio.wait_for for per-domain safety cap."""
        import ast
        from pathlib import Path

        source = Path("wiki/nodes/domain_compose.py").read_text()
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_run_domain":
                body_source = ast.get_source_segment(source, node)
                assert "wait_for" in body_source, (
                    "_run_domain should use asyncio.wait_for for per-domain timeout cap"
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


class TestWritePhaseHeartbeat:
    """I1: run_generation must emit heartbeat before/after LLM calls."""

    @pytest.mark.asyncio
    async def test_run_generation_calls_heartbeat(self):
        from unittest.mock import AsyncMock, MagicMock

        from wiki.agents.base_agent import RunConfig

        calls: list[int] = []

        def fake_heartbeat() -> None:
            calls.append(1)

        agent = MagicMock()
        agent._llm = AsyncMock()
        agent._llm.generate = AsyncMock(return_value="generated content")
        agent._run_output_guardrails = AsyncMock()
        agent.output_type = None

        config = RunConfig(heartbeat=fake_heartbeat)

        from wiki.agents.base_agent import GenericAgent

        result = await GenericAgent.run_generation(agent, "system", "user", config=config)
        assert result == "generated content"
        assert len(calls) >= 2, f"heartbeat should be called at least twice (before+after LLM), got {len(calls)}"

    @pytest.mark.asyncio
    async def test_run_generation_no_heartbeat_when_none(self):
        from unittest.mock import AsyncMock, MagicMock

        agent = MagicMock()
        agent._llm = AsyncMock()
        agent._llm.generate = AsyncMock(return_value="ok")
        agent._run_output_guardrails = AsyncMock()
        agent.output_type = None

        from wiki.agents.base_agent import GenericAgent

        result = await GenericAgent.run_generation(agent, "system", "user")
        assert result == "ok"

    def test_domain_doc_agent_get_write_config_with_heartbeat(self):
        from unittest.mock import MagicMock

        calls = []

        def hb():
            calls.append(1)

        from wiki.domain_doc_agent import DomainDocAgent

        agent = MagicMock(spec=DomainDocAgent)
        agent._heartbeat = hb
        config = DomainDocAgent._get_write_config(agent)
        assert config is not None
        assert config.heartbeat is hb

    def test_domain_doc_agent_get_write_config_none_without_heartbeat(self):
        from unittest.mock import MagicMock

        from wiki.domain_doc_agent import DomainDocAgent

        agent = MagicMock(spec=DomainDocAgent)
        agent._heartbeat = None
        config = DomainDocAgent._get_write_config(agent)
        assert config is None


class TestLangGraphErrorHandlerIntegration:
    """I5: Integration test — compile a mini StateGraph with error_handler."""

    @pytest.mark.asyncio
    async def test_error_handler_receives_error_on_failure(self):
        from typing import Any

        from langgraph.errors import NodeError
        from langgraph.graph import StateGraph
        from langgraph.types import Command, RetryPolicy

        received_errors: list = []

        async def failing_node(state: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("simulated compose failure")

        async def error_handler(state: dict[str, Any], *, error: NodeError) -> Command:
            real_error = getattr(error, "error", error)
            received_errors.append(real_error)
            return Command(update={"result": f"fallback: {type(real_error).__name__}"}, goto="end_node")

        async def end_node(state: dict[str, Any]) -> dict[str, Any]:
            return {}

        graph = StateGraph(dict)
        graph.add_node(
            "failing",
            failing_node,
            retry_policy=RetryPolicy(max_attempts=1, retry_on=(RuntimeError,)),
            error_handler=error_handler,
        )
        graph.add_node("end_node", end_node)
        graph.add_edge("failing", "end_node")
        graph.set_entry_point("failing")
        graph.set_finish_point("end_node")

        compiled = graph.compile()
        await compiled.ainvoke({})

        assert len(received_errors) == 1, "error_handler should receive exactly one error"
        assert isinstance(received_errors[0], RuntimeError)
        assert "simulated compose failure" in str(received_errors[0])

    def test_production_error_handler_uses_node_error_annotation(self):
        """Verify compose_error_fallback uses NodeError annotation (required by LangGraph)."""
        import inspect

        from wiki.nodes.compose_error_handler import compose_error_fallback

        sig = inspect.signature(compose_error_fallback)
        error_param = sig.parameters["error"]
        assert error_param.annotation == "NodeError", (
            f"error param must be annotated as 'NodeError' (got '{error_param.annotation}'). "
            "LangGraph requires exact NodeError annotation for error injection."
        )
