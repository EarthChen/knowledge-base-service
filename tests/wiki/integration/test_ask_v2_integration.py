"""Ask v2 integration tests — full pipeline with mocked GraphPort, SearchPort, LLMPort."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock

import pytest

from wiki.ask import ConversationStore, WikiAskService
from wiki.search import SearchResponse, SearchResult

REPO = "demo-repo"

# Short search snippet (typical FTS excerpt); enrichment must supply longer wiki body.
SHORT_SNIPPET = "x" * 240


@dataclass
class MockGraphResult:
    """Stand-in for graph driver result objects exposing `.data`."""

    data: list[dict[str, Any]]


class MockGraph:
    """Mock GraphPort returning predefined rows based on Cypher shape."""

    def __init__(self, *, fail: bool = False) -> None:
        self.queries: list[tuple[str, dict[str, Any] | None]] = []
        self.fail = fail

    async def execute_query(self, cypher: str, params: dict[str, Any] | None = None) -> MockGraphResult:
        self.queries.append((cypher, params))
        if self.fail:
            raise RuntimeError("graph unavailable")

        if "WikiPage" in cypher and "wp.content" in cypher:
            return MockGraphResult(
                data=[
                    {
                        "page_path": "classes/AuthService.md",
                        "title": "AuthService",
                        "content": "Full wiki page content for AuthService — not the 240-char search snippet.",
                    }
                ]
            )
        if "shortestPath" in cypher:
            return MockGraphResult(data=[{"len": 2, "path": ["AuthService", "CoreAuth", "UserService"]}])
        if "(caller)-[:CALLS*1..3]->(n)" in cypher or ("caller" in cypher and "*1..3" in cypher and "shortestPath" not in cypher):
            return MockGraphResult(data=[{"caller": "ApiGateway"}])
        if "MATCH path = (n)-[:CALLS*2..3]->(m)" in cypher or ("-[:CALLS*2..3]->" in cypher and "shortestPath" not in cypher):
            return MockGraphResult(data=[{"chain": ["login", "verify_credentials", "issue_session"]}])
        if (
            "MATCH (n)-[r:CALLS|INHERITS|IMPORTS]-(m)" in cypher
            or ("CALLS|INHERITS|IMPORTS" in cypher and "shortestPath" not in cypher and "*2..3" not in cypher and "(caller)" not in cypher)
        ):
            return MockGraphResult(
                data=[{"rel_type": "CALLS", "from_name": "AuthService", "to_name": "UserRepo"}]
            )
        if "signature" in cypher or "docstring" in cypher:
            return MockGraphResult(data=[])
        if "Module" in cypher and ("overview" in cypher.lower() or "summary" in cypher.lower()):
            return MockGraphResult(data=[])
        return MockGraphResult(data=[])


def _sr(
    *,
    page_path: str = "classes/AuthService.md",
    title: str = "AuthService",
    snippet: str = SHORT_SNIPPET,
    entity: str = "AuthService",
) -> SearchResult:
    return SearchResult(
        page_path=page_path,
        title=title,
        score=0.95,
        snippet=snippet,
        source_locations=[
            {
                "entity": entity,
                "name": entity,
                "file_path": "auth/service.py",
                "start_line": 1,
            }
        ],
        context={"repository": REPO},
    )


def _messages_blob(messages: list[dict[str, str]]) -> str:
    return "\n".join(str(m.get("content", "")) for m in messages)


@pytest.mark.asyncio
async def test_e2e_enriched_context_reaches_llm_and_not_only_snippet() -> None:
    captured: list[list[dict[str, str]]] = []

    async def capture_llm(messages: list[dict], **kwargs: object) -> str:
        captured.append(messages)
        return "Synthetic answer based on enriched wiki."

    search = AsyncMock()
    search.search = AsyncMock(
        return_value=SearchResponse(results=[_sr()], query_expansion={}, total=1)
    )
    llm = AsyncMock()
    llm.complete = AsyncMock(side_effect=capture_llm)
    graph = MockGraph()

    svc = WikiAskService(search, llm, graph=graph)
    await svc.ask(REPO, "AuthService 是什么", mode="hybrid")

    assert captured
    blob = _messages_blob(captured[0])
    assert "Full wiki page content for AuthService" in blob
    assert SHORT_SNIPPET not in blob

    cy = " ".join(q[0] for q in graph.queries)
    assert "WikiPage" in cy
    assert "CALLS|INHERITS|IMPORTS" in cy


@pytest.mark.asyncio
async def test_sse_event_sequence_and_payloads() -> None:
    async def llm_ok(messages: list[dict], **kwargs: object) -> str:
        return "alpha beta gamma"

    search = AsyncMock()
    search.search = AsyncMock(
        return_value=SearchResponse(results=[_sr()], query_expansion={}, total=1)
    )
    llm = AsyncMock()
    llm.complete = AsyncMock(side_effect=llm_ok)

    svc = WikiAskService(search, llm, graph=MockGraph())
    events: list[dict[str, Any]] = []
    async for ev in svc.ask_stream(REPO, "AuthService 是什么"):
        events.append(ev)

    answer_evts = [e for e in events if e.get("event") == "wiki-answer"]
    assert answer_evts, "expected at least one wiki-answer chunk"
    for e in answer_evts:
        data = e.get("data") or {}
        assert "content" in data and "delta" in data
        assert isinstance(data["content"], str) and isinstance(data["delta"], str)

    src_idx = next(i for i, e in enumerate(events) if e.get("event") == "wiki-sources")
    complete_idx = next(i for i, e in enumerate(events) if e.get("event") == "wiki-answer-complete")
    assert src_idx < complete_idx

    src = events[src_idx].get("data") or {}
    assert "sources" in src and isinstance(src["sources"], list)
    if src["sources"]:
        s0 = src["sources"][0]
        assert {"entity", "file_path", "start_line", "wiki_page", "relevance_score"} <= set(s0.keys())

    done = events[complete_idx].get("data") or {}
    assert "conversation_id" in done and str(done["conversation_id"])
    assert "tokens_used" in done


@pytest.mark.asyncio
async def test_question_type_concept_queries_wiki_and_one_hop() -> None:
    graph = MockGraph()
    captured: list[list[dict[str, str]]] = []

    async def cap(messages: list[dict], **kwargs: object) -> str:
        captured.append(messages)
        return "ok"

    search = AsyncMock()
    search.search = AsyncMock(
        return_value=SearchResponse(results=[_sr()], query_expansion={}, total=1)
    )
    llm = AsyncMock()
    llm.complete = AsyncMock(side_effect=cap)

    svc = WikiAskService(search, llm, graph=graph)
    await svc.ask(REPO, "AuthService 是什么", mode="hybrid")

    cy = " ".join(q[0] for q in graph.queries)
    assert "WikiPage" in cy
    assert "CALLS|INHERITS|IMPORTS" in cy
    assert "-[:CALLS*2..3]->" not in cy
    assert _messages_blob(captured[0]).count("AuthService") >= 1


@pytest.mark.asyncio
async def test_question_type_flow_queries_callee_chain() -> None:
    graph = MockGraph()
    search = AsyncMock()
    search.search = AsyncMock(
        return_value=SearchResponse(results=[_sr()], query_expansion={}, total=1)
    )
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value="flow answer")

    svc = WikiAskService(search, llm, graph=graph)
    await svc.ask(REPO, "用户登录的流程是怎样的", mode="hybrid")

    cy_all = " ".join(q[0] for q in graph.queries)
    assert "-[:CALLS*2..3]->" in cy_all or "CALLS*2..3" in cy_all


@pytest.mark.asyncio
async def test_question_type_impact_queries_callers() -> None:
    graph = MockGraph()
    search = AsyncMock()
    search.search = AsyncMock(
        return_value=SearchResponse(
            results=[_sr(entity="UserRepo", title="UserRepo", page_path="classes/UserRepo.md")],
            query_expansion={},
            total=1,
        )
    )
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value="impact")

    svc = WikiAskService(search, llm, graph=graph)
    resp = await svc.ask(REPO, "修改 UserRepo 会影响什么", mode="hybrid")

    cy_all = " ".join(q[0] for q in graph.queries)
    assert "(caller)-[:CALLS*1..3]->(n)" in cy_all
    assert resp.content == "impact"


@pytest.mark.asyncio
async def test_question_type_relation_queries_shortest_path() -> None:
    graph = MockGraph()
    search = AsyncMock()
    search.search = AsyncMock(
        return_value=SearchResponse(
            results=[
                _sr(title="AuthService", entity="AuthService"),
                SearchResult(
                    page_path="classes/UserService.md",
                    title="UserService",
                    score=0.9,
                    snippet=SHORT_SNIPPET,
                    source_locations=[
                        {"entity": "UserService", "file_path": "user/svc.py", "start_line": 2}
                    ],
                    context={},
                ),
            ],
            query_expansion={},
            total=2,
        )
    )
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value="Comparison done.")

    svc = WikiAskService(search, llm, graph=graph)
    await svc.ask(REPO, "AuthService 和 UserService 的区别", mode="hybrid")

    cy_all = " ".join(q[0] for q in graph.queries)
    assert "shortestPath" in cy_all


@pytest.mark.asyncio
async def test_conversation_history_second_turn_includes_prior_qa() -> None:
    store = ConversationStore(max_conversations=50, max_turns=10, ttl_seconds=3600)
    captured: list[list[dict[str, str]]] = []

    async def cap(messages: list[dict], **kwargs: object) -> str:
        captured.append(messages)
        return f"turn-{len(captured)}"

    search = AsyncMock()
    search.search = AsyncMock(
        return_value=SearchResponse(results=[_sr()], query_expansion={}, total=1)
    )
    llm = AsyncMock()
    llm.complete = AsyncMock(side_effect=cap)

    svc = WikiAskService(search, llm, conversation_store=store, graph=MockGraph())
    first = await svc.ask(REPO, "AuthService 是什么")
    cid = first.conversation_id

    captured.clear()
    await svc.ask(REPO, "再说详细点", conversation_id=cid)

    assert len(captured) == 1
    blob = _messages_blob(captured[0])
    assert "AuthService 是什么" in blob
    assert "turn-1" in blob


@pytest.mark.asyncio
async def test_backward_compatible_without_graph_uses_snippet_format() -> None:
    captured: list[list[dict[str, str]]] = []

    async def cap(messages: list[dict], **kwargs: object) -> str:
        captured.append(messages)
        return "ok"

    search = AsyncMock()
    search.search = AsyncMock(
        return_value=SearchResponse(results=[_sr(snippet="SNIPPET_MARK")], query_expansion={}, total=1)
    )
    llm = AsyncMock()
    llm.complete = AsyncMock(side_effect=cap)

    svc = WikiAskService(search, llm, graph=None)
    await svc.ask(REPO, "AuthService 是什么")

    assert "SNIPPET_MARK" in _messages_blob(captured[0])
    assert "Full wiki page content" not in _messages_blob(captured[0])


@pytest.mark.asyncio
async def test_graph_failure_falls_back_to_search_snippet() -> None:
    captured: list[list[dict[str, str]]] = []

    async def cap(messages: list[dict], **kwargs: object) -> str:
        captured.append(messages)
        return "fallback ok"

    search = AsyncMock()
    search.search = AsyncMock(
        return_value=SearchResponse(results=[_sr(snippet="FALLBACK_SNIPPET_BODY")], query_expansion={}, total=1)
    )
    llm = AsyncMock()
    llm.complete = AsyncMock(side_effect=cap)

    svc = WikiAskService(search, llm, graph=MockGraph(fail=True))
    await svc.ask(REPO, "AuthService 是什么")

    blob = _messages_blob(captured[0])
    assert "FALLBACK_SNIPPET_BODY" in blob
    assert "Snippet:" in blob or "FALLBACK" in blob


@pytest.mark.asyncio
async def test_llm_unavailable_returns_friendly_message() -> None:
    search = AsyncMock()
    search.search = AsyncMock(
        return_value=SearchResponse(results=[_sr()], query_expansion={}, total=1)
    )
    llm = AsyncMock()
    llm.complete = AsyncMock(side_effect=RuntimeError("upstream down"))

    svc = WikiAskService(search, llm, graph=MockGraph())
    resp = await svc.ask(REPO, "AuthService 是什么")

    assert "language model is unavailable" in resp.content.lower() or "unavailable" in resp.content.lower()
