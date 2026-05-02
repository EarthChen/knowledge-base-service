"""HTTP tests for wiki editing presence endpoints (editor router)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from httpx import ASGITransport
from fastapi import FastAPI

import core.auth as auth_module
from api.routes.kb_routers import editor_router
from api.routes import wiki_page_routes  # noqa: F401 — registers wiki routes on editor_router
from store.wiki_store import WikiStore


@pytest.fixture(autouse=True)
def _no_auth_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_module, "_token_registry", {})


@pytest.mark.asyncio
async def test_editing_heartbeat_get_editors_delete_flow() -> None:
    app = FastAPI()
    app.state.wiki_store = MagicMock()
    r = MagicMock()
    r.zadd = AsyncMock()
    r.zremrangebyscore = AsyncMock()
    r.expire = AsyncMock()
    r.zrange = AsyncMock(return_value=[])
    r.zrem = AsyncMock()
    r.zcard = AsyncMock(return_value=0)
    r.delete = AsyncMock()
    wts = MagicMock()
    wts._redis = r
    app.state.wiki_task_store = wts

    app.include_router(editor_router)
    with patch.object(WikiStore, "assert_wiki_page_in_business", new_callable=AsyncMock) as m:
        m.return_value = True
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            p = await ac.post(
                "/api/v1/wiki/pages/page-1/editing",
                json={},
            )
            assert p.status_code == 200
            g = await ac.get("/api/v1/wiki/pages/page-1/editors")
            assert g.status_code == 200
            assert g.json()["other_active"] is False
            d = await ac.delete("/api/v1/wiki/pages/page-1/editing")
            assert d.status_code == 204
    r.zadd.assert_awaited()


@pytest.mark.asyncio
async def test_get_editors_other_active_with_two_editors() -> None:
    app = FastAPI()
    app.state.wiki_store = MagicMock()
    e_self = "a" * 16
    e_other = "b" * 16
    r = MagicMock()
    r.zadd = AsyncMock()
    r.zremrangebyscore = AsyncMock()
    r.zrange = AsyncMock(
        return_value=[(e_self, 1_700_000_000.0), (e_other, 1_700_000_050.0)],
    )
    r.expire = AsyncMock()
    wts = MagicMock()
    wts._redis = r
    app.state.wiki_task_store = wts
    app.include_router(editor_router)

    with (
        patch.object(WikiStore, "assert_wiki_page_in_business", new_callable=AsyncMock) as m,
        patch(
            "api.routes.wiki_page_routes.WikiEditingStore.editor_fingerprint",
            return_value=e_self,
        ),
    ):
        m.return_value = True
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            res = await ac.get("/api/v1/wiki/pages/page-1/editors")
    assert res.status_code == 200
    body = res.json()
    assert body["other_active"] is True
    assert len(body["editors"]) == 2


@pytest.mark.asyncio
async def test_editing_degraded_without_redis() -> None:
    app = FastAPI()
    app.state.wiki_store = MagicMock()
    app.state.wiki_task_store = None
    app.include_router(editor_router)
    with patch.object(WikiStore, "assert_wiki_page_in_business", new_callable=AsyncMock) as m:
        m.return_value = True
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            p = await ac.post("/api/v1/wiki/pages/page-1/editing", json={})
            g = await ac.get("/api/v1/wiki/pages/page-1/editors")
    assert p.status_code == 200
    assert p.json().get("degraded") is True
    assert g.json()["editors"] == []
    assert g.json().get("degraded") is True
