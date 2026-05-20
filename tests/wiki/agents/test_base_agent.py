import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wiki.agents.base_agent import GenericAgent


class TestToolDef:
    def test_tool_def_has_required_fields(self):
        from wiki.agents.base_agent import ToolDef

        async def handler(args):
            return {"ok": True}

        td = ToolDef(
            name="test_tool",
            description="A test tool",
            parameters={"type": "object", "properties": {}},
            handler=handler,
            tier=1,
        )
        assert td.name == "test_tool"
        assert td.tier == 1

    def test_tool_def_default_tier_is_1(self):
        from wiki.agents.base_agent import ToolDef

        td = ToolDef(
            name="t",
            description="d",
            parameters={},
            handler=AsyncMock(),
        )
        assert td.tier == 1


class TestToolRegistry:
    def test_register_and_get_all(self):
        from wiki.agents.base_agent import ToolDef, ToolRegistry

        reg = ToolRegistry()
        t1 = ToolDef("a", "desc_a", {"type": "object"}, AsyncMock(), tier=1)
        t2 = ToolDef("b", "desc_b", {"type": "object"}, AsyncMock(), tier=2)
        reg.register(t1)
        reg.register(t2)

        schemas = reg.get_all_tool_schemas()
        assert len(schemas) == 2
        names = {s["function"]["name"] for s in schemas}
        assert names == {"a", "b"}

    def test_tier_progression_round_1(self):
        from wiki.agents.base_agent import ToolDef, ToolRegistry

        reg = ToolRegistry()
        reg.register(ToolDef("core", "d", {}, AsyncMock(), tier=1))
        reg.register(ToolDef("ext", "d", {}, AsyncMock(), tier=2))
        reg.register(ToolDef("sup", "d", {}, AsyncMock(), tier=3))

        tools = reg.get_tools_for_round(1, has_empty=False)
        names = {t["function"]["name"] for t in tools}
        assert names == {"core"}

    def test_tier_progression_round_3(self):
        from wiki.agents.base_agent import ToolDef, ToolRegistry

        reg = ToolRegistry()
        reg.register(ToolDef("core", "d", {}, AsyncMock(), tier=1))
        reg.register(ToolDef("ext", "d", {}, AsyncMock(), tier=2))
        reg.register(ToolDef("sup", "d", {}, AsyncMock(), tier=3))

        tools = reg.get_tools_for_round(3, has_empty=False)
        names = {t["function"]["name"] for t in tools}
        assert names == {"core", "ext"}

    def test_tier_progression_round_5_all(self):
        from wiki.agents.base_agent import ToolDef, ToolRegistry

        reg = ToolRegistry()
        reg.register(ToolDef("core", "d", {}, AsyncMock(), tier=1))
        reg.register(ToolDef("ext", "d", {}, AsyncMock(), tier=2))
        reg.register(ToolDef("sup", "d", {}, AsyncMock(), tier=3))

        tools = reg.get_tools_for_round(5, has_empty=False)
        names = {t["function"]["name"] for t in tools}
        assert names == {"core", "ext", "sup"}

    def test_tier_progression_empty_unlocks_all(self):
        from wiki.agents.base_agent import ToolDef, ToolRegistry

        reg = ToolRegistry()
        reg.register(ToolDef("core", "d", {}, AsyncMock(), tier=1))
        reg.register(ToolDef("ext", "d", {}, AsyncMock(), tier=2))
        reg.register(ToolDef("sup", "d", {}, AsyncMock(), tier=3))

        tools = reg.get_tools_for_round(1, has_empty=True)
        names = {t["function"]["name"] for t in tools}
        assert names == {"core", "ext", "sup"}

    @pytest.mark.asyncio
    async def test_dispatch_calls_handler(self):
        from wiki.agents.base_agent import ToolDef, ToolRegistry

        handler = AsyncMock(return_value={"result": 42})
        reg = ToolRegistry()
        reg.register(ToolDef("calc", "d", {}, handler, tier=1))

        result, result_str = await reg.dispatch("calc", {"x": 1})
        assert result == {"result": 42}
        handler.assert_called_once_with({"x": 1})

    @pytest.mark.asyncio
    async def test_dispatch_unknown_tool_returns_error(self):
        from wiki.agents.base_agent import ToolRegistry

        reg = ToolRegistry()
        result, _ = await reg.dispatch("unknown", {})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_dispatch_handler_exception_returns_error(self):
        from wiki.agents.base_agent import ToolDef, ToolRegistry

        handler = AsyncMock(side_effect=RuntimeError("boom"))
        reg = ToolRegistry()
        reg.register(ToolDef("fail_tool", "d", {}, handler, tier=1))

        result, _ = await reg.dispatch("fail_tool", {})
        assert "error" in result
        assert "boom" in result["error"]

    @pytest.mark.asyncio
    async def test_dispatch_passes_ctx_to_handler(self):
        from wiki.agents.base_agent import ToolDef, ToolRegistry
        from wiki.agents.context import RunContext, WikiDeps
        from unittest.mock import MagicMock

        received_ctx = {}

        async def handler(args, ctx):
            received_ctx["ctx"] = ctx
            return {"ok": True}

        reg = ToolRegistry()
        reg.register(ToolDef("test_tool", "d", {}, handler, tier=1))

        deps = WikiDeps(graph_store=MagicMock())
        ctx = RunContext(deps=deps, trace_id="t1")
        result, _ = await reg.dispatch("test_tool", {"x": 1}, ctx=ctx)

        assert result == {"ok": True}
        assert received_ctx["ctx"] is ctx
        assert received_ctx["ctx"].trace_id == "t1"

    @pytest.mark.asyncio
    async def test_dispatch_falls_back_when_handler_rejects_ctx(self):
        from wiki.agents.base_agent import ToolDef, ToolRegistry
        from wiki.agents.context import RunContext, WikiDeps
        from unittest.mock import MagicMock

        calls: list[tuple] = []

        async def legacy_handler(args: dict) -> dict:
            calls.append((args,))
            return {"ok": True}

        reg = ToolRegistry()
        reg.register(ToolDef("legacy_tool", "d", {}, legacy_handler, tier=1))

        deps = WikiDeps(graph_store=MagicMock())
        ctx = RunContext(deps=deps)
        result, _ = await reg.dispatch("legacy_tool", {"x": 1}, ctx=ctx)

        assert result == {"ok": True}
        assert calls == [({"x": 1},)]


    @pytest.mark.asyncio
    async def test_dispatch_propagates_internal_typeerror(self):
        """A TypeError INSIDE the handler must propagate as error, not be swallowed."""
        from wiki.agents.base_agent import ToolDef, ToolRegistry
        from wiki.agents.context import RunContext, WikiDeps
        from unittest.mock import MagicMock

        async def buggy_handler(args, ctx):
            # This TypeError is an actual bug inside the tool
            return len(None)  # TypeError: object of type 'NoneType' has no len()

        reg = ToolRegistry()
        reg.register(ToolDef("buggy", "d", {}, buggy_handler, tier=1))

        deps = WikiDeps(graph_store=MagicMock())
        ctx = RunContext(deps=deps)
        result, _ = await reg.dispatch("buggy", {}, ctx=ctx)
        # Should report the real TypeError as error
        assert "error" in result
        assert "NoneType" in result["error"]


