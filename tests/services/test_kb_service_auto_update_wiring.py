"""Verify KnowledgeBaseService wires wiki_auto_updater callback into IncrementalIndexer."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_kb_service_wires_auto_updater_to_indexer() -> None:
    """IncrementalIndexer created by KnowledgeBaseService has _wiki_auto_updater set."""
    from core.config import Settings
    from services.kb_service import KnowledgeBaseService
    from store.settings_store import SettingsStore

    settings = MagicMock(spec=Settings)
    settings.falkordb = MagicMock()
    settings.falkordb.password = ""
    settings.falkordb_password = ""
    settings.embedding = MagicMock()
    settings.embedding.dimension = 384
    settings.llm = MagicMock()
    settings.llm.enabled = False
    settings.hybrid_search = MagicMock()
    settings.hybrid_search.use_child_chunks = False
    settings.hybrid_search.child_chunk_window_chars = 512
    settings.hybrid_search.child_chunk_stride_chars = 256
    settings.hybrid_search.child_chunk_min_parent_chars = 256
    settings.hybrid_search.include_raw_docs_in_results = False
    settings.hybrid_search.query_expansion_enabled = False
    settings.hybrid_search.enable_bm25 = False
    settings.hybrid_search.bm25_weight = 0.3
    settings.rerank = MagicMock()
    settings.rerank.enabled = False
    settings.file_extensions = {"python": [".py"]}
    settings.supported_languages = ["python"]
    settings.exclude_dirs = []
    settings.wiki = MagicMock()
    settings.wiki.community_context_enabled = False

    store = AsyncMock()
    settings_store = AsyncMock(spec=SettingsStore)

    with patch("services.kb_service.EmbeddingGenerator") as mock_emb, \
         patch("services.kb_service.WikiSearchService"), \
         patch("services.kb_service.WikiService"), \
         patch("services.kb_service.WikiPipelineAdapter"), \
         patch("services.kb_service.KnowledgeBaseMCPHandler"):
        mock_emb.shared.return_value = MagicMock()

        svc = KnowledgeBaseService.from_components(
            store=store,
            settings=settings,
            settings_store=settings_store,
        )

        assert svc._incremental_indexer._wiki_auto_updater is not None
        assert svc._incremental_indexer._settings_store is settings_store


@pytest.mark.asyncio
async def test_auto_update_wiki_calls_business_wiki_generation() -> None:
    """_auto_update_wiki triggers generate_business_wiki instead of generate_incremental."""
    from services.kb_service import KnowledgeBaseService

    svc = MagicMock()
    svc._wiki_service = AsyncMock()
    svc._wiki_service.generate_business_wiki = AsyncMock(return_value={"status": "ok"})

    await KnowledgeBaseService._auto_update_wiki(svc, "my-repo")

    svc._wiki_service.generate_business_wiki.assert_awaited_once_with(
        business_id="default",
        incremental=True,
    )
    svc._wiki_service.generate_incremental.assert_not_awaited()


@pytest.mark.asyncio
async def test_auto_update_wiki_calls_business_wiki_generation() -> None:
    """_auto_update_wiki triggers generate_business_wiki instead of generate_incremental."""
    from services.kb_service import KnowledgeBaseService

    svc = MagicMock()
    svc._wiki_service = AsyncMock()
    svc._wiki_service.generate_business_wiki = AsyncMock(return_value={"status": "ok"})

    await KnowledgeBaseService._auto_update_wiki(svc, "my-repo")

    svc._wiki_service.generate_business_wiki.assert_awaited_once_with(
        business_id="default",
        incremental=True,
    )
    svc._wiki_service.generate_incremental.assert_not_awaited()
