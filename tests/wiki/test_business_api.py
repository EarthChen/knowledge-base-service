import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient

import auth as auth_module
from api.error_handler import register_exception_handlers
from wiki.structure_planner import WikiScopeError


@pytest.fixture(autouse=True)
def _open_access_no_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_module, "_token_registry", {})


@pytest.fixture
def app():
    from api.routes.wiki_routes import wiki_router

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(wiki_router)
    return app


def test_generate_business_wiki_endpoint(app):
    """POST /api/v1/wiki/business/generate should return 202."""
    client = TestClient(app)
    mock_svc = AsyncMock()
    mock_svc.generate_business_wiki = AsyncMock(
        return_value={
            "business_id": "test",
            "domains": ["用户管理"],
            "pages_count": 5,
            "references_count": 3,
            "repositories": ["user-svc"],
        },
    )
    app.state.wiki_service_factory = lambda: mock_svc
    r = client.post(
        "/api/v1/wiki/business/generate",
        json={"business_id": "test", "language": "zh"},
    )
    assert r.status_code == 202
    data = r.json()
    assert data["business_id"] == "test"


def test_generate_business_wiki_scope_error(app):
    """WikiScopeError from generate_business_wiki should return 400."""
    client = TestClient(app)
    mock_svc = AsyncMock()
    mock_svc.generate_business_wiki = AsyncMock(side_effect=WikiScopeError("no such business"))
    app.state.wiki_service_factory = lambda: mock_svc
    r = client.post(
        "/api/v1/wiki/business/generate",
        json={"business_id": "missing", "language": "zh"},
    )
    assert r.status_code == 400
    body = r.json()
    assert body["error"]["code"] == "kb_client_error"


def test_generate_business_wiki_service_unavailable(app):
    """Without wiki_service_factory, business generate should return 503."""
    client = TestClient(app)
    if hasattr(app.state, "wiki_service_factory"):
        delattr(app.state, "wiki_service_factory")
    r = client.post(
        "/api/v1/wiki/business/generate",
        json={"business_id": "test", "language": "en"},
    )
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "kb_service_unavailable"


def test_wiki_page_references_endpoint(app):
    """GET /api/v1/wiki/pages/{page_uid}/references should return references."""
    client = TestClient(app)
    mock_store = MagicMock()
    mock_result = MagicMock()
    mock_result.data = []
    mock_result.result_set = []
    mock_store.execute_query = AsyncMock(return_value=mock_result)
    app.state.wiki_store = mock_store
    r = client.get("/api/v1/wiki/pages/WikiPage%3Ar%3Atest/references")
    assert r.status_code == 200


def test_page_references_response_shape(app):
    """GET page references JSON should include page_uid, outgoing, and incoming."""
    client = TestClient(app)
    mock_store = MagicMock()
    mock_out = MagicMock()
    mock_out.data = [{"target_uid": "WikiPage:r:other", "path": "other.md"}]
    mock_in = MagicMock()
    mock_in.data = [{"source_uid": "WikiPage:r:parent", "path": "parent.md"}]
    mock_store.execute_query = AsyncMock(side_effect=[mock_out, mock_in])
    app.state.wiki_store = mock_store
    r = client.get("/api/v1/wiki/pages/WikiPage%3Ar%3Atest/references")
    assert r.status_code == 200
    data = r.json()
    assert set(data.keys()) == {"page_uid", "outgoing", "incoming"}
    assert data["page_uid"] == "WikiPage:r:test"
    assert data["outgoing"] == mock_out.data
    assert data["incoming"] == mock_in.data
