import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock

from wiki.agents_md_generator import AgentsMdGenerator


class _Result:
    def __init__(self, data):
        self.data = data


class _FakeGraph:
    def __init__(self, page_rows, stats_rows):
        self._page_rows = page_rows
        self._stats = stats_rows
        self.queries = []

    async def execute_query(self, cypher, params=None):
        self.queries.append((cypher, params or {}))
        if "count(wp)" in cypher or "avg(" in cypher:
            return _Result(self._stats)
        return _Result(self._page_rows)


@pytest.mark.asyncio
async def test_agents_includes_knowledge_map_pointer():
    pages = [
        {
            "title": "A",
            "page_path": "m/x.md",
            "type": "module_overview",
        },
    ]
    stats = [{"n": 1, "avg_conf": 0.8}]
    g = _FakeGraph(pages, stats)
    gen = AgentsMdGenerator(g)
    md = await gen.generate("r1", "default")
    assert "Knowledge at a glance" in md
    assert "wiki_get_snapshot" in md
    assert "- **Pages:** 1" in md
    assert "0.80" in md


@pytest.mark.asyncio
async def test_generates_agents_md_content():
    page_rows = [
        {"title": "AuthService", "page_path": "auth/AuthService", "type": "class"},
        {"title": "UserModel", "page_path": "models/UserModel", "type": "class"},
    ]
    stat_rows = [{"n": 2, "avg_conf": 0.9}]
    mock_store = AsyncMock()
    mock_store.execute_query = AsyncMock(
        side_effect=[
            MagicMock(data=page_rows),
            MagicMock(data=stat_rows),
        ],
    )

    gen = AgentsMdGenerator(mock_store)
    content = await gen.generate("test-repo", business_id="default")

    assert "# AGENTS.md" in content or "# Knowledge Base" in content
    assert "AuthService" in content
    assert "UserModel" in content
    assert "Knowledge at a glance" in content
    assert mock_store.execute_query.await_count == 2


def test_empty_wiki_generates_minimal():
    stat_rows = [{"n": 0, "avg_conf": None}]
    mock_store = AsyncMock()
    mock_store.execute_query = AsyncMock(
        side_effect=[
            MagicMock(data=[]),
            MagicMock(data=stat_rows),
        ],
    )

    gen = AgentsMdGenerator(mock_store)
    content = asyncio.run(gen.generate("empty-repo"))
    assert len(content) > 0
    assert "Knowledge at a glance" in content
