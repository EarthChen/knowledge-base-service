from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

import core.auth as auth_module
from api.error_handler import register_exception_handlers
from api.routes.wiki_page_routes import router as wiki_page_router
from api.routes.wiki_shared import get_wiki_store_dep


@pytest.fixture(autouse=True)
def _open_access_no_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_module, "_token_registry", {})


@pytest.fixture
def tour_client() -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)

    async def _mock_store() -> MagicMock:
        return MagicMock()

    app.dependency_overrides[get_wiki_store_dep] = _mock_store
    app.include_router(wiki_page_router, prefix="/api/v1/wiki")
    return TestClient(app)


class TestTourAPI:
    def test_tour_endpoint_returns_steps(self, tour_client: TestClient) -> None:
        with (
            patch(
                "api.routes.wiki_page_routes.get_wiki_store_dep",
                new=AsyncMock(return_value=MagicMock()),
            ),
            patch(
                "api.routes.wiki_page_routes._compute_tour_from_graph",
                new=AsyncMock(
                    return_value={
                        "total_pages": 2,
                        "steps": [
                            {
                                "order": 1,
                                "layer_name": "api",
                                "layer_display": "API",
                                "pages": [
                                    {
                                        "path": "api/ctrl.md",
                                        "title": "Controller",
                                        "reading_order": 1,
                                        "architecture_layer": "api",
                                    }
                                ],
                            },
                        ],
                    }
                ),
            ) as mock_compute,
        ):
            resp = tour_client.get("/api/v1/wiki/tour", params={"business_id": "test"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_pages"] == 2
        mock_compute.assert_awaited_once()
