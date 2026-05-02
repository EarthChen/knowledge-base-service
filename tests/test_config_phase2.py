from core.config import Settings


def test_wiki_rag_config_defaults():
    s = Settings(_env_file=None, falkordb={"host": "localhost", "port": 6379})
    assert s.wiki.rag_enabled is True
    assert s.wiki.rag_top_k == 5
    assert s.wiki.rag_min_score == 0.3
    assert s.wiki.rag_exclude_same_parent is True


def test_wiki_chunk_embedding_config_defaults():
    s = Settings(_env_file=None, falkordb={"host": "localhost", "port": 6379})
    assert s.wiki.chunk_embedding_batch_size == 64
    assert s.wiki.chunk_embedding_max_length == 512
