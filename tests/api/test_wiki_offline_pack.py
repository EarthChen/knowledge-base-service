import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_offline_pack_build():
    from wiki.offline_pack import WikiOfflinePack

    store = MagicMock()
    store.execute_query = AsyncMock(return_value=MagicMock(data=[]))

    pack = WikiOfflinePack(store)
    result = await pack.build("test-repo", "b1")

    assert result["repository"] == "test-repo"
    assert "generated_at" in result
    assert "pages" in result
    assert "tree" in result
    assert result["page_count"] == 0
