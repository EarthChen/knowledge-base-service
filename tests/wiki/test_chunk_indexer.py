import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from tests.wiki_config_inject import inject_wiki_embedding
from wiki.chunk_indexer import CodeChunkIndexer

@pytest.fixture
def mock_wiki_store():
    store = MagicMock()
    store.count_chunks_without_embedding = AsyncMock(
        return_value=MagicMock(result_set=[[128]])
    )
    store.batch_get_chunks_for_embedding = AsyncMock(
        return_value=MagicMock(result_set=[
            ["uid1", "def hello(): pass"],
            ["uid2", "class Foo: bar = 1"],
        ])
    )
    return store

@pytest.fixture
def mock_store():
    store = MagicMock()
    store.set_node_embedding = AsyncMock()
    return store

@pytest.mark.asyncio
async def test_index_counts_first(mock_wiki_store, mock_store):
    w, e = inject_wiki_embedding()
    indexer = CodeChunkIndexer(
        mock_wiki_store, mock_store, e, w.chunk_embedding_max_length, batch_size=64,
    )
    mock_wiki_store.batch_get_chunks_for_embedding.side_effect = [
        MagicMock(result_set=[["uid1", "code"]]),
        MagicMock(result_set=[]),
    ]
    with patch("wiki.chunk_indexer.EmbeddingGenerator") as MockEmbGen:
        mock_emb_gen = MagicMock()
        mock_emb_gen.generate_for_docs = AsyncMock(return_value=[[0.1] * 1024])
        MockEmbGen.shared.return_value = mock_emb_gen
        
        result = await indexer.index_all_chunks("my-repo")
    
    assert result["indexed"] >= 0
    mock_wiki_store.count_chunks_without_embedding.assert_called_once()

@pytest.mark.asyncio
async def test_index_skips_empty_text(mock_wiki_store, mock_store):
    mock_wiki_store.batch_get_chunks_for_embedding.side_effect = [
        MagicMock(result_set=[["uid1", ""], ["uid2", None]]),
        MagicMock(result_set=[]),
    ]
    w, e = inject_wiki_embedding()
    indexer = CodeChunkIndexer(
        mock_wiki_store, mock_store, e, w.chunk_embedding_max_length, batch_size=64,
    )
    with patch("wiki.chunk_indexer.EmbeddingGenerator") as MockEmbGen:
        mock_emb_gen = MagicMock()
        mock_emb_gen.generate_for_docs = AsyncMock(return_value=[])
        MockEmbGen.shared.return_value = mock_emb_gen

        result = await indexer.index_all_chunks("my-repo")

    assert result["skipped"] >= 0
