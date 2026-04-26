import pytest
from fastapi.testclient import TestClient

import auth as auth_module


@pytest.fixture(autouse=True)
def _open_access_no_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_module, "_token_registry", {})


@pytest.fixture
def client():
    from main import app

    return TestClient(app)


def test_wiki_tree_endpoint_exists(client):
    """GET /api/v1/wiki/tree returns JSON (not SPA index.html) with tree, view, business."""
    response = client.get(
        "/api/v1/wiki/tree",
        params={"business_id": "default", "view": "business_domain"},
    )
    assert response.status_code == 200
    assert "application/json" in response.headers.get("content-type", "")
    data = response.json()
    assert "tree" in data
    assert data.get("view_type") == "business_domain"
    assert data.get("business_id") == "default"
    assert isinstance(data["tree"], list)
