"""Tests for deprecated search endpoints and HybridSearchRequest.entity_type."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from pydantic import ValidationError
from starlette.testclient import TestClient

import auth as auth_module
from main import HybridSearchRequest, _get_service, viewer_router
from query.hybrid_query import HybridResult
from query.semantic_query import SemanticResult


@pytest.fixture(autouse=True)
def _open_access_no_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    """Viewer routes use require_role; empty token registry allows access."""
    monkeypatch.setattr(auth_module, "_token_registry", {})


def _make_client_with_mock(mock_svc: MagicMock) -> TestClient:
    app = FastAPI()
    app.include_router(viewer_router)

    async def override_get_service():
        return mock_svc

    app.dependency_overrides[_get_service] = override_get_service
    return TestClient(app)


class TestDeprecatedSearchEndpoints:
    def test_search_returns_deprecated_payload_and_header(self) -> None:
        mock_svc = MagicMock()
        mock_svc.semantic_query.search_all = AsyncMock(
            return_value=SemanticResult(matches=[], query_text="hello", total=0)
        )
        mock_svc.store.keyword_search = AsyncMock(return_value=[])

        client = _make_client_with_mock(mock_svc)
        with pytest.warns(DeprecationWarning, match="Deprecated: use /hybrid"):
            r = client.post("/api/v1/search", json={"query": "hello", "k": 5})

        assert r.status_code == 200
        assert r.headers.get("Deprecation") == "true"
        body = r.json()
        assert body["_deprecated"] == "Use POST /api/v1/hybrid instead"
        assert body["query"] == "hello"

    def test_business_search_returns_deprecated_payload_and_header(self) -> None:
        mock_svc = MagicMock()
        mock_svc.semantic_query.search_business_flows = AsyncMock(
            return_value=SemanticResult(matches=[], query_text="q", total=0)
        )
        mock_svc.semantic_query.search_business_concepts = AsyncMock(
            return_value=SemanticResult(matches=[], query_text="q", total=0)
        )

        client = _make_client_with_mock(mock_svc)
        with pytest.warns(DeprecationWarning, match="Deprecated: use /hybrid"):
            r = client.post(
                "/api/v1/business/search",
                json={"query": "checkout", "search_type": "all", "k": 5},
            )

        assert r.status_code == 200
        assert r.headers.get("Deprecation") == "true"
        body = r.json()
        assert (
            body["_deprecated"]
            == "Use POST /api/v1/hybrid with entity_type filter instead"
        )


class TestHybridEntityTypeFilter:
    def test_filters_semantic_matches_by_entity_type(self) -> None:
        mock_svc = MagicMock()
        matches = [
            {"type": "Function", "name": "run", "score": 0.9},
            {"type": "BusinessFlow", "name": "Checkout", "score": 0.85},
            {"type": "BusinessConcept", "name": "Payment", "score": 0.8},
        ]
        graph_ctx = [{"name": "helper", "type": "Function"}]
        mock_svc.hybrid_query.search_with_context = AsyncMock(
            return_value=HybridResult(
                semantic_matches=matches,
                graph_context=graph_ctx,
                query_text="pay",
                total=len(matches) + len(graph_ctx),
            )
        )

        client = _make_client_with_mock(mock_svc)
        r = client.post(
            "/api/v1/hybrid",
            json={
                "query": "pay",
                "k": 5,
                "expand_depth": 2,
                "entity_type": "flow",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert len(body["semantic_matches"]) == 1
        assert body["semantic_matches"][0]["type"] == "BusinessFlow"
        assert body["graph_context"] == graph_ctx
        assert body["total"] == 1 + len(graph_ctx)

    def test_without_entity_type_backward_compatible(self) -> None:
        mock_svc = MagicMock()
        matches = [
            {"type": "Function", "name": "a"},
            {"type": "Class", "name": "B"},
        ]
        mock_svc.hybrid_query.search_with_context = AsyncMock(
            return_value=HybridResult(
                semantic_matches=matches,
                graph_context=[],
                query_text="x",
                total=len(matches),
            )
        )

        client = _make_client_with_mock(mock_svc)
        r = client.post("/api/v1/hybrid", json={"query": "x"})
        assert r.status_code == 200
        body = r.json()
        assert len(body["semantic_matches"]) == 2
        assert body["total"] == len(matches)
        mock_svc.hybrid_query.search_with_context.assert_called_once_with(
            "x", k=5, expand_depth=2
        )

    def test_invalid_entity_type_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            HybridSearchRequest(
                query="x",
                entity_type="invalid_kind",
            )


class TestHybridSearchRequestModel:
    def test_entity_type_aliases_normalized(self) -> None:
        m = HybridSearchRequest(query="q", entity_type="FLOW")
        assert m.entity_type == "flow"

    def test_entity_type_none_means_all(self) -> None:
        m = HybridSearchRequest(query="q")
        assert m.entity_type is None
