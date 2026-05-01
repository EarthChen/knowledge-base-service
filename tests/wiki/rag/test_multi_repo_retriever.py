"""Tests for MultiRepoRetriever cross-repository search."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from wiki.rag.multi_repo_retriever import MultiRepoRetriever, _hybrid_result_to_chunks
from wiki.rag.protocol import Chunk, RetrievalScope


@pytest.mark.asyncio
async def test_global_scope_multi_repo_triggers_search_multi_repo() -> None:
    """Global scope with multiple registered repos calls search_multi_repo."""
    hybrid = AsyncMock()
    hybrid.search_multi_repo = AsyncMock(
        return_value={
            "semantic_matches": [
                {
                    "content": "from repo A",
                    "name": "FuncA",
                    "score": 0.9,
                    "file": "a.py",
                },
                {
                    "content": "from repo B",
                    "name": "ClassB",
                    "rrf_score": 0.8,
                    "file": "b.java",
                },
            ],
        },
    )
    hybrid.search_with_context = AsyncMock(
        return_value={"semantic_matches": [{"content": "single", "name": "X", "score": 0.7}]},
    )

    registry = MagicMock()
    registry.list_all.return_value = [
        {"repository": "repo-a", "git_url": "https://example.com/a"},
        {"repository": "repo-b", "git_url": "https://example.com/b"},
    ]

    retriever = MultiRepoRetriever(hybrid, repo_registry=registry)
    scope = RetrievalScope(scope_type="global")
    chunks = await retriever.retrieve(["how does auth work"], scope, limit=10)

    hybrid.search_multi_repo.assert_awaited_once()
    assert hybrid.search_multi_repo.await_args.args[0] == "how does auth work"
    assert hybrid.search_multi_repo.await_args.args[1] == ["repo-a", "repo-b"]
    hybrid.search_with_context.assert_not_awaited()

    assert len(chunks) >= 2
    assert any("FuncA" in c.title or "FuncA" in c.content for c in chunks)


@pytest.mark.asyncio
async def test_repository_scope_delegates_to_single_repo_search() -> None:
    """When scope.repository is set, use search_with_context (not multi-repo)."""
    hybrid = AsyncMock()
    hybrid.search_multi_repo = AsyncMock(
        return_value={
            "semantic_matches": [
                {"content": "multi", "name": "M", "score": 0.99},
            ],
        },
    )
    hybrid.search_with_context = AsyncMock(
        return_value={
            "semantic_matches": [
                {"content": "scoped", "name": "ScopedFn", "score": 0.75, "path": "x.py"},
            ],
        },
    )

    registry = MagicMock()
    registry.list_all.return_value = [
        {"repository": "repo-a", "git_url": "https://example.com/a"},
        {"repository": "repo-b", "git_url": "https://example.com/b"},
    ]

    retriever = MultiRepoRetriever(hybrid, repo_registry=registry)
    scope = RetrievalScope(scope_type="repository", repository="repo-a")
    chunks = await retriever.retrieve(["query"], scope, limit=10)

    hybrid.search_with_context.assert_awaited()
    hybrid.search_multi_repo.assert_not_awaited()
    kw = hybrid.search_with_context.await_args.kwargs
    assert kw.get("repository") == "repo-a"

    assert len(chunks) >= 1
    assert any("ScopedFn" in c.title or "scoped" in c.content for c in chunks)


@pytest.mark.asyncio
async def test_no_registered_repos_uses_single_search() -> None:
    """Empty registry falls back to search_with_context (no search_multi_repo)."""
    hybrid = AsyncMock()
    hybrid.search_multi_repo = AsyncMock(
        return_value={"semantic_matches": [{"content": "multi", "name": "M", "score": 0.9}]},
    )
    hybrid.search_with_context = AsyncMock(
        return_value={"semantic_matches": [{"content": "fallback", "name": "Y", "score": 0.6}]},
    )

    registry = MagicMock()
    registry.list_all.return_value = []

    retriever = MultiRepoRetriever(hybrid, repo_registry=registry)
    scope = RetrievalScope(scope_type="global")
    chunks = await retriever.retrieve(["query"], scope, limit=10)

    hybrid.search_with_context.assert_awaited()
    hybrid.search_multi_repo.assert_not_awaited()
    assert len(chunks) >= 1


@pytest.mark.asyncio
async def test_single_registered_repo_uses_single_search() -> None:
    """One registered repo uses single-repo path (not search_multi_repo)."""
    hybrid = AsyncMock()
    hybrid.search_multi_repo = AsyncMock(return_value={"semantic_matches": []})
    hybrid.search_with_context = AsyncMock(
        return_value={"semantic_matches": [{"content": "one repo", "name": "Z", "score": 0.5}]},
    )

    registry = MagicMock()
    registry.list_all.return_value = [{"repository": "only-one", "git_url": "https://x"}]

    retriever = MultiRepoRetriever(hybrid, repo_registry=registry)
    chunks = await retriever.retrieve(["q"], scope=RetrievalScope(scope_type="global"))

    hybrid.search_with_context.assert_awaited()
    hybrid.search_multi_repo.assert_not_awaited()
    assert len(chunks) >= 1


def test_hybrid_result_to_chunks() -> None:
    result = {
        "semantic_matches": [
            {
                "content": "test content",
                "name": "TestFunc",
                "score": 0.85,
                "file": "test.py",
                "title": "Titled",
            },
        ],
    }
    chunks = _hybrid_result_to_chunks(result)
    assert len(chunks) == 1
    assert isinstance(chunks[0], Chunk)
    assert chunks[0].source == "wiki"
    assert chunks[0].content == "test content"
    assert chunks[0].title == "Titled"
    assert chunks[0].relevance == 0.85
    assert chunks[0].metadata.get("path") == "test.py"


def test_hybrid_result_to_chunks_rrf_score_fallback() -> None:
    result = {
        "results": [
            {"summary": "via results key", "name": "N1", "rrf_score": 0.42, "path": "/p"},
        ],
    }
    chunks = _hybrid_result_to_chunks(result)
    assert len(chunks) == 1
    assert chunks[0].content == "via results key"
    assert chunks[0].relevance == 0.42
    assert chunks[0].metadata["path"] == "/p"
