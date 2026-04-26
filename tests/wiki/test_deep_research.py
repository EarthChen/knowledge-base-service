import pytest
from unittest.mock import MagicMock
from wiki.deep_research import DeepResearchService


@pytest.mark.asyncio
async def test_decompose_question():
    service = DeepResearchService(ask_service=MagicMock())
    questions = await service.decompose_question("How does authentication work end-to-end?")
    assert isinstance(questions, list)
    assert len(questions) >= 1


@pytest.mark.asyncio
async def test_research_returns_structured_result():
    async def ask_stream(*, repository, question, **kwargs):  # noqa: ARG001
        yield {"event": "wiki-answer", "data": {"content": "x"}}
        yield {"event": "wiki-answer-complete", "data": {"conversation_id": "c"}}

    mock_ask = MagicMock()
    mock_ask.ask_stream = ask_stream

    service = DeepResearchService(ask_service=mock_ask)
    result = await service.research(
        question="How does auth work?",
        repository="test-repo",
        business_id="default",
    )
    assert "question" in result
    assert "sub_questions" in result
    assert "synthesis" in result


@pytest.mark.asyncio
async def test_research_calls_ask_stream_for_sub_questions():
    calls: list[tuple[str, str, str | None]] = []

    async def ask_stream(
        *, repository, question, scope=None, business_id=None, **kwargs
    ):  # noqa: ARG001
        calls.append((repository, question, business_id))
        yield {"event": "wiki-answer", "data": {"content": "sub-answer"}}
        yield {"event": "wiki-answer-complete", "data": {"conversation_id": "c1"}}

    mock_ask = MagicMock()
    mock_ask.ask_stream = ask_stream
    service = DeepResearchService(ask_service=mock_ask)
    result = await service.research("How does X work?", "test-repo", "default")
    assert len(calls) == 1
    assert calls[0][0] == "test-repo"
    assert calls[0][1] == "How does X work?"
    assert calls[0][2] == "default"
    assert result["sub_questions"][0]["answer"] == "sub-answer"
