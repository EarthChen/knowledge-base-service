"""Cross-repository aggregate hybrid search (Sprint A)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from api.mcp_server import KnowledgeBaseMCPHandler, MCP_TOOLS_MANIFEST


@pytest.mark.asyncio
async def test_single_repo_array_delegates_to_search_with_context() -> None:
    """repositories: [one] should match repository: same for hybrid path."""
    from query.hybrid_query import HybridQueryService

    hybrid = HybridQueryService(
        store=MagicMock(),
        semantic_svc=MagicMock(),
        graph_svc=MagicMock(),
    )
    hybrid.search_with_context = AsyncMock(
        return_value={
            "results": [{"name": "a", "score": 0.9}],
            "semantic_matches": [{"name": "a", "score": 0.9}],
            "total": 1,
            "offset": 0,
            "limit": 20,
            "graph_context": [],
            "query_text": "q",
            "confidence": 0.5,
            "no_results_reason": "",
        },
    )

    await hybrid.search_multi_repo(
        "q",
        ["repo-a"],
        k=3,
        offset=5,
        limit=10,
        entity_type="function",
    )

    hybrid.search_with_context.assert_awaited_once()
    call = hybrid.search_with_context.await_args
    assert call.kwargs["repository"] == "repo-a"
    assert call.kwargs["k"] == 3
    assert call.kwargs["offset"] == 5
    assert call.kwargs["limit"] == 10
    assert call.kwargs["entity_type"] == "function"


@pytest.mark.asyncio
async def test_multi_repo_parallel_merge_sort_and_sum_total() -> None:
    from query.hybrid_query import HybridQueryService

    hybrid = HybridQueryService(
        store=MagicMock(),
        semantic_svc=MagicMock(),
        graph_svc=MagicMock(),
    )

    async def fake_search(q: str, **kwargs: object) -> dict:
        repo = kwargs.get("repository")
        if repo == "repo-a":
            return {
                "results": [
                    {"name": "low", "type": "Function", "file": "a.py", "line": 1, "score": 0.3},
                    {"name": "mid", "type": "Function", "file": "b.py", "line": 2, "score": 0.5},
                ],
                "semantic_matches": [],
                "total": 2,
                "offset": 0,
                "limit": 500,
                "graph_context": [
                    {"name": "g1", "file": "x.py", "line": 1},
                ],
                "query_text": q,
                "confidence": 0.1,
                "no_results_reason": "",
            }
        if repo == "repo-b":
            return {
                "results": [
                    {"name": "high", "type": "Function", "file": "c.py", "line": 3, "rrf_score": 0.9},
                ],
                "semantic_matches": [],
                "total": 1,
                "offset": 0,
                "limit": 500,
                "graph_context": [
                    {"name": "g1", "file": "x.py", "line": 1},
                    {"name": "g2", "file": "y.py", "line": 2},
                ],
                "query_text": q,
                "confidence": 0.2,
                "no_results_reason": "",
            }
        raise AssertionError(f"unexpected repo {repo!r}")

    hybrid.search_with_context = AsyncMock(side_effect=fake_search)

    out = await hybrid.search_multi_repo(
        "query",
        ["repo-a", "repo-b"],
        k=5,
        offset=0,
        limit=10,
        sort_by="score",
        entity_type=None,
    )

    assert out["total"] == 3
    names = [m["name"] for m in out["results"]]
    assert names == ["high", "mid", "low"]
    gc = out["graph_context"]
    assert len(gc) == 2


@pytest.mark.asyncio
async def test_mcp_repositories_takes_precedence_over_repository() -> None:
    hybrid = AsyncMock()
    hybrid.search_with_context = AsyncMock(
        return_value={
            "results": [],
            "semantic_matches": [],
            "total": 0,
            "offset": 0,
            "limit": 20,
            "graph_context": [],
            "query_text": "x",
            "confidence": 0.0,
            "no_results_reason": "",
        },
    )
    hybrid.search_multi_repo = AsyncMock(
        return_value={
            "results": [],
            "semantic_matches": [],
            "total": 0,
            "offset": 0,
            "limit": 20,
            "graph_context": [],
            "query_text": "x",
            "confidence": 0.0,
            "no_results_reason": "",
        },
    )

    srv = KnowledgeBaseMCPHandler(
        hybrid_svc=hybrid,
        graph_svc=AsyncMock(),
        indexer=MagicMock(),
    )

    await srv.handle_rag_query(
        {
            "query": "x",
            "repository": "ignored",
            "repositories": ["repo-a", "repo-b"],
        },
    )

    hybrid.search_multi_repo.assert_awaited_once()
    assert hybrid.search_with_context.await_count == 0


@pytest.mark.asyncio
async def test_mcp_empty_repositories_falls_back_to_search_all() -> None:
    hybrid = AsyncMock()
    hybrid.search_with_context = AsyncMock(
        return_value={
            "results": [],
            "semantic_matches": [],
            "total": 0,
            "offset": 0,
            "limit": 20,
            "graph_context": [],
            "query_text": "x",
            "confidence": 0.0,
            "no_results_reason": "",
        },
    )

    srv = KnowledgeBaseMCPHandler(
        hybrid_svc=hybrid,
        graph_svc=AsyncMock(),
        indexer=MagicMock(),
    )

    await srv.handle_rag_query(
        {
            "query": "x",
            "repository": "would-filter",
            "repositories": [],
        },
    )

    hybrid.search_with_context.assert_awaited_once()
    kw = hybrid.search_with_context.await_args.kwargs
    assert kw.get("repository") is None


@pytest.mark.asyncio
async def test_mcp_repositories_validation_max_and_string_only() -> None:
    srv = KnowledgeBaseMCPHandler(
        hybrid_svc=AsyncMock(),
        graph_svc=AsyncMock(),
        indexer=MagicMock(),
    )

    err = await srv.handle_rag_query(
        {"query": "x", "repositories": [f"r{i}" for i in range(11)]},
    )
    assert "error" in err

    err2 = await srv.handle_rag_query(
        {"query": "x", "repositories": ["ok", 1]},
    )
    assert "error" in err2


def test_rag_query_manifest_includes_repositories() -> None:
    tool = next(t for t in MCP_TOOLS_MANIFEST if t["name"] == "rag_query")
    assert "repositories" in tool["inputSchema"]["properties"]
    props = tool["inputSchema"]["properties"]["repositories"]
    assert props["type"] == "array"
    assert props["items"] == {"type": "string"}


@pytest.mark.asyncio
async def test_offset_limit_applied_on_merged_results() -> None:
    from query.hybrid_query import HybridQueryService

    hybrid = HybridQueryService(
        store=MagicMock(),
        semantic_svc=MagicMock(),
        graph_svc=MagicMock(),
    )

    async def fake_search(q: str, **kwargs: object) -> dict:
        repo = kwargs.get("repository")
        rows = {
            "repo-a": [
                {"name": "a1", "type": "Function", "file": "a.py", "line": 1, "score": 0.9},
                {"name": "a2", "type": "Function", "file": "a.py", "line": 2, "score": 0.8},
            ],
            "repo-b": [
                {"name": "b1", "type": "Function", "file": "b.py", "line": 1, "score": 0.85},
            ],
        }
        return {
            "results": rows[repo],
            "semantic_matches": [],
            "total": len(rows[repo]),
            "offset": 0,
            "limit": 500,
            "graph_context": [],
            "query_text": q,
            "confidence": 0.1,
            "no_results_reason": "",
        }

    hybrid.search_with_context = AsyncMock(side_effect=fake_search)

    out = await hybrid.search_multi_repo(
        "q",
        ["repo-a", "repo-b"],
        offset=1,
        limit=2,
        sort_by="score",
    )

    assert out["total"] == 3
    assert len(out["results"]) == 2
    assert out["results"][0]["name"] == "b1"
    assert out["results"][1]["name"] == "a2"


def test_hybrid_search_request_repositories_validation() -> None:
    from pydantic import ValidationError

    from main import HybridSearchRequest

    req = HybridSearchRequest(query="x", repositories=[" a ", "b"])
    assert req.repositories == ["a", "b"]

    with pytest.raises(ValidationError):
        HybridSearchRequest(query="x", repositories=["a", "b", 3])


@pytest.mark.asyncio
async def test_multi_repo_partial_failure_returns_successful_results() -> None:
    """One repo fails, the other succeeds — results from the successful repo are returned."""
    from query.hybrid_query import HybridQueryService

    hybrid = HybridQueryService(
        store=MagicMock(),
        semantic_svc=MagicMock(),
        graph_svc=MagicMock(),
    )

    async def fake_search(q: str, **kwargs: object) -> dict:
        repo = kwargs.get("repository")
        if repo == "repo-fail":
            raise RuntimeError("connection error")
        return {
            "results": [
                {"name": "ok", "type": "Function", "file": "f.py", "line": 1, "score": 0.9, "uid": "u1"},
            ],
            "semantic_matches": [],
            "total": 1,
            "offset": 0,
            "limit": 500,
            "graph_context": [],
            "query_text": q,
            "confidence": 0.5,
            "no_results_reason": "",
        }

    hybrid.search_with_context = AsyncMock(side_effect=fake_search)

    out = await hybrid.search_multi_repo(
        "q",
        ["repo-fail", "repo-ok"],
        k=5,
    )

    assert len(out["results"]) == 1
    assert out["results"][0]["name"] == "ok"
    assert "errors" in out
    assert len(out["errors"]) == 1
    assert "repo-fail" in out["errors"][0]


@pytest.mark.asyncio
async def test_multi_repo_dedup_by_uid_not_name_file_line() -> None:
    """Two repos with same name+file+line but different uid should NOT be deduped."""
    from query.hybrid_query import HybridQueryService

    hybrid = HybridQueryService(
        store=MagicMock(),
        semantic_svc=MagicMock(),
        graph_svc=MagicMock(),
    )

    async def fake_search(q: str, **kwargs: object) -> dict:
        repo = kwargs.get("repository")
        return {
            "results": [
                {
                    "name": "main",
                    "type": "Function",
                    "file": "main.py",
                    "line": 1,
                    "score": 0.8,
                    "uid": f"uid-{repo}",
                    "repository": repo,
                },
            ],
            "semantic_matches": [],
            "total": 1,
            "offset": 0,
            "limit": 500,
            "graph_context": [],
            "query_text": q,
            "confidence": 0.5,
            "no_results_reason": "",
        }

    hybrid.search_with_context = AsyncMock(side_effect=fake_search)

    out = await hybrid.search_multi_repo(
        "q",
        ["repo-a", "repo-b"],
        k=10,
    )

    assert len(out["results"]) == 2, "Same name+file+line but different uid must NOT be deduped"
    uids = {m["uid"] for m in out["results"]}
    assert uids == {"uid-repo-a", "uid-repo-b"}
