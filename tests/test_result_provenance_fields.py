"""Result provenance: commit_sha and indexed_at on semantic hits and code snippets."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from query.semantic_query import SemanticQueryService
from store.graph_queries import GraphQueryRepository


class _Node:
    def __init__(self, props: dict) -> None:
        self.properties = props


@pytest.mark.asyncio
async def test_search_by_label_includes_commit_sha_and_indexed_at(monkeypatch: pytest.MonkeyPatch) -> None:
    store = AsyncMock()
    emb = AsyncMock()
    emb.generate_for_query = AsyncMock(return_value=[[0.1] * 4])

    vec_row = (
        _Node({
            "name": "foo",
            "file": "f.py",
            "start_line": 1,
            "end_line": 5,
            "uid": "uid1",
            "docstring": "",
            "fqn": "x.foo",
            "signature": "",
            "commit_sha": "abc123",
            "indexed_at": "2026-01-01T00:00:00Z",
        }),
        0.95,
    )
    store.vector_search = AsyncMock(return_value=[vec_row])

    from store.schema import NodeLabel

    svc = SemanticQueryService(store, emb)
    result = await svc._search_by_label("q", NodeLabel.FUNCTION, k=5)

    assert len(result.matches) == 1
    m = result.matches[0]
    assert m.get("commit_sha") == "abc123"
    assert m.get("indexed_at") == "2026-01-01T00:00:00Z"


@pytest.mark.asyncio
async def test_get_code_snippet_includes_optional_provenance(monkeypatch: pytest.MonkeyPatch) -> None:
    store = AsyncMock()
    store.execute_query = AsyncMock(
        return_value=MagicMock(
            data=[
                {
                    "name": "n",
                    "file": "f.py",
                    "start_line": 1,
                    "end_line": 2,
                    "code_snippet": "x",
                    "signature": "",
                    "docstring": "",
                    "fqn": "",
                    "type": "Function",
                    "commit_sha": "deadbeef",
                    "indexed_at": None,
                },
            ],
        ),
    )

    repo = GraphQueryRepository(store)
    row = await repo.get_code_snippet("uid-x")

    assert row is not None
    assert row.get("commit_sha") == "deadbeef"
    assert row.get("indexed_at") is None
