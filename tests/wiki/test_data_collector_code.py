import pytest
from unittest.mock import AsyncMock, MagicMock

from store.schema import GraphNode, NodeLabel
from wiki.data_collector import WikiDataCollector


@pytest.fixture
def mock_graph_port():
    port = MagicMock()
    port.find_edges = AsyncMock(return_value=[])
    port.find_children = AsyncMock(return_value=[])
    return port


@pytest.fixture
def mock_wiki_store():
    store = MagicMock()
    result = MagicMock()
    result.result_set = [["print('hello')", "src/main.py", 1, 5, 0]]
    store.find_chunks_by_parent_uid = AsyncMock(return_value=result)
    return store


@pytest.mark.asyncio
async def test_collect_includes_code_snippets(mock_graph_port, mock_wiki_store):
    collector = WikiDataCollector(mock_graph_port, wiki_store=mock_wiki_store)
    node = GraphNode(
        label=NodeLabel.CLASS,
        uid="Class:f.py:Foo:1",
        properties={"name": "Foo", "file": "src/foo.py", "start_line": 1, "end_line": 50},
    )
    page_data = await collector.collect("my-repo", node, code_budget=8000)

    assert hasattr(page_data, "code_snippets")
    assert len(page_data.code_snippets) > 0
    assert page_data.code_snippets[0].origin == "chunk"


@pytest.mark.asyncio
async def test_collect_without_wiki_store_has_empty_snippets(mock_graph_port):
    """When wiki_store is None (backward compatible), code_snippets is empty."""
    collector = WikiDataCollector(mock_graph_port)
    node = GraphNode(
        label=NodeLabel.CLASS,
        uid="Class:f.py:Foo:1",
        properties={"name": "Foo", "file": "src/foo.py", "start_line": 1, "end_line": 50},
    )
    page_data = await collector.collect("my-repo", node)

    assert page_data.code_snippets == []
