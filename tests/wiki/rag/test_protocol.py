from __future__ import annotations

import pytest

from wiki.rag.protocol import Chunk, RetrievalScope, Source


def test_chunk_dataclass_fields() -> None:
    c = Chunk(
        content="body",
        source="wiki:/p",
        title="T",
        relevance=0.9,
        metadata={"k": "v"},
    )
    assert c.content == "body"
    assert c.metadata == {"k": "v"}


def test_retrieval_scope_repository_global() -> None:
    scope = RetrievalScope(scope_type="repository", repository="repo-a")
    assert scope.scope_type == "repository"
    assert scope.repository == "repo-a"
    assert scope.page_path is None


def test_source_for_citations() -> None:
    s = Source(kind="wiki", title="Auth", path="/auth", relevance=0.88, extra={"uid": "1"})
    assert s.kind == "wiki"
    assert s.path == "/auth"


def test_chunk_metadata_default_factory() -> None:
    c = Chunk(content="a", source="s", title="t", relevance=0.1)
    c.metadata["x"] = 1
    c2 = Chunk(content="a", source="s", title="t", relevance=0.1)
    assert c2.metadata == {}
