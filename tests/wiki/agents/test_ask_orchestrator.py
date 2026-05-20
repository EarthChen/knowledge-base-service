from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.wiki.agents.test_base_agent import ConcreteAgent
from wiki.agents.ask_orchestrator import ASK_ANSWER_SYSTEM, ASK_EXPLORE_SYSTEM, AskOrchestrator
from wiki.agents.base_agent import ToolDef
from wiki.agents.memory import Memory


class TestAskOrchestrator:
    @pytest.mark.asyncio
    async def test_ask_explores_and_generates_answer(self):
        handler = AsyncMock(return_value={"file": "auth.py", "hit": True})
        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(return_value="Authentication lives in wiki/auth.py.")
        mock_llm.complete_with_tools = AsyncMock(
            side_effect=[
                {
                    "tool_calls": [{
                        "id": "tc1",
                        "function": {"name": "search_module", "arguments": '{"q": "auth"}'},
                    }],
                    "content": None,
                },
                {"tool_calls": None, "content": "done exploring"},
            ]
        )

        agent = ConcreteAgent(mock_llm, max_rounds=5, max_tool_calls=10)
        agent._tool_registry.register(
            ToolDef(
                "search_module",
                "find modules",
                {"type": "object"},
                handler,
                tier=1,
            )
        )

        orch = AskOrchestrator(agent)
        result = await orch.ask("Where is auth implemented?")

        assert result["answer"] == "Authentication lives in wiki/auth.py."
        handler.assert_called_once_with({"q": "auth"})
        mock_llm.generate.assert_called_once()
        gen_kwargs = mock_llm.generate.call_args[1]
        assert gen_kwargs["system"] == ASK_ANSWER_SYSTEM
        assert "Where is auth implemented?" in gen_kwargs["prompt"]
        assert "Code intelligence findings:" in gen_kwargs["prompt"]

        assert mock_llm.complete_with_tools.call_count >= 1
        explore_messages = mock_llm.complete_with_tools.call_args_list[0][0][0]
        assert explore_messages[0]["content"] == ASK_EXPLORE_SYSTEM
        assert "Where is auth implemented?" in explore_messages[1]["content"]

    @pytest.mark.asyncio
    async def test_ask_returns_degraded_answer_on_failure(self):
        mock_llm = MagicMock()
        mock_llm.complete_with_tools = AsyncMock()

        agent = ConcreteAgent(mock_llm)
        mock_llm.generate = AsyncMock(side_effect=RuntimeError("LLM unavailable"))

        orch = AskOrchestrator(agent)
        result = await orch.ask("Anything?")

        assert "Unable to generate an answer" in result["answer"]
        assert result["sources"] == []

    @pytest.mark.asyncio
    async def test_ask_includes_sources_from_memory(self):
        long_line = "finding: " + "x" * 50
        mem = Memory()
        mem.add("findings", long_line)

        mock_agent = MagicMock()
        mock_agent.create_memory = MagicMock(return_value=mem)
        mock_agent.run_tool_loop = AsyncMock(return_value=mem)
        mock_agent.memory_to_prompt = MagicMock(return_value=long_line)
        mock_agent.run_generation = AsyncMock(return_value="Based on findings.")

        orch = AskOrchestrator(mock_agent)
        result = await orch.ask("Q?")

        assert result["answer"] == "Based on findings."
        assert len(result["sources"]) == 1
        assert result["sources"][0] == long_line[:200]

    @pytest.mark.asyncio
    async def test_ask_without_tools_still_generates(self):
        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(return_value="Answer without tool use.")
        mock_llm.complete_with_tools = AsyncMock()

        agent = ConcreteAgent(mock_llm)
        orch = AskOrchestrator(agent)
        result = await orch.ask("What is 2+2?")

        mock_llm.complete_with_tools.assert_not_called()
        mock_llm.generate.assert_called_once()
        _, kwargs = mock_llm.generate.call_args
        assert kwargs["system"] == ASK_ANSWER_SYSTEM
        assert result["answer"] == "Answer without tool use."


class TestAskExports:
    def test_package_exports_ask_orchestrator(self):
        from wiki.agents import AskOrchestrator as AO

        assert AO is AskOrchestrator
