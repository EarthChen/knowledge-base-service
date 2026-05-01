"""Unit tests for wiki.ask — WikiAskService, ConversationStore, streaming Q&A."""

from __future__ import annotations

import json
import time
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from wiki.ask import (
    AskSource,
    ConversationHistory,
    ConversationStore,
    ConversationTurn,
    WikiAskService,
)
from wiki.rag.engine import IterativeRAGEngine
from wiki.rag.protocol import Chunk
from wiki.rag.wiki_retriever import WikiRetriever
from wiki.search import SearchResponse, SearchResult


def _llm_rag_json_answer(answer: str) -> str:
    return json.dumps(
        {
            "answer": answer,
            "gaps": [],
            "next_queries": [],
            "confidence": 0.9,
            "is_complete": True,
        }
    )


def _wiki_rag_engine(search: object, llm: object) -> IterativeRAGEngine:
    return IterativeRAGEngine(retriever=WikiRetriever(search), llm=llm)  # type: ignore[arg-type]


def _make_search_result(
    page_path: str = "classes/Foo.md",
    title: str = "Foo",
    score: float = 0.9,
    source_locations: list | None = None,
) -> SearchResult:
    return SearchResult(
        page_path=page_path,
        title=title,
        score=score,
        snippet="class Foo: ...",
        source_locations=source_locations
        or [
            {
                "entity": "Foo",
                "file_path": "src/foo.py",
                "start_line": 10,
            }
        ],
        context={"repository": "repo"},
    )


class TestConversationStore:
    """ConversationStore LRU, TTL, and persistence."""

    def test_store_create_generates_uuid(self) -> None:
        store = ConversationStore(max_conversations=200, max_turns=10, ttl_seconds=1800)
        h = store.create("my-repo", scope="mod/a")
        assert h.conversation_id
        uuid.UUID(h.conversation_id)
        assert h.repository == "my-repo"
        assert h.scope == "mod/a"
        assert h.turns == []

    def test_store_get_returns_none_for_unknown(self) -> None:
        store = ConversationStore()
        assert store.get("nonexistent-id") is None

    def test_store_save_and_retrieve(self) -> None:
        store = ConversationStore()
        h = store.create("r")
        h.turns.append(ConversationTurn(role="user", content="hi", timestamp=1.0))
        store.save(h)
        got = store.get(h.conversation_id)
        assert got is not None
        assert got.conversation_id == h.conversation_id
        assert len(got.turns) == 1
        assert got.turns[0].content == "hi"

    def test_store_ttl_eviction(self) -> None:
        store = ConversationStore(ttl_seconds=60)
        t0 = 1_000_000.0
        with patch("wiki.ask.time") as mock_time:
            mock_time.time.return_value = t0
            h = store.create("r")
            cid = h.conversation_id
            mock_time.time.return_value = t0 + 61
            assert store.get(cid) is None

    def test_store_lru_eviction(self) -> None:
        store = ConversationStore(max_conversations=5, max_turns=10, ttl_seconds=3600)
        first_id = store.create("r").conversation_id
        for _ in range(5):
            store.create("r")
        assert store.get(first_id) is None
        assert len(store._data) == 5


