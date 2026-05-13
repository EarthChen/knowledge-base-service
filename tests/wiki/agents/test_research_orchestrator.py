from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.wiki.agents.test_base_agent import ConcreteAgent
from wiki.agents.base_agent import ToolDef
from wiki.agents.research_orchestrator import (
    EXPLORE_SYSTEM,
    ResearchOrchestrator,
    _parse_sub_questions,
)


class TestParseSubQuestions:
    def test_strips_numbered_lines(self):
        text = "1. First question?\n2) Second question?\n"
        assert _parse_sub_questions(text) == ["First question?", "Second question?"]

    def test_strips_bullets(self):
        text = "- Alpha?\n* Beta?\n• Gamma?\n"
        assert _parse_sub_questions(text) == ["Alpha?", "Beta?", "Gamma?"]

    def test_caps_at_four(self):
        text = "\n".join(f"{i}. Q{i}?" for i in range(1, 8))
        assert len(_parse_sub_questions(text)) == 4

    def test_empty_input(self):
        assert _parse_sub_questions("") == []
        assert _parse_sub_questions("   \n  \n") == []


class TestDecompose:
    @pytest.mark.asyncio
    async def test_decompose_successful_llm_response(self):
        mock_agent = MagicMock()
        mock_agent.run_generation = AsyncMock(
            return_value="How does authentication work?\nWhat are the main modules?\n"
        )

        orch = ResearchOrchestrator(mock_agent)
        result = await orch.decompose("Explain the auth system")

        assert result == [
            "How does authentication work?",
            "What are the main modules?",
        ]
        mock_agent.run_generation.assert_called_once()
        sys_prompt, user_prompt = mock_agent.run_generation.call_args[0]
        assert "sub-question" in sys_prompt.lower() or "break" in sys_prompt.lower()
        assert user_prompt == "Explain the auth system"

    @pytest.mark.asyncio
    async def test_decompose_fallback_when_llm_returns_empty(self):
        mock_agent = MagicMock()
        mock_agent.run_generation = AsyncMock(return_value="")

        orch = ResearchOrchestrator(mock_agent)
        q = "Single fallback question?"
        with patch("wiki.agents.research_orchestrator.log.warning") as mock_log:
            result = await orch.decompose(q)

        assert result == [q]
        mock_log.assert_called()


class TestExploreSubQuestion:
    @pytest.mark.asyncio
    async def test_explore_calls_run_tool_loop(self):
        mock_agent = MagicMock()
        mem = MagicMock()
        mock_agent.run_tool_loop = AsyncMock(return_value=mem)

        orch = ResearchOrchestrator(mock_agent)
        out = await orch.explore_sub_question("Sub Q?", mem)

        assert out is mem
        mock_agent.run_tool_loop.assert_called_once_with(
            EXPLORE_SYSTEM, "Sub Q?", mem
        )


class TestAnswerSubQuestion:
    @pytest.mark.asyncio
    async def test_answer_uses_memory_to_prompt_and_generation(self):
        mock_agent = MagicMock()
        mock_agent.memory_to_prompt = MagicMock(return_value="line a\nline b")
        mock_agent.run_generation = AsyncMock(return_value="Answer text")

        orch = ResearchOrchestrator(mock_agent)
        memory = MagicMock()
        ans = await orch.answer_sub_question("What is X?", memory)

        assert ans == "Answer text"
        mock_agent.memory_to_prompt.assert_called_once_with(memory)
        _, user_prompt = mock_agent.run_generation.call_args[0]
        assert "What is X?" in user_prompt
        assert "line a" in user_prompt
        assert "Evidence from tools:" in user_prompt


class TestSynthesize:
    @pytest.mark.asyncio
    async def test_synthesize_combines_sub_answers(self):
        mock_agent = MagicMock()
        mock_agent.run_generation = AsyncMock(return_value="Final")

        orch = ResearchOrchestrator(mock_agent)
        out = await orch.synthesize(
            "Main Q?",
            ["Sq1", "Sq2"],
            ["A1", "A2"],
        )

        assert out == "Final"
        _, user_prompt = mock_agent.run_generation.call_args[0]
        assert "Main Q?" in user_prompt
        assert "Sq1" in user_prompt and "Sq2" in user_prompt
        assert "A1" in user_prompt and "A2" in user_prompt


class TestResearchPipeline:
    @pytest.mark.asyncio
    async def test_research_end_to_end(self):
        mock_agent = MagicMock()
        mem_a, mem_b = MagicMock(name="a"), MagicMock(name="b")

        mock_agent.create_memory = MagicMock(side_effect=[mem_a, mem_b])
        mock_agent.run_tool_loop = AsyncMock(side_effect=lambda sys, usr, mem: mem)
        mock_agent.memory_to_prompt = MagicMock(return_value="M")
        mock_agent.run_generation = AsyncMock(
            side_effect=[
                "One?\nTwo?",  # decompose
                "Ans1",
                "Ans2",
                "Synth",
            ],
        )

        orch = ResearchOrchestrator(mock_agent)
        result = await orch.research("Big question?")

        assert result["question"] == "Big question?"
        assert result["sub_questions"] == ["One?", "Two?"]
        assert result["sub_answers"] == ["Ans1", "Ans2"]
        assert result["synthesis"] == "Synth"
        assert mock_agent.run_tool_loop.call_count == 2
        assert mock_agent.create_memory.call_count == 2


class TestResearchWithTools:
    @pytest.mark.asyncio
    async def test_research_with_actual_tool_calls(self):
        handler = AsyncMock(return_value={"fact": "Paris"})
        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(
            side_effect=[
                "What is the capital of France?",
                "The capital is Paris based on the lookup result.",
                "France's capital is Paris.",
            ]
        )
        mock_llm.complete_with_tools = AsyncMock(
            side_effect=[
                {
                    "tool_calls": [{
                        "id": "tc1",
                        "function": {"name": "lookup", "arguments": "{}"},
                    }],
                    "content": None,
                },
                {"tool_calls": None, "content": "done"},
            ]
        )

        agent = ConcreteAgent(mock_llm, max_rounds=5, max_tool_calls=10)
        agent._tool_registry.register(
            ToolDef("lookup", "lookup fact", {"type": "object"}, handler, tier=1)
        )

        orch = ResearchOrchestrator(agent)
        result = await orch.research("Where is French government seated?")

        assert result["sub_questions"] == ["What is the capital of France?"]
        assert result["synthesis"] == "France's capital is Paris."
        handler.assert_called_once_with({})
        assert any(t[0] == "lookup" for t in agent._incorporated)


class TestExports:
    def test_package_exports_research_orchestrator(self):
        from wiki.agents import ResearchOrchestrator as RO

        assert RO is ResearchOrchestrator
