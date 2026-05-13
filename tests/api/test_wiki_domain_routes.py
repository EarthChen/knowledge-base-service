"""HTTP tests for domain module listing and domain rename under /api/v1/wiki."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from main import app

import core.auth as auth_module


@pytest.fixture(autouse=True)
def _open_access_no_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_module, "_token_registry", {})


@pytest.mark.asyncio
async def test_list_domain_modules_endpoint() -> None:
    """GET …/domains/{slug}/modules returns modules list via persistence."""
    modules = [{"name": "Payments", "repository": "my-repo", "path": "app/payments", "pinned": False}]
    mock_p = AsyncMock()
    mock_p.list_domain_modules = AsyncMock(return_value=modules)

    with patch(
        "api.routes.wiki_page_routes._wiki_persistence_for_business_id",
        new=AsyncMock(return_value=mock_p),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/wiki/acme/domains/payment/modules",
                headers={"Authorization": "Bearer test-token"},
            )

    assert resp.status_code == 200
    assert resp.json() == {"modules": modules}
    mock_p.list_domain_modules.assert_awaited_once_with("acme", "payment")


@pytest.mark.asyncio
async def test_rename_domain_endpoint() -> None:
    """PUT …/domains/{slug}/rename calls persistence.rename_domain with body fields."""
    mock_p = AsyncMock()
    mock_p.rename_domain = AsyncMock(return_value=True)

    with patch(
        "api.routes.wiki_page_routes._wiki_persistence_for_business_id",
        new=AsyncMock(return_value=mock_p),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.put(
                "/api/v1/wiki/acme/domains/old-slug/rename",
                json={"new_slug": "new-slug", "new_display_name": "New Title"},
                headers={"Authorization": "Bearer test-token"},
            )

    assert resp.status_code == 200
    assert resp.json() == {
        "status": "ok",
        "old_slug": "old-slug",
        "new_slug": "new-slug",
    }
    mock_p.rename_domain.assert_awaited_once_with(
        "acme",
        "old-slug",
        "new-slug",
        "New Title",
    )


@pytest.mark.asyncio
async def test_rename_domain_invalid_slug() -> None:
    """Invalid new_slug (spaces) returns 422."""
    mock_p = AsyncMock()

    with patch(
        "api.routes.wiki_page_routes._wiki_persistence_for_business_id",
        new=AsyncMock(return_value=mock_p),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.put(
                "/api/v1/wiki/acme/domains/old-slug/rename",
                json={"new_slug": "bad slug"},
                headers={"Authorization": "Bearer test-token"},
            )

    assert resp.status_code == 422
    mock_p.rename_domain.assert_not_called()


@pytest.mark.asyncio
async def test_rename_domain_not_found() -> None:
    """Persistence returns False → 404."""
    mock_p = AsyncMock()
    mock_p.rename_domain = AsyncMock(return_value=False)

    with patch(
        "api.routes.wiki_page_routes._wiki_persistence_for_business_id",
        new=AsyncMock(return_value=mock_p),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.put(
                "/api/v1/wiki/acme/domains/old-slug/rename",
                json={"new_slug": "new-slug"},
                headers={"Authorization": "Bearer test-token"},
            )

    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_rename_domain_collision() -> None:
    """Persistence raises ValueError → 409."""
    mock_p = AsyncMock()
    mock_p.rename_domain = AsyncMock(
        side_effect=ValueError("Domain slug 'new-slug' already exists"),
    )

    with patch(
        "api.routes.wiki_page_routes._wiki_persistence_for_business_id",
        new=AsyncMock(return_value=mock_p),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.put(
                "/api/v1/wiki/acme/domains/old-slug/rename",
                json={"new_slug": "new-slug"},
                headers={"Authorization": "Bearer test-token"},
            )

    assert resp.status_code == 409
    assert "already exists" in resp.json()["detail"]