class TestWikiAskService:
    """WikiAskService hybrid context, streaming, conversation, errors."""

    async def test_ask_returns_streaming(self) -> None:
        search = AsyncMock()
        search.search = AsyncMock(
            return_value=SearchResponse(
                results=[_make_search_result()],
                query_expansion={},
                total=1,
            )
        )
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value=_llm_rag_json_answer("Answer text."))
        svc = WikiAskService(search, llm, rag_engine=_wiki_rag_engine(search, llm))
        events: list[dict] = []
        async for ev in svc.ask_stream("repo", "What is Foo?", mode="hybrid"):
            events.append(ev)

        kinds = [e["event"] for e in events]
        assert "wiki-answer" in kinds
        assert kinds.count("wiki-sources") == 1
        assert kinds[-1] == "wiki-answer-complete"
        complete = next(e for e in events if e["event"] == "wiki-answer-complete")
        assert "conversation_id" in complete["data"]
        assert "tokens_used" in complete["data"]

    async def test_ask_stream_emits_multiple_wiki_answer_deltas(self) -> None:
        search = AsyncMock()
        search.search = AsyncMock(
            return_value=SearchResponse(
                results=[_make_search_result()],
                query_expansion={},
                total=1,
            )
        )
        llm = AsyncMock()
        llm.complete = AsyncMock(
            return_value=_llm_rag_json_answer(" ".join(f"w{i}" for i in range(20)))
        )
        svc = WikiAskService(search, llm, rag_engine=_wiki_rag_engine(search, llm))
        answer_events = [
            e
            for e in [ev async for ev in svc.ask_stream("repo", "Q?", mode="hybrid")]
            if e.get("event") == "wiki-answer"
        ]
        assert len(answer_events) >= 2
        assert answer_events[-1]["data"]["content"].strip().endswith("w19")

    async def test_ask_includes_sources(self) -> None:
        sr = _make_search_result()
        search = AsyncMock()
        search.search = AsyncMock(
            return_value=SearchResponse(results=[sr], query_expansion={}, total=1)
        )
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value=_llm_rag_json_answer("ok"))
        rag = AsyncMock()
        rag.arun = AsyncMock(
            return_value={
                "current_draft": "ok",
                "accumulated_context": [
                    Chunk(
                        content="c",
                        source="wiki",
                        title="Foo",
                        relevance=0.9,
                        metadata={
                            "page_path": "classes/Foo.md",
                            "file_path": "src/foo.py",
                            "start_line": 10,
                        },
                    ),
                ],
                "sse_events": [],
                "round": 1,
                "confidence": 0.9,
            }
        )
        svc = WikiAskService(search, llm, rag_engine=rag)
        resp = await svc.ask("repo", "What is Foo?")
        assert len(resp.sources) >= 1
        assert resp.sources[0].file_path == "src/foo.py"
        assert resp.sources[0].wiki_page == "classes/Foo.md"

    async def test_ask_conversation_history(self) -> None:
        search = AsyncMock()
        search.search = AsyncMock(
            return_value=SearchResponse(results=[_make_search_result()], query_expansion={}, total=1)
        )
        captured: list[list[dict]] = []

        async def capture_complete(messages: list[dict], **kwargs: object) -> str:
            captured.append(messages)
            return _llm_rag_json_answer("reply")

        llm = AsyncMock()
        llm.complete = AsyncMock(side_effect=capture_complete)
        svc = WikiAskService(search, llm, rag_engine=_wiki_rag_engine(search, llm))

        r1 = await svc.ask("repo", "First question?")
        cid = r1.conversation_id

        await svc.ask("repo", "Follow-up?", conversation_id=cid)

        assert llm.complete.await_count >= 2
        assert len(captured) >= 2

    async def test_ask_conversation_ttl(self) -> None:
        search = AsyncMock()
        search.search = AsyncMock(
            return_value=SearchResponse(results=[_make_search_result()], query_expansion={}, total=1)
        )
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value=_llm_rag_json_answer("ok"))
        store = ConversationStore(ttl_seconds=60)
        svc = WikiAskService(
            search, llm, rag_engine=_wiki_rag_engine(search, llm), conversation_store=store
        )

        t0 = 2_000_000.0
        with patch("wiki.ask.time") as mock_time:
            mock_time.time.return_value = t0
            r1 = await svc.ask("repo", "Q1")
            old_cid = r1.conversation_id

            mock_time.time.return_value = t0 + 120
            r2 = await svc.ask("repo", "Q2", conversation_id=old_cid)

        assert r2.conversation_id != old_cid

    async def test_ask_max_turns(self) -> None:
        search = AsyncMock()
        search.search = AsyncMock(
            return_value=SearchResponse(results=[_make_search_result()], query_expansion={}, total=1)
        )
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value=_llm_rag_json_answer("ok"))
        store = ConversationStore(max_conversations=200, max_turns=10, ttl_seconds=1800)
        svc = WikiAskService(
            search, llm, rag_engine=_wiki_rag_engine(search, llm), conversation_store=store
        )

        r = await svc.ask("repo", "start")
        cid = r.conversation_id
        # Each ask appends user + assistant (2 turns); 6 rounds => 12 turns > max_turns (10).
        for i in range(5):
            await svc.ask("repo", f"follow{i}", conversation_id=cid)

        hist = store.get(cid)
        assert hist is not None
        assert len(hist.turns) <= 10

    async def test_ask_scoped_search(self) -> None:
        search = AsyncMock()
        search.search = AsyncMock(
            return_value=SearchResponse(results=[_make_search_result()], query_expansion={}, total=1)
        )
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value=_llm_rag_json_answer("ok"))
        rag = AsyncMock()
        rag.arun = AsyncMock(
            return_value={
                "current_draft": "ok",
                "accumulated_context": [],
                "sse_events": [],
                "round": 1,
                "confidence": 0.9,
            }
        )
        svc = WikiAskService(search, llm, rag_engine=rag)
        await svc.ask("repo", "Q", scope="src/auth")

        rag.arun.assert_awaited()
        scope = rag.arun.await_args.kwargs.get("scope")
        assert scope is not None
        assert scope.page_path == "src/auth"

    async def test_ask_hybrid_context(self) -> None:
        sr = _make_search_result(title="Bar", page_path="entities/Bar.md")
        search = AsyncMock()
        search.search = AsyncMock(
            return_value=SearchResponse(results=[sr], query_expansion={}, total=1)
        )
        captured: list[list[dict]] = []

        async def capture(messages: list[dict], **kwargs: object) -> str:
            captured.append(messages)
            return _llm_rag_json_answer("done")

        llm = AsyncMock()
        llm.complete = AsyncMock(side_effect=capture)
        svc = WikiAskService(search, llm, rag_engine=_wiki_rag_engine(search, llm))
        await svc.ask("repo", "Explain Bar")

        assert captured
        blob = "\n".join(m["content"] for m in captured[0])
        assert "Bar" in blob
        assert "class Foo" in blob or "Foo" in blob

    async def test_ask_no_llm_fallback(self) -> None:
        search = AsyncMock()
        search.search = AsyncMock(
            return_value=SearchResponse(results=[_make_search_result()], query_expansion={}, total=1)
        )
        llm = AsyncMock()
        llm.complete = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
        svc = WikiAskService(search, llm, rag_engine=_wiki_rag_engine(search, llm))
        resp = await svc.ask("repo", "Q?")
        assert resp.content
        assert "error" in resp.content.lower() or "unavailable" in resp.content.lower() or "could not" in resp.content.lower()

        events: list[dict] = []
        async for ev in svc.ask_stream("repo", "Q?"):
            events.append(ev)
        ans_events = [e for e in events if e["event"] == "wiki-answer"]
        assert ans_events
        text = ans_events[-1]["data"].get("content", "")
        assert text


class TestAskSourceModel:
    """Sanity check on AskSource dataclass."""

    def test_ask_source_fields(self) -> None:
        s = AskSource(
            entity="X",
            file_path="f.py",
            start_line=3,
            wiki_page="p.md",
            relevance_score=0.5,
        )
        assert s.entity == "X"
        assert s.start_line == 3