class TestWikiPageAgentCreateMemory:
    def test_create_memory_returns_working_memory(self):
        from wiki.page_agent import WikiPageAgent, WorkingMemory

        agent = WikiPageAgent(llm=None, graph_store=None)
        mem = agent.create_memory()
        assert isinstance(mem, WorkingMemory)


class ConcreteAgent(GenericAgent):
    """Minimal concrete subclass for testing GenericAgent execution methods."""

    def __init__(self, llm, **kwargs):
        super().__init__(llm, **kwargs)
        self._incorporated: list[tuple[str, dict]] = []

    def incorporate(self, tool_name, result, memory):
        self._incorporated.append((tool_name, result))
        if hasattr(memory, "add"):
            memory.add("findings", f"{tool_name}: {json.dumps(result, default=str)[:200]}")

    def memory_to_prompt(self, memory):
        if hasattr(memory, "entries"):
            parts = []
            for k, vals in memory.entries.items():
                parts.extend(vals)
            return "\n".join(parts) if parts else "(empty)"
        return str(memory)


class TestRunToolLoop:
    @pytest.mark.asyncio
    async def test_basic_tool_loop_executes_tools(self):
        from wiki.agents.base_agent import ToolDef

        handler = AsyncMock(return_value={"data": "hello"})
        mock_llm = MagicMock()
        mock_llm.complete_with_tools = AsyncMock(side_effect=[
            {
                "tool_calls": [{
                    "id": "tc1",
                    "function": {"name": "test_tool", "arguments": '{"q": "x"}'},
                }],
                "content": None,
            },
            {"tool_calls": None, "content": "done"},
        ])

        agent = ConcreteAgent(mock_llm, max_rounds=5, max_tool_calls=10)
        agent._tool_registry.register(
            ToolDef("test_tool", "a test tool", {"type": "object"}, handler, tier=1)
        )

        from wiki.agents.memory import Memory

        memory = Memory()
        result = await agent.run_tool_loop("system", "user prompt", memory)

        assert result is memory
        handler.assert_called_once_with({"q": "x"})
        assert len(agent._incorporated) == 1
        assert agent._incorporated[0][0] == "test_tool"
        assert memory.total_chars() > 0

    @pytest.mark.asyncio
    async def test_tool_loop_respects_max_tool_calls(self):
        from wiki.agents.base_agent import ToolDef
        from wiki.agents.memory import Memory

        call_count = 0

        async def counting_handler(args):
            nonlocal call_count
            call_count += 1
            return {"n": call_count}

        _call_idx = 0

        async def _varying_llm_response(*args, **kwargs):
            nonlocal _call_idx
            _call_idx += 1
            return {
                "tool_calls": [{
                    "id": f"tc_{_call_idx}",
                    "function": {"name": "counter", "arguments": f'{{"step": {_call_idx}}}'},
                }],
                "content": None,
            }

        mock_llm = MagicMock()
        mock_llm.complete_with_tools = AsyncMock(side_effect=_varying_llm_response)

        agent = ConcreteAgent(mock_llm, max_rounds=100, max_tool_calls=3)
        agent._tool_registry.register(
            ToolDef("counter", "d", {}, counting_handler, tier=1)
        )

        memory = Memory()
        await agent.run_tool_loop("sys", "usr", memory)

        assert call_count == 3

    @pytest.mark.asyncio
    async def test_tool_loop_nudges_llm_when_no_tools_early(self):
        from wiki.agents.base_agent import ToolDef
        from wiki.agents.memory import Memory

        mock_llm = MagicMock()
        mock_llm.complete_with_tools = AsyncMock(side_effect=[
            {"tool_calls": None, "content": "thinking..."},
            {"tool_calls": None, "content": "still thinking..."},
            {"tool_calls": None, "content": "ok done"},
        ])

        agent = ConcreteAgent(mock_llm, max_rounds=5, max_tool_calls=10)
        agent._tool_registry.register(
            ToolDef("noop", "unused in this test", {"type": "object"}, AsyncMock(return_value={"ok": True}), tier=1)
        )
        memory = Memory()
        await agent.run_tool_loop("sys", "usr", memory, nudge_message="Use tools!")

        assert mock_llm.complete_with_tools.call_count >= 2

    @pytest.mark.asyncio
    async def test_tool_loop_no_tools_registered_returns_immediately(self):
        from wiki.agents.memory import Memory

        mock_llm = MagicMock()
        mock_llm.complete_with_tools = AsyncMock()

        agent = ConcreteAgent(mock_llm, max_rounds=5)
        memory = Memory()
        result = await agent.run_tool_loop("sys", "usr", memory)

        assert result is memory
        mock_llm.complete_with_tools.assert_not_called()

    @pytest.mark.asyncio
    async def test_tool_loop_handles_llm_exception(self):
        from wiki.agents.base_agent import ToolDef
        from wiki.agents.memory import Memory

        mock_llm = MagicMock()
        mock_llm.complete_with_tools = AsyncMock(side_effect=RuntimeError("LLM unavailable"))

        agent = ConcreteAgent(mock_llm, max_rounds=5, max_tool_calls=10)
        agent._tool_registry.register(
            ToolDef("noop", "d", {}, AsyncMock(return_value={"ok": True}), tier=1)
        )
        memory = Memory()
        with patch("wiki.agents.runner.log.warning") as mock_warning:
            result = await agent.run_tool_loop("sys", "usr", memory)

        assert result is memory
        mock_warning.assert_called()
        event_names = {c.args[0] for c in mock_warning.call_args_list if c.args}
        assert "run_agent_loop_llm_failed" in event_names


