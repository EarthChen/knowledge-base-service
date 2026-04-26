"""R-Phase 9: global search result merge at scale, wiki task registry lifecycle, reindex route."""

from __future__ import annotations

import asyncio
import re
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

import auth as auth_module
import api.kb_state as kb_state
from api.routes import indexing_routes  # noqa: F401 — register reindex on editor router
from api.routes.kb_routers import editor_router
from api.routes.wiki_routes import (
    WIKI_TASK_TTL_SEC,
    WikiTaskRegistry,
    get_wiki_search_dep,
    get_wiki_service_dep,
    wiki_router,
)
from fastapi import FastAPI
from indexer.task_manager import IndexTaskManager
from wiki.search import SearchResponse, SearchResult


@pytest.fixture(autouse=True)
def _no_auth_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_module, "_token_registry", {})


def _make_wiki_routes_app(*, app_state: dict) -> FastAPI:
    from api.routes.wiki_routes import WikiTaskRegistry as WR

    app = FastAPI()
    for k, v in app_state.items():
        setattr(app.state, k, v)
    if not hasattr(app.state, "wiki_store"):
        app.state.wiki_store = MagicMock()
    if not hasattr(app.state, "wiki_tasks"):
        app.state.wiki_tasks = WR()

    async def no_wiki_svc() -> MagicMock:
        return MagicMock()

    app.include_router(wiki_router)
    app.dependency_overrides[get_wiki_service_dep] = no_wiki_svc
    return app


@pytest.mark.asyncio
async def test_wiki_search_global_merges_many_repos_by_score() -> None:
    """12+ repos: merged ``results`` are sorted by score; ``context.repository`` is set per row."""
    n_repos = 12
    repos = [f"repo{i}" for i in range(n_repos)]
    reg = MagicMock()
    kb = MagicMock()
    kb.store = MagicMock()
    queries = MagicMock()
    rows = [{"repository": n} for n in repos]
    queries.list_repositories = AsyncMock(return_value=rows)
    reg.get_service = AsyncMock(return_value=kb)

    async def search_side_effect(*, repository: str, **_: object) -> SearchResponse:
        idx = int(re.sub(r"^repo", "", repository))
        sc = (idx + 1) * 0.1
        return SearchResponse(
            results=[
                SearchResult(
                    page_path=f"hit-{repository}.md",
                    title=repository,
                    score=sc,
                    snippet="n",
                    source_locations=[],
                    context={},
                )
            ],
            query_expansion={"original": "q", "expanded_queries": ["q"], "terms": []},
            total=1,
        )

    mock_search = MagicMock()
    mock_search.search = AsyncMock(side_effect=search_side_effect)
    with patch("api.routes.wiki_routes.GraphQueryRepository", return_value=queries):
        app = _make_wiki_routes_app(
            app_state={
                "registry": reg,
                "wiki_search_service": mock_search,
            },
        )
        app.dependency_overrides[get_wiki_search_dep] = lambda: mock_search

        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post(
                "/api/v1/wiki/search/global",
                json={"query": "hello", "limit": 5},
            )
    assert r.status_code == 200
    data = r.json()
    assert len(data["repositories_searched"]) == n_repos
    assert data["total"] == 5
    out = data["results"]
    scores = [float(x["score"]) for x in out]
    assert scores == pytest.approx([1.2, 1.1, 1.0, 0.9, 0.8])
    for row in out:
        ctx = row.get("context") or {}
        assert re.match(r"^repo\d+$", str(ctx.get("repository", "")))


def test_wiki_task_registry_lifecycle() -> None:
    """put_task → get_task; after TTL, get_task returns None (prune)."""
    reg = WikiTaskRegistry()
    with patch("api.routes.wiki_routes.time.monotonic", return_value=0.0):
        reg.put_task("t1", {"status": "pending"})
    with patch("api.routes.wiki_routes.time.monotonic", return_value=0.0):
        assert reg.get_task("t1") == {"status": "pending"}
    with patch("api.routes.wiki_routes.time.monotonic", return_value=float(WIKI_TASK_TTL_SEC + 1)):
        assert reg.get_task("t1") is None


@pytest.mark.asyncio
async def test_reindex_all_queues_tasks_with_base_dir(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "r0").mkdir()
    (tmp_path / "r1").mkdir()
    km = IndexTaskManager()
    reg = MagicMock()
    reg.get_service = AsyncMock(return_value=MagicMock(store=MagicMock()))
    monkeypatch.setattr(kb_state, "task_manager", km)
    monkeypatch.setattr(kb_state, "registry", reg)

    app = FastAPI()
    app.include_router(editor_router)

    with patch("api.routes.indexing_routes.run_index_task", new_callable=AsyncMock) as m_run:
        m_run.return_value = None
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.post(
                "/api/v1/reindex/all",
                json={"base_dir": str(tmp_path), "repositories": ["r0", "r1"]},
                headers={"X-Business-Id": "default"},
            )
        assert r.status_code == 200
        body = r.json()
        assert body["queued"] == 2
        assert len(body["task_ids"]) == 2
        await asyncio.sleep(0.2)
        assert m_run.await_count == 2
