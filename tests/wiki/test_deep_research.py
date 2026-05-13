import pytest
from unittest.mock import AsyncMock, MagicMock

from wiki.deep_research import DeepResearchService


@pytest.mark.asyncio
async def test_decompose_question():
    engine = AsyncMock()
    service = DeepResearchService(rag_engine=engine)
    questions = await service.decompose_question("How does authentication work end-to-end?")
    assert isinstance(questions, list)
    assert len(questions) >= 1


@pytest.mark.asyncio
async def test_research_returns_structured_result():
    async def arun(*, question, scope, max_rounds=7):  # noqa: ARG001
        return {"current_draft": "x", "round": 1}

    mock_engine = MagicMock()
    mock_engine.arun = arun

    service = DeepResearchService(rag_engine=mock_engine, llm=None)
    result = await service.research(
        question="How does auth work?",
        repository="test-repo",
        business_id="default",
    )
    assert "question" in result
    assert "sub_questions" in result
    assert "synthesis" in result
    assert "sub_answers" in result


@pytest.mark.asyncio
async def test_research_calls_engine_for_sub_questions():
    calls: list[tuple[str, object]] = []

    async def arun(*, question, scope, max_rounds=7):  # noqa: ARG001
        calls.append((question, scope))
        return {"current_draft": "sub-answer", "round": 1}

    mock_engine = MagicMock()
    mock_engine.arun = arun
    service = DeepResearchService(rag_engine=mock_engine, llm=None)
    result = await service.research(
        question="How does X work?",
        repository="test-repo",
        business_id="default",
    )
    assert len(calls) == 1
    assert calls[0][0] == "How does X work?"
    assert getattr(calls[0][1], "repository", None) == "test-repo"
    assert result["sub_answers"][0] == "sub-answer"


@pytest.mark.asyncio
async def test_research_uses_agent_when_provided():
    """When agent is provided, always delegates to ResearchOrchestrator."""
    from tests.wiki.agents.test_base_agent import ConcreteAgent

    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(side_effect=[
        "sub q1\nsub q2",        # decompose
        "answer 1",              # answer_sub_question 1
        "answer 2",              # answer_sub_question 2
        "synthesized answer",    # synthesize
    ])
    mock_llm.complete_with_tools = AsyncMock(return_value={"tool_calls": None, "content": "done"})

    agent = ConcreteAgent(mock_llm, max_rounds=2)

    service = DeepResearchService(
        rag_engine=MagicMock(),
        llm=None,
        agent=agent,
    )
    result = await service.research(question="How does X work?")

    assert result["question"] == "How does X work?"
    assert len(result["sub_questions"]) == 2
    assert result["synthesis"] == "synthesized answer"
