"""HTTP tests for GET /api/v1/wiki/domain-tree, /topic-tree, and /domain-edges."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from main import app
from httpx import ASGITransport, AsyncClient

import auth as auth_module


@pytest.fixture(autouse=True)
def _open_access_no_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_module, "_token_registry", {})


@pytest.mark.asyncio
async def test_get_domain_tree_returns_tree() -> None:
    """GET /wiki/domain-tree should return domain tree data."""
    mock_svc = AsyncMock()
    mock_svc.get_domain_tree = AsyncMock(
        return_value={
            "tree": [{"name": "payment", "modules": ["PaymentService"], "children": []}],
            "review_status": {"domain_tree": "pending_review"},
        }
    )

    with patch(
        "api.routes.wiki_page_routes._get_wiki_service",
        new=AsyncMock(return_value=mock_svc),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/wiki/domain-tree",
                params={"business_id": "test-biz"},
                headers={"Authorization": "Bearer test-token"},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert "tree" in data
    assert len(data["tree"]) == 1
    assert data["tree"][0]["name"] == "payment"


@pytest.mark.asyncio
async def test_get_topic_tree_returns_tree() -> None:
    """GET /wiki/topic-tree should return topic page tree."""
    mock_svc = AsyncMock()
    mock_svc.get_topic_tree = AsyncMock(
        return_value={
            "tree": [
                {
                    "name": "payment",
                    "page_type": "domain_overview",
                    "path": "wiki/payment",
                    "children": [],
                }
            ],
        }
    )

    with patch(
        "api.routes.wiki_page_routes._get_wiki_service",
        new=AsyncMock(return_value=mock_svc),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/wiki/topic-tree",
                params={"business_id": "test-biz"},
                headers={"Authorization": "Bearer test-token"},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert "tree" in data


@pytest.mark.asyncio
async def test_get_domain_edges_returns_empty_on_fallback() -> None:
    """GET /wiki/domain-edges should return empty edges on AttributeError."""

    class _SvcWithoutDomainEdges:
        pass

    with patch(
        "api.routes.wiki_page_routes._get_wiki_service",
        new=AsyncMock(return_value=_SvcWithoutDomainEdges()),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/wiki/domain-edges",
                params={"business_id": "test-biz"},
                headers={"Authorization": "Bearer test-token"},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data.get("edges") == []


@pytest.mark.asyncio
async def test_get_domain_edges_returns_edges() -> None:
    """GET /wiki/domain-edges should return edges from the wiki service."""
    mock_svc = AsyncMock()
    mock_svc.get_domain_edges = AsyncMock(
        return_value={
            "edges": [
                {"source": "payment", "target": "orders", "label": "CALLS (3)"},
            ],
        },
    )

    with patch(
        "api.routes.wiki_page_routes._get_wiki_service",
        new=AsyncMock(return_value=mock_svc),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/wiki/domain-edges",
                params={"business_id": "test-biz"},
                headers={"Authorization": "Bearer test-token"},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["edges"]) == 1
    assert data["edges"][0]["source"] == "payment"
    assert data["edges"][0]["target"] == "orders"
