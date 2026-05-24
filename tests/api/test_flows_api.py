from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

import core.auth as auth_module
from api.error_handler import register_exception_handlers
from api.routes.wiki_page_routes import _build_flows_graph_response, router as wiki_page_router
from api.routes.wiki_shared import get_wiki_store_dep


@pytest.fixture(autouse=True)
def _open_access_no_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_module, "_token_registry", {})


@pytest.fixture
def flows_client() -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)

    async def _mock_store() -> MagicMock:
        return MagicMock()

    app.dependency_overrides[get_wiki_store_dep] = _mock_store
    app.include_router(wiki_page_router, prefix="/api/v1/wiki")
    return TestClient(app)


class TestFlowsAPIUpgrade:
    @pytest.mark.asyncio
    async def test_flows_returns_nodes(self) -> None:
        """Verify the flows endpoint returns BusinessFlow nodes."""
        from wiki.flow_baseline import EntryPointInfo, FlowBaseline

        baseline = FlowBaseline(
            "order",
            [EntryPointInfo("create", "Ctrl", "http", "f.py")],
            [],
            1,
            [],
        )
        assert baseline.entry_points[0].function_name == "create"
        assert baseline.entry_points[0].entry_type == "http"

    def test_build_flows_graph_response_includes_edges(self) -> None:
        rows = [
            {
                "bf_uid": "bf:order:create",
                "bf_name": "OrderController.create",
                "bf_description": "",
                "bf_domain": "order",
                "step_uid": "fs:validate",
                "step_name": "Validate Input",
                "step_weight": 1,
            },
            {
                "bf_uid": "bf:order:create",
                "bf_name": "OrderController.create",
                "bf_description": "",
                "bf_domain": "order",
                "step_uid": "fs:save",
                "step_name": "Save Order",
                "step_weight": 2,
            },
        ]
        data = _build_flows_graph_response(rows)
        assert len(data["nodes"]) == 3
        assert any(n["uid"] == "bf:order:create" and n["type"] == "business_flow" for n in data["nodes"])
        assert any(n["uid"] == "fs:validate" and n["type"] == "flow_step" for n in data["nodes"])
        assert len(data["edges"]) == 2
        assert data["edges"][0]["label"] == "step 1"

    def test_flows_endpoint_returns_edges(self, flows_client: TestClient) -> None:
        mock_raw = MagicMock()
        mock_result = MagicMock()
        mock_result.data = [
            {
                "bf_uid": "bf:order:create",
                "bf_name": "Create Order",
                "bf_description": "",
                "bf_domain": "order",
                "step_uid": "fs:validate",
                "step_name": "Validate",
                "step_weight": 1,
            },
            {
                "bf_uid": "bf:order:create",
                "bf_name": "Create Order",
                "bf_description": "",
                "bf_domain": "order",
                "step_uid": "fs:save",
                "step_name": "Save",
                "step_weight": 2,
            },
        ]
        mock_raw.execute_query = AsyncMock(return_value=mock_result)

        with patch(
            "api.routes.wiki_page_routes.get_wiki_store_dep",
            new=AsyncMock(return_value=mock_raw),
        ):
            resp = flows_client.get("/api/v1/wiki/flows", params={"business_id": "test"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["nodes"]) >= 1
        assert len(data["edges"]) > 0
        assert data["edges"][0]["source"] == "bf:order:create"
