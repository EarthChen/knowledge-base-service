"""Bounded concurrency for claim tracking during wiki persist."""

from __future__ import annotations

import asyncio
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


def _base_store_and_wiki_store() -> tuple[MagicMock, MagicMock]:
    async def exec_q(cypher: str, params: object | None = None) -> MagicMock:
        if "coalesce(w.content" in cypher:
            return MagicMock(data=[{"c": ""}])
        return MagicMock(data=[])

    store = MagicMock()
    store.persist_wiki_pages = AsyncMock(return_value=1)
    store.execute_query = AsyncMock(side_effect=exec_q)
    store.batch_set_node_embeddings = AsyncMock()

    wiki_store = MagicMock()
    wiki_store.next_claim_version = AsyncMock(return_value=1)
    wiki_store.find_or_create_wiki_claim = AsyncMock(return_value="claim-uid")
    wiki_store.find_wiki_claim_by_text = AsyncMock(return_value=None)
    wiki_store.set_wiki_claim_superseded = AsyncMock()
    wiki_store.set_wiki_page_supersedes = AsyncMock()
    return store, wiki_store


def _app_cfg(**updates: object) -> AppWikiFlags:
    base: dict[str, object] = {
        "confidence_scoring_enabled": False,
        "supersession_tracking_enabled": True,
    }
    base.update(updates)
    return AppWikiFlags().model_copy(update=base)


@pytest.mark.asyncio
async def test_claim_tracking_runs_extract_claims_concurrently(monkeypatch: pytest.MonkeyPatch) -> None:
    store, wiki_store = _base_store_and_wiki_store()
    lock = asyncio.Lock()
    state = {"inflight": 0, "peak": 0}

    async def fake_extract(*_a: object, **_k: object) -> list[object]:
        async with lock:
            state["inflight"] += 1
            state["peak"] = max(state["peak"], state["inflight"])
        await asyncio.sleep(0.06)
        async with lock:
            state["inflight"] -= 1
        return []

    monkeypatch.setattr("wiki.claim_extractor.extract_claims", fake_extract)
    mgen = MagicMock()
    mgen.generate_for_docs = AsyncMock(return_value=[[0.0, 0.0]])
    monkeypatch.setattr("wiki.service.EmbeddingGenerator.shared", lambda **_: mgen)
    monkeypatch.setattr("wiki.service.doc_dict_for_embedding", lambda _: {"title": "t", "content": "c"})

    llm = MagicMock()
    svc = WikiService(
        graph=MagicMock(),
        llm=llm,
        repository_exists=AsyncMock(return_value=True),
        store=store,
        wiki_store=wiki_store,
        wiki_config=_app_cfg(claim_tracking_concurrency=4),
        embedding_config=EmbeddingConfig(),
    )
    pages = [_page(f"p{i}.md", f"body-{i}") for i in range(8)]
    await svc._persist_pages_to_graph("r-conc", pages, language="en")
    assert state["peak"] >= 4, "sequential processing would keep peak at 1"


@pytest.mark.asyncio
async def test_claim_tracking_respects_configured_concurrency_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    store, wiki_store = _base_store_and_wiki_store()
    lock = asyncio.Lock()
    state = {"inflight": 0, "peak": 0}

    async def fake_extract(*_a: object, **_k: object) -> list[object]:
        async with lock:
            state["inflight"] += 1
            state["peak"] = max(state["peak"], state["inflight"])
        await asyncio.sleep(0.06)
        async with lock:
            state["inflight"] -= 1
        return []

    monkeypatch.setattr("wiki.claim_extractor.extract_claims", fake_extract)
    mgen = MagicMock()
    mgen.generate_for_docs = AsyncMock(return_value=[[0.0, 0.0]])
    monkeypatch.setattr("wiki.service.EmbeddingGenerator.shared", lambda **_: mgen)
    monkeypatch.setattr("wiki.service.doc_dict_for_embedding", lambda _: {"title": "t", "content": "c"})

    llm = MagicMock()
    cap = 2
    svc = WikiService(
        graph=MagicMock(),
        llm=llm,
        repository_exists=AsyncMock(return_value=True),
        store=store,
        wiki_store=wiki_store,
        wiki_config=_app_cfg(claim_tracking_concurrency=cap),
        embedding_config=EmbeddingConfig(),
    )
    pages = [_page(f"x{i}.md", f"c-{i}") for i in range(10)]
    await svc._persist_pages_to_graph("r-cap", pages, language="en")
    assert state["peak"] <= cap
    assert state["peak"] == cap


