"""HTTP tests for R-Phase 8 wiki routes: quality, references, Q&A list/record."""

from __future__ import annotations

from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient

import auth as auth_module
from api.routes.wiki_routes import get_wiki_service_dep, wiki_router
from wiki.quality_score import QualityFactor, QualityScoreBreakdown


@pytest.fixture(autouse=True)
def _open_access_no_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_module, "_token_registry", {})


@pytest.fixture
def client_references() -> TestClient:
    app = FastAPI()
    raw = MagicMock()
    raw.execute_query = AsyncMock(
        side_effect=[
            MagicMock(
                data=[
                    {
                        "uid": "p1",
                        "title": "A",
                        "path": "a.md",
                        "repository": "r",
                        "importance_tier": "core",
                    }
                ],
            ),
            MagicMock(data=[]),
        ],
    )
    app.state.wiki_store = raw

    async def _wiki() -> object:
        return MagicMock()

    app.include_router(wiki_router)
    app.dependency_overrides[get_wiki_service_dep] = _wiki
    return TestClient(app)


def test_get_references_shape(client_references: TestClient) -> None:
    r = client_references.get("/api/v1/wiki/references?business_id=b1")
    assert r.status_code == 200
    body = r.json()
    assert "pages" in body and "edges" in body
    assert body["pages"][0]["uid"] == "p1"


@patch("api.routes.wiki_routes.WikiQualityScorer", autospec=True)
def test_get_quality_score(mock_scorer: MagicMock) -> None:
    inst = mock_scorer.return_value
    inst.compute_score = AsyncMock(
        return_value=QualityScoreBreakdown(
            score=75,
            factors=[QualityFactor(name="coverage", weight=0.4, score=0.9)],
            details={},
        ),
    )

    app = FastAPI()
    app.state.wiki_store = MagicMock()
    app.include_router(wiki_router)

    with TestClient(app) as c:
        r = c.get("/api/v1/wiki/quality-score?business_id=default")
    assert r.status_code == 200
    j = r.json()
    assert j["score"] == 75
    inst.compute_score.assert_awaited_once()
    assert inst.compute_score.call_args[0][0] == "default"


@pytest.mark.asyncio
async def test_post_qa_record_invokes_memory_loop() -> None:
    app = FastAPI()
    raw = MagicMock()
    mem = MagicMock()
    mem.record = AsyncMock(return_value="WikiQA:bi:uid1")

    app.state.wiki_store = raw
    app.state.wiki_memory_loop = mem
    app.include_router(wiki_router)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        p = await ac.post(
            "/api/v1/wiki/qa/record",
            json={"business_id": "b1", "question": "Q", "answer": "A", "source_pages": ["x.md"]},
        )
    assert p.status_code == 200
    assert p.json()["uid"] == "WikiQA:bi:uid1"
    mem.record.assert_awaited_once()
    assert mem.record.call_args.kwargs.get("business_id") == "b1"


def test_get_qa_list() -> None:
    app = FastAPI()
    raw = MagicMock()
    raw.execute_query = AsyncMock(
        side_effect=[
            MagicMock(
                data=[{"uid": "q1", "question": "Q", "answer": "A", "source_pages": "[]", "quality_score": 0.5, "created_at": "t"}],
            ),
            MagicMock(data=[{"c": 1}]),
        ],
    )
    app.state.wiki_store = raw
    app.include_router(wiki_router)
    with TestClient(app) as c:
        r = c.get("/api/v1/wiki/qa?business_id=b1")
    assert r.status_code == 200
    j = r.json()
    assert len(j["items"]) == 1
    assert j["total"] == 1
