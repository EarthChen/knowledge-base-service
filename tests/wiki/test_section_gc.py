"""Tests for wiki section garbage collection."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_prune_deletes_empty_sections():
    from wiki.section_gc import prune_empty_domain_sections

    store = AsyncMock()
    # Find query returns 2 empty sections
    find_result = MagicMock()
    find_result.data = [
        {"uid": "WikiSection:ultron:domain:family-task", "title": "家族任务策略"},
        {"uid": "WikiSection:ultron:domain:intimacy-relation", "title": "亲密度关系"},
    ]
    # Delete query returns count
    del_result = MagicMock()
    del_result.data = [{"deleted": 2}]
    store.execute_query = AsyncMock(side_effect=[find_result, del_result])

    deleted = await prune_empty_domain_sections(
        store, business_id="ultron", space_uid="WikiSpace:ultron"
    )
    assert deleted == 2
    assert store.execute_query.call_count == 2


@pytest.mark.asyncio
async def test_prune_returns_zero_when_no_empty_sections():
    from wiki.section_gc import prune_empty_domain_sections

    store = AsyncMock()
    find_result = MagicMock()
    find_result.data = []
    store.execute_query = AsyncMock(return_value=find_result)

    deleted = await prune_empty_domain_sections(
        store, business_id="ultron", space_uid="WikiSpace:ultron"
    )
    assert deleted == 0
    assert store.execute_query.call_count == 1  # only find query, no delete
