import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_update_wiki_page_content_calls_execute():
    """Basic smoke test for the store method."""
    from store.wiki_page_store import WikiPageStoreMixin

    class _Store(WikiPageStoreMixin):
        def __init__(self):
            self.execute_query = AsyncMock(return_value=MagicMock(data=[{"version": 2, "old_content": "old"}]))

    s = _Store()
    await s.update_wiki_page_content("page1", "new content", source="human_edit")
    assert s.execute_query.await_count >= 1
