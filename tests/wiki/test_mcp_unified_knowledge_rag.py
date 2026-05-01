from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from wiki.mcp_tools import WikiMCPHandler
from wiki.rag.protocol import Chunk


@pytest.fixture
def mock_rag_engine():
    engine = AsyncMock()
    engine.arun = AsyncMock(
        return_value={
            "current_draft": "The authentication system uses JWT tokens...",
            "accumulated_context": [
                Chunk(content="jwt auth logic", source="wiki", title="auth.md", relevance=0.9),
            ],
            "sse_events": [],
            "round": 2,
            "confidence": 0.92,
        }
    )
    return engine


@pytest.mark.asyncio
async def test_unified_knowledge_query_uses_rag_engine(mock_rag_engine):
    handler = WikiMCPHandler(pipeline=MagicMock(), rag_engine=mock_rag_engine)
    result = await handler.handle_unified_knowledge_query(
        {
            "question": "How does authentication work?",
            "scope": "global",
            "max_rounds": 5,
        }
    )
    mock_rag_engine.arun.assert_called_once()
    assert "JWT tokens" in result["answer"]
    assert len(result["sources"]) > 0


@pytest.mark.asyncio
async def test_unified_knowledge_query_requires_question(mock_rag_engine):
    handler = WikiMCPHandler(pipeline=MagicMock(), rag_engine=mock_rag_engine)
    result = await handler.handle_unified_knowledge_query({"question": ""})
    assert "error" in result or "invalid_params" in str(result)