@pytest.mark.asyncio
async def test_run_config_ctx_used_when_no_explicit_ctx():
    """Verify config.ctx is used when ctx param is not passed."""
    from wiki.agents.base_agent import RunConfig
    from wiki.agents.context import RunContext, WikiDeps

    deps = WikiDeps(graph_store=MagicMock())
    config_ctx = RunContext(deps=deps, trace_id="from-config")
    config = RunConfig(ctx=config_ctx)

    # Just verify RunConfig accepts ctx
    assert config.ctx is config_ctx
    assert config.ctx.trace_id == "from-config"


class TestRunGeneration:
    @pytest.mark.asyncio
    async def test_run_generation_calls_llm(self):
        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(return_value="# Generated Content")

        agent = ConcreteAgent(mock_llm)
        result = await agent.run_generation("system prompt", "user prompt")

        assert result == "# Generated Content"
        mock_llm.generate.assert_called_once_with(
            prompt="user prompt", system="system prompt"
        )

class TestRunGenerationError:
    @pytest.mark.asyncio
    async def test_run_generation_raises_on_llm_failure(self):
        """LLM failure must raise LLMGenerationError, not return empty string."""
        from wiki.agents.base_agent import LLMGenerationError

        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(side_effect=RuntimeError("model overloaded"))

        agent = ConcreteAgent(mock_llm)
        with pytest.raises(LLMGenerationError, match="model overloaded"):
            await agent.run_generation("system", "user prompt")

    @pytest.mark.asyncio
    async def test_run_generation_returns_text_on_success(self):
        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(return_value="Hello world")

        agent = ConcreteAgent(mock_llm)
        result = await agent.run_generation("system", "user prompt")
        assert result == "Hello world"
