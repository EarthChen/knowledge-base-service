from __future__ import annotations

import pytest

from wiki.rag.protocol import RetrievalScope
from wiki.rag.wiki_retriever import WikiRetriever


class _FakeSearch:
    def __init__(self) -> None:
        self.called: list[tuple[str, str]] = []

    async def search(
        self,
        repository: str,
        query: str,
        mode: str = "hybrid",
        limit: int = 10,
        min_score: float = 0.0,
        *,
        scope: str | None = None,
    ) -> object:
        self.called.append((repository, query))
        from wiki.search import SearchResponse, SearchResult

        return SearchResponse(
            results=[
                SearchResult(
                    page_path="/a",
                    title="A",
                    score=0.9,
                    snippet="hi",
                    source_locations=[],
                    context={},
                )
            ],
            query_expansion={},
            total=1,
        )


@pytest.mark.asyncio
async def test_wiki_retriever_maps_search_results_to_chunks() -> None:
    fake = _FakeSearch()
    r = WikiRetriever(fake, default_repository="repo1")
    scope = RetrievalScope(scope_type="repository", repository="repo1")
    chunks = await r.retrieve(["q1"], scope, limit=5)
    assert len(chunks) == 1
    assert chunks[0].title == "A"
    assert chunks[0].source.startswith("wiki:")
    assert ("repo1", "q1") in fake.called
