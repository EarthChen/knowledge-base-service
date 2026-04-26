import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from store.schema import GraphNode, NodeLabel
from tests.wiki_config_inject import inject_wiki_embedding
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
    result.result_set = []
    store.find_chunks_by_parent_uid = AsyncMock(return_value=result)
    store.vector_search_chunks = AsyncMock(
        return_value=MagicMock(
            result_set=[
                ["related code", "src/related.py", 1, 5, "Class:r.py:R:1", "Related", 0.8],
            ]
        )
    )
    return store


@pytest.mark.asyncio
async def test_collect_includes_related_chunks(mock_graph_port, mock_wiki_store):
    with patch("wiki.chunk_retriever.ChunkRetriever") as MockRetriever:
        from wiki.models import ChunkSnippet

        mock_retriever_instance = MagicMock()
        mock_retriever_instance.retrieve = AsyncMock(
            return_value=[
                ChunkSnippet(
                    text="related code",
                    file_path="src/related.py",
                    score=0.8,
                    parent_name="Related",
                    parent_uid="Class:r.py:R:1",
                ),
            ]
        )
        MockRetriever.return_value = mock_retriever_instance

        w, e = inject_wiki_embedding()
        collector = WikiDataCollector(
            mock_graph_port, w, e, wiki_store=mock_wiki_store, rag_enabled=True,
        )
        node = GraphNode(
            label=NodeLabel.CLASS,
            uid="Class:f.py:Foo:1",
            properties={
                "name": "Foo",
                "file": "src/foo.py",
                "start_line": 1,
                "end_line": 50,
            },
        )
        page_data = await collector.collect("my-repo", node)

    assert len(page_data.related_chunks) > 0
    assert page_data.related_chunks[0].parent_name == "Related"


@pytest.mark.asyncio
async def test_collect_without_rag_has_empty_chunks(mock_graph_port):
    w, e = inject_wiki_embedding()
    collector = WikiDataCollector(mock_graph_port, w, e, rag_enabled=False)
    node = GraphNode(
        label=NodeLabel.CLASS,
        uid="Class:f.py:Foo:1",
        properties={
            "name": "Foo",
            "file": "src/foo.py",
            "start_line": 1,
            "end_line": 50,
        },
    )
    page_data = await collector.collect("my-repo", node)
    assert page_data.related_chunks == []
