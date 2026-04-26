import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_wiki_service_passes_rag_enabled():
    from wiki.service import WikiService

    graph = MagicMock()
    wiki_store = MagicMock()

    service = WikiService(
        graph=graph,
        llm=None,
        repository_exists=AsyncMock(return_value=True),
        wiki_store=wiki_store,
    )
    assert service._collector._rag_enabled is True
