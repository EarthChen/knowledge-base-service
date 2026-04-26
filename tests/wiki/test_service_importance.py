"""WikiService integration with wiki_store and importance scoring."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from tests.wiki_config_inject import wiki_service_injection


@pytest.mark.asyncio
async def test_wiki_service_creates_collector_with_wiki_store():
    """Verify that WikiService passes wiki_store to WikiDataCollector."""
    from wiki.service import WikiService

    graph = MagicMock()
    graph.find_children = AsyncMock(return_value=[])
    graph.find_edges = AsyncMock(return_value=[])
    graph.count_nodes = AsyncMock(return_value=0)

    wiki_store = MagicMock()

    service = WikiService(
        graph=graph,
        llm=None,
        repository_exists=AsyncMock(return_value=True),
        wiki_store=wiki_store,
        **wiki_service_injection(),
    )

    assert service._collector._wiki_store is wiki_store
