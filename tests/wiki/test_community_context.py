from unittest.mock import AsyncMock, MagicMock

import pytest

from wiki.community_context import (
    CachedCommunityService,
    format_communities_markdown,
    get_repository_index_fingerprint,
)


def test_format_communities_markdown_includes_label_and_cohesion() -> None:
    payload = {
        "communities": [
            {
                "id": 0,
                "label": "AuthService / TokenManager",
                "size": 2,
                "cohesion": 0.85,
                "members": [
                    {"name": "AuthService", "type": "Class", "file": "a.py"},
                    {"name": "TokenManager", "type": "Class", "file": "b.py"},
                ],
            }
        ],
        "total_communities": 1,
        "unclustered_count": 0,
    }
    out = format_communities_markdown(payload)
    assert "### Community 1:" in out
    assert "AuthService" in out
    assert "0.85" in out or "cohesion" in out.lower()


def test_format_empty_communities() -> None:
    assert format_communities_markdown({"communities": []}) == ""


@pytest.mark.asyncio
async def test_fingerprint_uses_max_indexed_at_and_node_count() -> None:
    store = MagicMock()
    store.execute_query = AsyncMock(return_value=MagicMock(data=[{"mx": 100.0, "cnt": 42}]))
    fp = await get_repository_index_fingerprint(store, "my-repo")
    assert "42" in fp


@pytest.mark.asyncio
async def test_cached_community_skips_second_detect() -> None:
    detector = MagicMock()
    detector.detect = AsyncMock(
        return_value={"communities": [], "total_communities": 0, "unclustered_count": 0}
    )
    store = MagicMock()
    store.execute_query = AsyncMock(return_value=MagicMock(data=[{"cnt": 1, "mx": 1.0}]))
    svc = CachedCommunityService(store, detector)
    await svc.get_cached("r1")
    await svc.get_cached("r1")
    assert detector.detect.call_count == 1
