import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from wiki.chunk_retriever import ChunkRetriever
from wiki.models import ChunkSnippet
from store.schema import GraphNode, NodeLabel


@pytest.fixture
def mock_wiki_store():
    store = MagicMock()
    store.vector_search_chunks = AsyncMock(return_value=MagicMock(result_set=[
        ["def hello(): pass", "src/main.py", 1, 5, "Class:main.py:Main:1", "Main", 0.85],
        ["class Foo: bar = 1", "src/foo.py", 10, 15, "Class:foo.py:Foo:1", "Foo", 0.72],
    ]))
    return store


def _make_node(uid: str = "Class:f.py:Svc:1", name: str = "Svc") -> GraphNode:
    return GraphNode(
        label=NodeLabel.CLASS, uid=uid,
        properties={"name": name, "fqn": f"pkg.{name}", "signature": f"class {name}:"},
    )


@pytest.mark.asyncio
async def test_retrieve_returns_chunk_snippets(mock_wiki_store):
    with patch("wiki.chunk_retriever.EmbeddingGenerator") as MockEmbGen:
        mock_emb_gen = MagicMock()
        mock_emb_gen.generate_for_docs = AsyncMock(return_value=[[0.1] * 1024])
        MockEmbGen.shared.return_value = mock_emb_gen

        retriever = ChunkRetriever(mock_wiki_store)
        node = _make_node()
        results = await retriever.retrieve(node, "my-repo")

    assert len(results) == 2
    assert all(isinstance(r, ChunkSnippet) for r in results)
    assert results[0].score >= results[1].score


@pytest.mark.asyncio
async def test_retrieve_excludes_same_parent(mock_wiki_store):
    with patch("wiki.chunk_retriever.EmbeddingGenerator") as MockEmbGen:
        mock_emb_gen = MagicMock()
        mock_emb_gen.generate_for_docs = AsyncMock(return_value=[[0.1] * 1024])
        MockEmbGen.shared.return_value = mock_emb_gen

        retriever = ChunkRetriever(mock_wiki_store, exclude_same_parent=True)
        node = _make_node(uid="Class:main.py:Main:1")
        results = await retriever.retrieve(node, "my-repo")

    assert len(results) == 1
    assert results[0].parent_name == "Foo"


@pytest.mark.asyncio
async def test_retrieve_filters_by_min_score(mock_wiki_store):
    with patch("wiki.chunk_retriever.EmbeddingGenerator") as MockEmbGen:
        mock_emb_gen = MagicMock()
        mock_emb_gen.generate_for_docs = AsyncMock(return_value=[[0.1] * 1024])
        MockEmbGen.shared.return_value = mock_emb_gen

        retriever = ChunkRetriever(mock_wiki_store, min_score=0.80)
        node = _make_node()
        results = await retriever.retrieve(node, "my-repo")

    assert len(results) == 1
    assert results[0].score >= 0.80
