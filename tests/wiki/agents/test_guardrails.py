"""Tests for the unified guardrails module (Layer 1a)."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from wiki.agents.context import RunContext, WikiDeps


class TestGuardrailResult:
    def test_default_values(self):
        from wiki.agents.guardrails import GuardrailResult

        r = GuardrailResult(passed=True)
        assert r.passed is True
        assert r.output_info == ""
        assert r.tripwire is False

    def test_tripwire_flag(self):
        from wiki.agents.guardrails import GuardrailResult

        r = GuardrailResult(passed=False, tripwire=True, output_info="blocked")
        assert r.passed is False
        assert r.tripwire is True
        assert r.output_info == "blocked"


class TestInputGuardrail:
    @pytest.mark.asyncio
    async def test_input_guardrail_protocol_check(self):
        from wiki.agents.guardrails import InputGuardrail, GuardrailResult

        class MyInputGuardrail:
            async def check(self, user_prompt: str, ctx: RunContext) -> GuardrailResult:
                if len(user_prompt) > 100000:
                    return GuardrailResult(passed=False, tripwire=True, output_info="prompt too long")
                return GuardrailResult(passed=True)

        guard = MyInputGuardrail()
        ctx = RunContext(deps=WikiDeps(graph_store=MagicMock()))

        result = await guard.check("short prompt", ctx)
        assert result.passed is True

        result = await guard.check("x" * 200000, ctx)
        assert result.passed is False
        assert result.tripwire is True

    @pytest.mark.asyncio
    async def test_prompt_length_guardrail(self):
        from wiki.agents.guardrails import PromptLengthGuardrail

        guard = PromptLengthGuardrail(max_chars=1000)
        ctx = RunContext(deps=WikiDeps(graph_store=MagicMock()))

        result = await guard.check("short", ctx)
        assert result.passed is True

        result = await guard.check("x" * 2000, ctx)
        assert result.passed is False
        assert result.tripwire is True


class TestOutputGuardrail:
    @pytest.mark.asyncio
    async def test_output_guardrail_protocol_check(self):
        from wiki.agents.guardrails import OutputGuardrail, GuardrailResult

        class MyOutputGuardrail:
            async def check(self, output: str, ctx: RunContext) -> GuardrailResult:
                if "forbidden" in output:
                    return GuardrailResult(passed=False, output_info="contains forbidden content")
                return GuardrailResult(passed=True)

        guard = MyOutputGuardrail()
        ctx = RunContext(deps=WikiDeps(graph_store=MagicMock()))

        result = await guard.check("clean output", ctx)
        assert result.passed is True

        result = await guard.check("this has forbidden word", ctx)
        assert result.passed is False


class TestToolGuardrailWithCtx:
    @pytest.mark.asyncio
    async def test_tool_guardrail_receives_ctx(self):
        from wiki.agents.guardrails import ToolGuardrailWithCtx, GuardrailResult

        class MyToolGuardrail:
            async def pre_call(self, name: str, args: dict, ctx: RunContext) -> dict | None:
                if name == "dangerous_tool":
                    return None
                return args

            async def post_call(self, name: str, args: dict, result: str, ctx: RunContext) -> str:
                return result

        guard = MyToolGuardrail()
        ctx = RunContext(deps=WikiDeps(graph_store=MagicMock()))

        result = await guard.pre_call("safe_tool", {"x": 1}, ctx)
        assert result == {"x": 1}

        result = await guard.pre_call("dangerous_tool", {"x": 1}, ctx)
        assert result is None


class TestGuardrailTrippedError:
    def test_error_contains_info(self):
        from wiki.agents.guardrails import GuardrailTrippedError

        err = GuardrailTrippedError("prompt too long", guardrail_name="PromptLength")
        assert "prompt too long" in str(err)
        assert err.guardrail_name == "PromptLength"


class TestRunToolLoopInputGuardrails:
    @pytest.mark.asyncio
    async def test_input_guardrail_blocks_execution(self):
        """When input guardrail returns tripwire=True, loop should raise."""
        from wiki.agents.base_agent import RunConfig, ToolDef
        from wiki.agents.guardrails import GuardrailResult, GuardrailTrippedError

        class BlockingGuardrail:
            async def check(self, user_prompt, ctx):
                return GuardrailResult(passed=False, tripwire=True, output_info="blocked")

        mock_llm = MagicMock()
        mock_llm.complete_with_tools = AsyncMock()

        from tests.wiki.agents.test_base_agent import ConcreteAgent

        agent = ConcreteAgent(mock_llm, max_rounds=5, max_tool_calls=10)
        agent._tool_registry.register(
            ToolDef("noop", "d", {}, AsyncMock(return_value={"ok": True}), tier=1)
        )

        config = RunConfig(input_guardrails=[BlockingGuardrail()])
        ctx = RunContext(deps=WikiDeps(graph_store=MagicMock()))

        from wiki.agents.memory import Memory

        with pytest.raises(GuardrailTrippedError) as exc_info:
            await agent.run_tool_loop("sys", "blocked prompt", Memory(), config=config, ctx=ctx)

        assert "blocked" in str(exc_info.value)
        mock_llm.complete_with_tools.assert_not_called()

    @pytest.mark.asyncio
    async def test_passing_input_guardrail_allows_execution(self):
        """When input guardrail passes, loop should proceed normally."""
        from wiki.agents.base_agent import RunConfig, ToolDef
        from wiki.agents.guardrails import GuardrailResult

        class PassingGuardrail:
            async def check(self, user_prompt, ctx):
                return GuardrailResult(passed=True)

        mock_llm = MagicMock()
        mock_llm.complete_with_tools = AsyncMock(return_value={
            "tool_calls": None, "content": "done"
        })

        from tests.wiki.agents.test_base_agent import ConcreteAgent

        agent = ConcreteAgent(mock_llm, max_rounds=5, max_tool_calls=10)
        agent._tool_registry.register(
            ToolDef("noop", "d", {}, AsyncMock(return_value={"ok": True}), tier=1)
        )

        config = RunConfig(input_guardrails=[PassingGuardrail()])
        ctx = RunContext(deps=WikiDeps(graph_store=MagicMock()))

        from wiki.agents.memory import Memory

        result = await agent.run_tool_loop("sys", "ok prompt", Memory(), config=config, ctx=ctx)
        assert result is not None


class TestRunToolLoopOutputGuardrails:
    @pytest.mark.asyncio
    async def test_output_guardrail_runs_after_loop(self):
        """Output guardrails are called with the final LLM output."""
        from wiki.agents.base_agent import RunConfig, ToolDef
        from wiki.agents.guardrails import GuardrailResult

        captured_output: list[str] = []

        class CapturingGuardrail:
            async def check(self, output, ctx):
                captured_output.append(output)
                return GuardrailResult(passed=True)

        mock_llm = MagicMock()
        mock_llm.complete_with_tools = AsyncMock(return_value={
            "tool_calls": None, "content": "final output text"
        })

        from tests.wiki.agents.test_base_agent import ConcreteAgent

        agent = ConcreteAgent(mock_llm, max_rounds=5, max_tool_calls=10)
        agent._tool_registry.register(
            ToolDef("noop", "d", {}, AsyncMock(return_value={"ok": True}), tier=1)
        )

        config = RunConfig(output_guardrails=[CapturingGuardrail()])
        ctx = RunContext(deps=WikiDeps(graph_store=MagicMock()))

        from wiki.agents.memory import Memory

        await agent.run_tool_loop("sys", "usr", Memory(), config=config, ctx=ctx)
        assert len(captured_output) == 1
        assert captured_output[0] == "final output text"

    @pytest.mark.asyncio
    async def test_output_guardrail_tripwire_raises(self):
        """When output guardrail returns tripwire=True, should raise."""
        from wiki.agents.base_agent import RunConfig, ToolDef
        from wiki.agents.guardrails import GuardrailResult, GuardrailTrippedError

        class TrippingGuardrail:
            async def check(self, output, ctx):
                return GuardrailResult(passed=False, tripwire=True, output_info="bad output")

        mock_llm = MagicMock()
        mock_llm.complete_with_tools = AsyncMock(return_value={
            "tool_calls": None, "content": "bad content"
        })

        from tests.wiki.agents.test_base_agent import ConcreteAgent

        agent = ConcreteAgent(mock_llm, max_rounds=5, max_tool_calls=10)
        agent._tool_registry.register(
            ToolDef("noop", "d", {}, AsyncMock(return_value={"ok": True}), tier=1)
        )

        config = RunConfig(output_guardrails=[TrippingGuardrail()])
        ctx = RunContext(deps=WikiDeps(graph_store=MagicMock()))

        from wiki.agents.memory import Memory

        with pytest.raises(GuardrailTrippedError):
            await agent.run_tool_loop("sys", "usr", Memory(), config=config, ctx=ctx)
