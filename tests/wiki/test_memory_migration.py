"""Migration of flat wiki Q&A to tiered memory fields."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from store.wiki_store import WikiStore
from wiki.migrate_memory_tiers import migrate_flat_wiki_qa_to_tiered


@pytest.mark.asyncio
async def test_migrate_flat_wiki_qa_sets_tier1_and_access1() -> None:
    base = MagicMock()
    base.execute_query = AsyncMock(return_value=MagicMock(data=[{"updated": 3}]))
    n = await migrate_flat_wiki_qa_to_tiered(WikiStore(base), business_id="biz")
    assert n == 3
    cypher = base.execute_query.call_args[0][0].lower()
    assert "wikiqa" in cypher
    assert "tier" in cypher
    assert "access_count" in cypher
