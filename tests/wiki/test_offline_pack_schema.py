"""WikiOfflinePack build output includes schema version and build timestamp."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from wiki.offline_pack import WikiOfflinePack, _SCHEMA_VERSION


@pytest.mark.asyncio
async def test_offline_pack_build_includes_schema_version_and_built_at() -> None:
    store = MagicMock()
    store.execute_query = AsyncMock(
        return_value=MagicMock(data=[]),
    )
    pack = WikiOfflinePack(store)
    out = await pack.build("my-repo", "biz-1")

    assert out.get("schema_version") == _SCHEMA_VERSION
    built = out.get("built_at")
    assert isinstance(built, str)
    datetime.fromisoformat(built.replace("Z", "+00:00"))
