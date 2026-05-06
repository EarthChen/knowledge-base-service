"""Tests for ``query.semantic_wiki_query``."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from query.semantic_wiki_query import SemanticSearchResult, SemanticWikiQuery, WikiSearchHit


@pytest.mark.asyncio
async def test_search_returns_semantic_result() -> None:
    mock_wiki = AsyncMock()
    node = MagicMock()
    node.properties = {"path": "wiki/meeting", "title": "Meeting", "content": "Meeting domain content"}
    mock_wiki.fulltext_wiki_search = AsyncMock(
        return_value=MagicMock(data=[{"node": node, "score": 0.9}]),
    )
    mock_wiki.graph_path_search = AsyncMock(return_value=MagicMock(data=[]))

    mock_graph = AsyncMock()
    mock_graph.execute_query = AsyncMock(
        return_value=MagicMock(
            data=[
                {
                    "name": "MeetingSvc",
                    "labels": ["Module"],
                    "file_path": "svc.java",
                    "summary": "Meeting service",
                    "repository": "repo",
                },
            ],
        ),
    )

    query = SemanticWikiQuery(mock_wiki, mock_graph)
    result = await query.search("meeting", "repo", limit=10)

    assert isinstance(result, SemanticSearchResult)
    assert result.total_count > 0


@pytest.mark.asyncio
async def test_search_without_graph_store() -> None:
    mock_wiki = AsyncMock()
    mock_wiki.fulltext_wiki_search = AsyncMock(return_value=MagicMock(data=[]))
    mock_wiki.graph_path_search = AsyncMock(return_value=MagicMock(data=[]))

    query = SemanticWikiQuery(mock_wiki, graph_store=None)
    result = await query.search("test", "repo")

    assert isinstance(result, SemanticSearchResult)
    assert result.entity_hits == []


def test_search_result_model() -> None:
    from query.semantic_wiki_query import EntitySearchHit

    hit = WikiSearchHit(
        page_path="wiki/test",
        title="Test",
        snippet="content",
        score=0.9,
        source="wiki_fulltext",
    )
    assert hit.page_path == "wiki/test"

    entity = EntitySearchHit(
        name="Svc",
        entity_type="Module",
        repository="r",
        file_path="f.java",
        summary="desc",
        score=0.8,
    )
    assert entity.name == "Svc"
