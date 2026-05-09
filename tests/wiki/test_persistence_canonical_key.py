import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_persist_pages_includes_canonical_key():
    from wiki.persistence import WikiPagePersistence
    from wiki.models import EnrichmentLevel, PageType, WikiPage, WikiPageMetadata

    mock_store = AsyncMock()
    mock_store.persist_wiki_pages = AsyncMock()
    mock_store.execute_query = AsyncMock(return_value=MagicMock(data=[]))

    mock_graph = AsyncMock()
    mock_wiki_store = AsyncMock()

    mock_cfg = MagicMock()
    mock_cfg.supersession_tracking_enabled = False
    mock_cfg.confidence_scoring_enabled = False

    mock_emb_cfg = MagicMock()

    persistence = WikiPagePersistence(
        store=mock_store,
        graph=mock_graph,
        wiki_store=mock_wiki_store,
        wiki_cfg=mock_cfg,
        embedding_cfg=mock_emb_cfg,
    )

    page = WikiPage(
        path="test-page",
        title="Test Page",
        content="# Test",
        page_type=PageType.MODULE_OVERVIEW,
        diagrams=[],
        source_locations=[],
        metadata=WikiPageMetadata(
            node_count=1,
            edge_count=0,
            generation_mode="business",
            enrichment_level=EnrichmentLevel.BASE,
        ),
    )
    page.canonical_key = "src-auth-login"

    with patch.object(persistence, "_store") as patched_store:
        patched_store.persist_wiki_pages = AsyncMock()
        patched_store.execute_query = AsyncMock(return_value=MagicMock(data=[]))

        await persistence.persist_pages_to_graph(
            "test-repo",
            [page],
            language="zh",
            skip_claim_tracking=True,
        )

        if patched_store.persist_wiki_pages.called:
            call_args = patched_store.persist_wiki_pages.call_args
            page_dicts = call_args[0][1]
            assert any("canonical_key" in pd for pd in page_dicts)
            assert page_dicts[0]["canonical_key"] == "src-auth-login"
