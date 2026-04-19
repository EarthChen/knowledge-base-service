"""Wiki FTS repository scoping: Cypher, params, and cross-repo filtering."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from wiki.search import WikiSearchService, _fts_cypher


def test_fts_cypher_includes_repository_parameter() -> None:
    cy = _fts_cypher()
    assert "$repository" in cy
    assert "node.repository" in cy


@pytest.mark.asyncio
async def test_fts_path_passes_repository_in_execute_query_params() -> None:
    graph = AsyncMock()
    graph.execute_query = AsyncMock(return_value=MagicMock(data=[]))
    vector = AsyncMock()
    vector.search_all = AsyncMock(return_value=[])
    fts = AsyncMock()
    fts.execute_query = AsyncMock(return_value=MagicMock(data=[]))

    svc = WikiSearchService(graph, vector, fts)
    await svc.search("my-repo", "auth login", mode="keyword", limit=5)

    fts.execute_query.assert_awaited()
    _cy, params = fts.execute_query.call_args[0]
    assert params is not None
    assert params.get("repository") == "my-repo"
    assert "text" in params
    assert "limit" in params


@pytest.mark.asyncio
async def test_fts_multiple_repos_mock_only_requested_repo_in_results() -> None:
    graph = AsyncMock()
    graph.execute_query = AsyncMock(return_value=MagicMock(data=[]))
    vector = AsyncMock()
    vector.search_all = AsyncMock(return_value=[])

    fts = AsyncMock()

    async def fts_execute(cypher: str, params: dict | None = None) -> MagicMock:
        p = params or {}
        assert p.get("repository") == "repo-a"
        assert "$repository" in cypher
        assert "node.repository" in cypher
        # Simulate DB applying WHERE node.repository = $repository on a wider FTS hit set.
        raw = [
            {
                "node": MagicMock(
                    properties={
                        "path": "classes/Keep.md",
                        "title": "Keep",
                        "content": "alpha beta",
                        "repository": "repo-a",
                    }
                ),
                "score": 0.9,
            },
            {
                "node": MagicMock(
                    properties={
                        "path": "classes/Other.md",
                        "title": "Other",
                        "content": "alpha beta gamma",
                        "repository": "repo-b",
                    }
                ),
                "score": 0.85,
            },
        ]
        want = p.get("repository")
        data = [r for r in raw if r["node"].properties.get("repository") == want]
        return MagicMock(data=data)

    fts.execute_query = AsyncMock(side_effect=fts_execute)

    svc = WikiSearchService(graph, vector, fts)
    resp = await svc.search("repo-a", "alpha beta", mode="keyword", limit=10)
    paths = {r.page_path for r in resp.results}
    assert paths == {"classes/Keep.md"}
    assert "classes/Other.md" not in paths
