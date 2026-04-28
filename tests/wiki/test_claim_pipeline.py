"""Claim supersession during wiki persist (integration-style with mocks)."""

from __future__ import annotations

import json
from unittest.mock import ANY, AsyncMock, MagicMock

import pytest

from config import AppWikiFlags, EmbeddingConfig
from wiki.models import PageType, WikiPage, WikiPageMetadata
from wiki.service import WikiService


def _page(path: str, content: str) -> WikiPage:
    return WikiPage(
        path=path,
        title="T",
        page_type=PageType.CLASS_DETAIL,
        content=content,
        diagrams=[],
        source_locations=[],
        metadata=WikiPageMetadata(
            node_count=0,
            edge_count=0,
            generation_mode="structure",
            fallback_tier=None,
        ),
    )


@pytest.mark.asyncio
async def test_supersession_creates_claim_history(monkeypatch: pytest.MonkeyPatch) -> None:
    async def exec_q(cypher: str, params: object | None = None) -> MagicMock:
        if "coalesce(w.content" in cypher:
            return MagicMock(data=[{"c": "previous"}])
        if "max(h.version" in cypher:
            return MagicMock(data=[{"m": 0}])
        return MagicMock(data=[])

    store = MagicMock()
    store.persist_wiki_pages = AsyncMock(return_value=1)
    store.execute_query = AsyncMock(side_effect=exec_q)
    store.batch_set_node_embeddings = AsyncMock()

    wiki_store = MagicMock()
    wiki_store.next_claim_version = AsyncMock(return_value=1)
    wiki_store.create_wiki_claim_history = AsyncMock()

    async def _find_by_text(page_uid: str, text: str) -> str | None:
        if (text or "").strip() == "X":
            return "old-uid"
        return None

    async def _find_or_create(
        page_uid: str,
        claim_text: str,
        version: int,
        *,
        new_claim_uid: str,
        created_at: int,
    ) -> str:
        t = (claim_text or "").strip()
        existing = await _find_by_text(page_uid, t)
        if existing:
            return existing
        await wiki_store.create_wiki_claim_history(
            new_claim_uid,
            page_uid,
            t,
            version,
            superseded_by=None,
            created_at=created_at,
            superseded_at=None,
        )
        return new_claim_uid

    wiki_store.find_wiki_claim_by_text = AsyncMock(side_effect=_find_by_text)
    wiki_store.find_or_create_wiki_claim = AsyncMock(side_effect=_find_or_create)
    wiki_store.set_wiki_claim_superseded = AsyncMock()
    wiki_store.set_wiki_page_supersedes = AsyncMock()
    mgen = MagicMock()
    mgen.generate_for_docs = AsyncMock(return_value=[[0.0, 0.0]])
    monkeypatch.setattr("wiki.service.EmbeddingGenerator.shared", lambda **_: mgen)
    monkeypatch.setattr("wiki.service.doc_dict_for_embedding", lambda _: {"title": "t", "content": "c"})

    llm = MagicMock()
    llm.generate = AsyncMock(
        side_effect=[
            json.dumps([{"claim_text": "X", "subject_entity": "E"}]),  # old
            json.dumps([{"claim_text": "Y", "subject_entity": "E"}]),  # new
        ],
    )
    app_cfg = AppWikiFlags().model_copy(
        update={
            "confidence_scoring_enabled": False,
            "supersession_tracking_enabled": True,
        },
    )

    async def _exists(_: str) -> bool:
        return True

    svc = WikiService(
        graph=MagicMock(),
        llm=llm,
        repository_exists=_exists,
        store=store,
        wiki_store=wiki_store,
        wiki_config=app_cfg,
        embedding_config=EmbeddingConfig(),
    )
    await svc._persist_pages_to_graph("r1", [_page("a.md", "new body")], language="en")
    assert wiki_store.create_wiki_claim_history.await_count == 1
    wiki_store.create_wiki_claim_history.assert_awaited_with(
        ANY,
        "WikiPage:r1:a.md",
        "Y",
        1,
        superseded_by=None,
        created_at=ANY,
        superseded_at=None,
    )
    wiki_store.set_wiki_claim_superseded.assert_awaited()
