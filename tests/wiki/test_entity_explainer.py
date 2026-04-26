import pytest
from unittest.mock import AsyncMock, MagicMock
from wiki.entity_explainer import EntityExplainer


@pytest.mark.asyncio
async def test_explain_found_entity():
    mock_graph = AsyncMock()
    entity_result = MagicMock()
    entity_result.data = [{"name": "AuthService", "fqn": "auth.AuthService", "type": "class", "signature": "class AuthService", "docstring": "Handles auth", "file": "auth.py", "start_line": 10}]

    rel_result = MagicMock()
    rel_result.data = [{"rel_type": "CALLS", "other_name": "TokenValidator", "other_type": "class"}]

    wiki_result = MagicMock()
    wiki_result.data = [{"title": "AuthService", "content": "# AuthService\nHandles authentication.", "page_path": "auth/AuthService"}]

    mock_graph.execute_query = AsyncMock(side_effect=[entity_result, rel_result, wiki_result])

    explainer = EntityExplainer(mock_graph)
    result = await explainer.explain("test-repo", "AuthService")

    assert result["found"] is True
    assert result["entity"]["name"] == "AuthService"
    assert len(result["relationships"]) == 1
    assert result["wiki_page"]["title"] == "AuthService"


@pytest.mark.asyncio
async def test_explain_not_found():
    mock_graph = AsyncMock()
    empty_result = MagicMock()
    empty_result.data = []
    mock_graph.execute_query = AsyncMock(return_value=empty_result)

    explainer = EntityExplainer(mock_graph)
    result = await explainer.explain("test-repo", "NonExistent")

    assert result["found"] is False
