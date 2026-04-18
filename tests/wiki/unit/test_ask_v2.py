"""Unit tests for Ask v2: question type detection, graph-enhanced context, WikiAskService."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from wiki.ask import (
    GraphEnhancedContextCollector,
    WikiAskService,
    detect_question_type,
)
from wiki.search import SearchResponse, SearchResult


def _sr(
    page_path: str = "classes/Foo.md",
    title: str = "Foo",
    score: float = 0.9,
    snippet: str = "snippet text",
    source_locations: list | None = None,
) -> SearchResult:
    return SearchResult(
        page_path=page_path,
        title=title,
        score=score,
        snippet=snippet,
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


class TestDetectQuestionType:
    """Keyword-based classification (no LLM). Priority: relation > impact > flow > concept > general."""

    @pytest.mark.parametrize(
        ("question", "expected"),
        [
            ("Foo是什么", "concept"),
            ("什么是 Foo", "concept"),
            ("what is Foo", "concept"),
            ("What Is the module", "concept"),
            ("定义 Bar", "concept"),
            ("describe the handler", "concept"),
            ("DESCRIBE X", "concept"),
        ],
    )
    def test_concept_zh_en(self, question: str, expected: str) -> None:
        assert detect_question_type(question) == expected

    @pytest.mark.parametrize(
        ("question", "expected"),
        [
            ("怎么做部署", "flow"),
            ("流程是怎样的", "flow"),
            ("how does login work", "flow"),
            ("steps to build", "flow"),
            ("explain the process", "flow"),
            ("workflow for CI", "flow"),
        ],
    )
    def test_flow_zh_en(self, question: str, expected: str) -> None:
        assert detect_question_type(question) == expected

    @pytest.mark.parametrize(
        ("question", "expected"),
        [
            ("A和B的关系", "relation"),
            ("区别是什么", "relation"),
            ("X vs Y", "relation"),
            ("比较 Foo 和 Bar", "relation"),
            ("difference between A and B", "relation"),
            ("compare X to Y", "relation"),
            ("what is the difference between foo and bar", "relation"),
        ],
    )
    def test_relation_zh_en(self, question: str, expected: str) -> None:
        assert detect_question_type(question) == expected

    @pytest.mark.parametrize(
        ("question", "expected"),
        [
            ("这对性能有什么影响", "impact"),
            ("依赖哪些模块", "impact"),
            ("impact on latency", "impact"),
            ("does this affect caching", "impact"),
            ("what depends on Auth", "impact"),
        ],
    )
    def test_impact_zh_en(self, question: str, expected: str) -> None:
        assert detect_question_type(question) == expected

    def test_general_default(self) -> None:
        assert detect_question_type("") == "general"
        assert detect_question_type("random question about nothing specific") == "general"

    def test_relation_wins_over_concept_keywords(self) -> None:
        assert detect_question_type("what is the difference between A and B") == "relation"


class TestGraphEnhancedContextCollector:
    async def test_concept_includes_wiki_and_one_hop(self) -> None:
        calls: list[tuple[str, dict | None]] = []

        async def exec_q(cypher: str, params: dict | None = None) -> list[dict]:
            calls.append((cypher, params))
            if "WikiPage" in cypher and "content" in cypher:
                return [{"page_path": "classes/Foo.md", "title": "Foo", "content": "FULL WIKI BODY"}]
            if "CALLS|INHERITS|IMPORTS" in cypher and "*2..3" not in cypher and "shortestPath" not in cypher:
                if "caller)-[:CALLS" in cypher or "MATCH path = (caller)" in cypher:
                    return []
                return [{"rel_type": "CALLS", "from_name": "Foo", "to_name": "Bar"}]
            if "signature" in cypher or "docstring" in cypher:
                return [{"name": "Foo", "signature": "def foo()", "docstring": "doc"}]
            if "Module" in cypher and "overview" in cypher.lower():
                return [{"module": "mod", "summary": "overview"}]
            return []

        graph = AsyncMock()
        graph.execute_query = AsyncMock(side_effect=exec_q)
        collector = GraphEnhancedContextCollector(graph)
        out = await collector.collect(
            "my-repo",
            [_sr()],
            "concept",
            token_budget=8000,
        )
        assert "FULL WIKI BODY" in out
        assert "Foo" in out and "Bar" in out
        cy_text = " ".join(c[0] for c in calls)
        assert "WikiPage" in cy_text
        assert graph.execute_query.await_count >= 1

    async def test_flow_uses_callee_chain_query(self) -> None:
        async def exec_q(cypher: str, params: dict | None = None) -> list[dict]:
            if "WikiPage" in cypher:
                return [{"page_path": "x.md", "title": "X", "content": "wiki"}]
            if "*2..3" in cypher or ("CALLS*" in cypher and "2..3" in cypher):
                return [{"chain": ["a", "b", "c"]}]
            if "signature" in cypher:
                return []
            if "Module" in cypher:
                return []
            return []

        graph = AsyncMock()
        graph.execute_query = AsyncMock(side_effect=exec_q)
        collector = GraphEnhancedContextCollector(graph)
        out = await collector.collect("repo", [_sr()], "flow", token_budget=8000)
        assert "wiki" in out.lower() or "chain" in out.lower()
        cy_all = " ".join(str(call.args[0]) for call in graph.execute_query.await_args_list)
        assert "2..3" in cy_all or ("CALLS" in cy_all and "2..3" in cy_all)

    async def test_relation_uses_path_query(self) -> None:
        async def exec_q(cypher: str, params: dict | None = None) -> list[dict]:
            if "WikiPage" in cypher:
                return [{"page_path": "x.md", "title": "X", "content": "w"}]
            if "shortestPath" in cypher or ("*1..4" in cypher and "seed" in cypher):
                return [{"path": ["Foo", "Mid", "Bar"], "len": 2}]
            if "signature" in cypher:
                return []
            if "Module" in cypher:
                return []
            return []

        graph = AsyncMock()
        graph.execute_query = AsyncMock(side_effect=exec_q)
        collector = GraphEnhancedContextCollector(graph)
        out = await collector.collect(
            "repo",
            [
                _sr(title="Foo"),
                _sr(
                    title="Bar",
                    page_path="classes/Bar.md",
                    source_locations=[
                        {"entity": "Bar", "file_path": "src/bar.py", "start_line": 1},
                    ],
                ),
            ],
            "relation",
            token_budget=8000,
        )
        assert out
        cy_all = " ".join(str(call.args[0]) for call in graph.execute_query.await_args_list)
        assert "shortestPath" in cy_all or "*1..4" in cy_all

    async def test_impact_uses_callers_direction(self) -> None:
        async def exec_q(cypher: str, params: dict | None = None) -> list[dict]:
            if "WikiPage" in cypher:
                return [{"page_path": "x.md", "title": "X", "content": "w"}]
            if "caller" in cypher.lower() and "CALLS" in cypher:
                return [{"caller": "Root"}]
            if "signature" in cypher:
                return []
            if "Module" in cypher:
                return []
            return []

        graph = AsyncMock()
        graph.execute_query = AsyncMock(side_effect=exec_q)
        collector = GraphEnhancedContextCollector(graph)
        out = await collector.collect("repo", [_sr()], "impact", token_budget=8000)
        assert "Root" in out or "caller" in out.lower()
        cy_all = " ".join(str(call.args[0]) for call in graph.execute_query.await_args_list).lower()
        assert "caller" in cy_all

    async def test_general_matches_concept_style(self) -> None:
        async def exec_q(cypher: str, params: dict | None = None) -> list[dict]:
            if "WikiPage" in cypher:
                return [{"page_path": "a.md", "title": "T", "content": "full"}]
            return [{"rel_type": "X", "from_name": "A", "to_name": "B"}]

        graph = AsyncMock()
        graph.execute_query = AsyncMock(side_effect=exec_q)
        collector = GraphEnhancedContextCollector(graph)
        out = await collector.collect("repo", [_sr()], "general", token_budget=8000)
        assert "full" in out

    async def test_token_budget_truncates(self) -> None:
        long_content = "word " * 5000

        async def exec_q(cypher: str, params: dict | None = None) -> list[dict]:
            if "WikiPage" in cypher:
                return [{"page_path": "a.md", "title": "T", "content": long_content}]
            return []

        graph = AsyncMock()
        graph.execute_query = AsyncMock(side_effect=exec_q)
        collector = GraphEnhancedContextCollector(graph)
        out = await collector.collect("repo", [_sr()], "concept", token_budget=50)
        from wiki.ask import _estimate_tokens

        assert _estimate_tokens(out) <= 50


class TestWikiAskServiceGraphIntegration:
    async def test_with_graph_collects_and_passes_to_llm(self) -> None:
        search = AsyncMock()
        search.search = AsyncMock(
            return_value=SearchResponse(
                results=[_sr()],
                query_expansion={},
                total=1,
            )
        )
        captured: list[list[dict]] = []

        async def capture_llm(messages: list[dict], **kwargs: object) -> str:
            captured.append(messages)
            return "ok"

        llm = AsyncMock()
        llm.complete = AsyncMock(side_effect=capture_llm)

        async def exec_q(cypher: str, params: dict | None = None) -> list[dict]:
            if "WikiPage" in cypher:
                return [{"page_path": "classes/Foo.md", "title": "Foo", "content": "ENRICHED_WIKI_FULL"}]
            return []

        graph = AsyncMock()
        graph.execute_query = AsyncMock(side_effect=exec_q)

        svc = WikiAskService(search, llm, graph=graph)
        await svc.ask("repo", "Foo是什么?")

        assert captured
        blob = "\n".join(str(m.get("content", "")) for m in captured[0])
        assert "ENRICHED_WIKI_FULL" in blob
        graph.execute_query.assert_awaited()

    async def test_without_graph_backward_compatible_no_graph_queries(self) -> None:
        search = AsyncMock()
        search.search = AsyncMock(
            return_value=SearchResponse(
                results=[_sr(snippet="SNIPPET_ONLY")],
                query_expansion={},
                total=1,
            )
        )
        captured: list[list[dict]] = []

        async def capture_llm(messages: list[dict], **kwargs: object) -> str:
            captured.append(messages)
            return "ok"

        llm = AsyncMock()
        llm.complete = AsyncMock(side_effect=capture_llm)

        svc = WikiAskService(search, llm)
        await svc.ask("repo", "Foo是什么?")

        blob = "\n".join(str(m.get("content", "")) for m in captured[0])
        assert "SNIPPET_ONLY" in blob
