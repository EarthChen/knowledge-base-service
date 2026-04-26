import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock
from wiki.agents_md_generator import AgentsMdGenerator


@pytest.mark.asyncio
async def test_generates_agents_md_content():
    mock_store = AsyncMock()
    mock_result = MagicMock()
    mock_result.data = [
        {"title": "AuthService", "page_path": "auth/AuthService", "type": "class"},
        {"title": "UserModel", "page_path": "models/UserModel", "type": "class"},
    ]
    mock_store.execute_query = AsyncMock(return_value=mock_result)
    
    gen = AgentsMdGenerator(mock_store)
    content = await gen.generate("test-repo", business_id="default")
    
    assert "# AGENTS.md" in content or "# Knowledge Base" in content
    assert "AuthService" in content
    assert "UserModel" in content


def test_empty_wiki_generates_minimal():
    mock_store = AsyncMock()
    mock_result = MagicMock()
    mock_result.data = []
    mock_store.execute_query = AsyncMock(return_value=mock_result)
    
    gen = AgentsMdGenerator(mock_store)
    content = asyncio.run(gen.generate("empty-repo"))
    assert len(content) > 0