@pytest.mark.asyncio
async def test_supersession_disabled_skips_claim_tracking(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[None] = []

    async def fake_extract(*_a: object, **_k: object) -> list[object]:
        calls.append(None)
        return []

    monkeypatch.setattr("wiki.claim_extractor.extract_claims", fake_extract)
    store, wiki_store = _base_store_and_wiki_store()
    mgen = MagicMock()
    mgen.generate_for_docs = AsyncMock(return_value=[[0.0, 0.0]])
    monkeypatch.setattr("wiki.service.EmbeddingGenerator.shared", lambda **_: mgen)
    monkeypatch.setattr("wiki.service.doc_dict_for_embedding", lambda _: {"title": "t", "content": "c"})

    svc = WikiService(
        graph=MagicMock(),
        llm=MagicMock(),
        repository_exists=AsyncMock(return_value=True),
        store=store,
        wiki_store=wiki_store,
        wiki_config=_app_cfg(supersession_tracking_enabled=False),
        embedding_config=EmbeddingConfig(),
    )
    await svc._persist_pages_to_graph(
        "r-skip",
        [_page("a.md", "x"), _page("b.md", "y")],
        language="en",
    )
    assert calls == []


@pytest.mark.asyncio
async def test_claim_tracking_is_fail_soft_per_page(monkeypatch: pytest.MonkeyPatch) -> None:
    store, wiki_store = _base_store_and_wiki_store()

    async def fake_extract(_llm: object, content: str, _lang: str) -> list[object]:
        if "FAIL" in content:
            raise RuntimeError("simulated extract failure")
        return []

    monkeypatch.setattr("wiki.claim_extractor.extract_claims", fake_extract)
    mgen = MagicMock()
    mgen.generate_for_docs = AsyncMock(return_value=[[0.0, 0.0]])
    monkeypatch.setattr("wiki.service.EmbeddingGenerator.shared", lambda **_: mgen)
    monkeypatch.setattr("wiki.service.doc_dict_for_embedding", lambda _: {"title": "t", "content": "c"})

    svc = WikiService(
        graph=MagicMock(),
        llm=MagicMock(),
        repository_exists=AsyncMock(return_value=True),
        store=store,
        wiki_store=wiki_store,
        wiki_config=_app_cfg(claim_tracking_concurrency=3),
        embedding_config=EmbeddingConfig(),
    )
    pages = [
        _page("ok1.md", "ok content one"),
        _page("bad.md", "FAIL this page"),
        _page("ok2.md", "ok content two"),
    ]
    await svc._persist_pages_to_graph("r-soft", pages, language="en")
    assert wiki_store.next_claim_version.await_count == 2


@pytest.mark.asyncio
async def test_claim_tracking_still_persists_supersession_when_concurrent(monkeypatch: pytest.MonkeyPatch) -> None:
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

    llm = MagicMock()
    llm.generate = AsyncMock(
        side_effect=[
            json.dumps([{"claim_text": "X", "subject_entity": "E"}]),
            json.dumps([{"claim_text": "Y", "subject_entity": "E"}]),
        ],
    )
    mgen = MagicMock()
    mgen.generate_for_docs = AsyncMock(return_value=[[0.0, 0.0]])
    monkeypatch.setattr("wiki.service.EmbeddingGenerator.shared", lambda **_: mgen)
    monkeypatch.setattr("wiki.service.doc_dict_for_embedding", lambda _: {"title": "t", "content": "c"})

    svc = WikiService(
        graph=MagicMock(),
        llm=llm,
        repository_exists=AsyncMock(return_value=True),
        store=store,
        wiki_store=wiki_store,
        wiki_config=_app_cfg(claim_tracking_concurrency=5),
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


def test_app_wiki_flags_default_claim_tracking_concurrency() -> None:
    assert AppWikiFlags().claim_tracking_concurrency == 5
