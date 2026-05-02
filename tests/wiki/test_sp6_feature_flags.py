"""SP6 feature flags: deep research and concept merging."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import core.auth as auth_module
from api.error_handler import register_exception_handlers
from api.routes.wiki_routes import wiki_router
from wiki.deep_research import DeepResearchService


@pytest.fixture(autouse=True)
def _open_access_no_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_module, "_token_registry", {})


def _mock_settings(
    *,
    deep_research_enabled: bool = False,
    concept_merging_enabled: bool = False,
    concept_merge_similarity_threshold: float = 0.9,
) -> MagicMock:
    mock_settings = MagicMock()
    mock_settings.wiki.deep_research_enabled = deep_research_enabled
    mock_settings.wiki.concept_merging_enabled = concept_merging_enabled
    mock_settings.wiki.concept_merge_similarity_threshold = concept_merge_similarity_threshold
    return mock_settings


def test_deep_research_disabled_returns_404() -> None:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(wiki_router)
    dr = DeepResearchService(rag_engine=AsyncMock())
    app.state.wiki_deep_research_service = dr
    app.state.wiki_store = AsyncMock()

    mock_settings = _mock_settings(deep_research_enabled=False)
    with patch("api.routes.wiki_routes.get_settings", return_value=mock_settings):
        client = TestClient(app)
        resp = client.post(
            "/api/v1/wiki/research",
            json={"question": "Q?", "repository": "r1", "business_id": "b1"},
        )
    assert resp.status_code == 404


def test_deep_research_enabled_calls_service() -> None:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(wiki_router)
    dr = MagicMock(spec=DeepResearchService)
    dr.research = AsyncMock(
        return_value={
            "question": "Q",
            "sub_questions": [],
            "sub_answers": [],
            "synthesis": "S",
        },
    )
    app.state.wiki_deep_research_service = dr
    app.state.wiki_store = AsyncMock()

    mock_settings = _mock_settings(deep_research_enabled=True)
    with patch("api.routes.wiki_routes.get_settings", return_value=mock_settings):
        client = TestClient(app)
        resp = client.post(
            "/api/v1/wiki/research",
            json={"question": "Q?", "repository": "r1", "business_id": "b1"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["synthesis"] == "S"
    assert dr.research.await_count == 1


def test_merge_candidates_disabled_returns_404() -> None:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(wiki_router)
    app.state.wiki_store = AsyncMock()

    mock_settings = _mock_settings(concept_merging_enabled=False)
    with patch("api.routes.wiki_routes.get_settings", return_value=mock_settings):
        client = TestClient(app)
        resp = client.get("/api/v1/wiki/merge-candidates", params={"business_id": "b1"})

    assert resp.status_code == 404


def test_merge_candidates_enabled_returns_list() -> None:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(wiki_router)
    store = AsyncMock()
    store.execute_query = AsyncMock(
        return_value=MagicMock(
            data=[
                {
                    "a_uid": "WikiPage:repo1:A",
                    "b_uid": "WikiPage:repo2:B",
                    "a_title": "A",
                    "b_title": "B",
                    "similarity": 0.99,
                }
            ],
        ),
    )
    app.state.wiki_store = store

    mock_settings = _mock_settings(concept_merging_enabled=True, concept_merge_similarity_threshold=0.9)
    with patch("api.routes.wiki_routes.get_settings", return_value=mock_settings):
        client = TestClient(app)
        resp = client.get("/api/v1/wiki/merge-candidates", params={"business_id": "b1"})

    assert resp.status_code == 200
    cands = resp.json()["candidates"]
    assert len(cands) == 1
    assert cands[0]["similarity"] == 0.99
