import pytest
from unittest.mock import AsyncMock
from wiki.deep_research import DeepResearchService


@pytest.mark.asyncio
async def test_decompose_question():
    mock_ask = AsyncMock()
    mock_ask.ask_stream = AsyncMock()

    service = DeepResearchService(ask_service=mock_ask)
    questions = await service.decompose_question("How does authentication work end-to-end?")
    assert isinstance(questions, list)
    assert len(questions) >= 1


@pytest.mark.asyncio
async def test_research_returns_structured_result():
    mock_ask = AsyncMock()

    service = DeepResearchService(ask_service=mock_ask)
    result = await service.research(
        question="How does auth work?",
        repository="test-repo",
        business_id="default",
    )
    assert "question" in result
    assert "sub_questions" in result
    assert "synthesis" in result
