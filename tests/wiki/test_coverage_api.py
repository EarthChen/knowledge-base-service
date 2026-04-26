# tests/wiki/test_coverage_api.py
"""Unit tests for wiki coverage report API endpoint."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import auth as auth_module
from api.error_handler import register_exception_handlers
from api.routes.wiki_routes import wiki_router
from store.falkordb_store import QueryResultWrapper


@pytest.fixture(autouse=True)
def _open_access_no_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_module, "_token_registry", {})


def _create_test_app(
    wiki_store=None,
    coverage_report_enabled=True,
    stale_detection_enabled=True,
    suggested_questions_enabled=True,
):
    """Create a FastAPI test app with mocked dependencies."""
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(wiki_router)
    app.state.wiki_store = wiki_store

    # Mock settings
    mock_settings = MagicMock()
    mock_settings.wiki.coverage_report_enabled = coverage_report_enabled
    mock_settings.wiki.stale_detection_enabled = stale_detection_enabled
    mock_settings.wiki.suggested_questions_enabled = suggested_questions_enabled

    return app, mock_settings


def _raw_store_three_queries(
    tier_rows: list[dict],
    gap_rows: list[dict],
    stale_rows: list[dict],
) -> AsyncMock:
    """Build raw graph store mock: WikiStore calls execute_query in stats → gaps → stale order."""
    mock_store = AsyncMock()

    async def execute_query(cypher: str, params: dict | None = None):
        _ = (cypher, params)
        if not hasattr(execute_query, "_i"):
            execute_query._i = 0  # type: ignore[attr-defined]
        execute_query._i += 1  # type: ignore[attr-defined]
        i = execute_query._i  # type: ignore[attr-defined]
        if i == 1:
            return QueryResultWrapper(tier_rows)
        if i == 2:
            return QueryResultWrapper(gap_rows)
        if i == 3:
            return QueryResultWrapper(stale_rows)
        return QueryResultWrapper([])

    mock_store.execute_query = AsyncMock(side_effect=execute_query)
    return mock_store


class TestCoverageReportEndpoint:
    def test_returns_coverage_report(self):
        """Successful coverage report with all features enabled."""
        mock_store = _raw_store_three_queries(
            tier_rows=[
                {"tier": "core", "cnt": 15},
                {"tier": "standard", "cnt": 25},
                {"tier": "skeleton", "cnt": 10},
            ],
            gap_rows=[
                {"entity_name": "PayService", "in_degree": 10, "wiki_tier": "skeleton"},
            ],
            stale_rows=[
                {
                    "page_path": "/Domain/Old",
                    "page_title": "Old",
                    "entity_commit": "abc",
                    "page_generated_at": "2026-04-01",
                },
            ],
        )

        app, mock_settings = _create_test_app(wiki_store=mock_store)

        with patch("api.routes.wiki_routes.get_settings", return_value=mock_settings):
            client = TestClient(app)
            resp = client.get("/api/v1/wiki/coverage-report", params={"business_id": "test-biz"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_entities"] == 50
        assert data["covered_entities"] == 40
        assert data["coverage_percentage"] == 80.0
        assert len(data["knowledge_gaps"]) == 1
        assert len(data["stale_pages"]) == 1

    def test_disabled_returns_404(self):
        """When coverage_report_enabled=False, endpoint returns 404."""
        mock_store = AsyncMock()
        app, mock_settings = _create_test_app(
            wiki_store=mock_store,
            coverage_report_enabled=False,
        )

        with patch("api.routes.wiki_routes.get_settings", return_value=mock_settings):
            client = TestClient(app)
            resp = client.get("/api/v1/wiki/coverage-report", params={"business_id": "test"})

        assert resp.status_code == 404

    def test_stale_detection_disabled(self):
        """When stale_detection_enabled=False, stale_pages should be empty."""
        mock_store = _raw_store_three_queries(
            tier_rows=[
                {"tier": "core", "cnt": 3},
                {"tier": "standard", "cnt": 5},
                {"tier": "skeleton", "cnt": 2},
            ],
            gap_rows=[],
            stale_rows=[
                {
                    "page_path": "/X",
                    "page_title": "X",
                    "entity_commit": "c1",
                    "page_generated_at": "2026-01-01",
                },
            ],
        )

        app, mock_settings = _create_test_app(
            wiki_store=mock_store,
            stale_detection_enabled=False,
        )

        with patch("api.routes.wiki_routes.get_settings", return_value=mock_settings):
            client = TestClient(app)
            resp = client.get("/api/v1/wiki/coverage-report", params={"business_id": "test"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["stale_pages"] == []
        assert data["stale_page_count"] == 0

    def test_empty_business_returns_zeros(self):
        """Empty business returns zero coverage."""
        mock_store = _raw_store_three_queries(
            tier_rows=[],
            gap_rows=[],
            stale_rows=[],
        )

        app, mock_settings = _create_test_app(wiki_store=mock_store)

        with patch("api.routes.wiki_routes.get_settings", return_value=mock_settings):
            client = TestClient(app)
            resp = client.get("/api/v1/wiki/coverage-report", params={"business_id": "empty"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_entities"] == 0
        assert data["coverage_percentage"] == 0.0

    def test_store_unavailable_returns_503(self):
        """When wiki_store is None, return 503."""
        app, mock_settings = _create_test_app(wiki_store=None)

        with patch("api.routes.wiki_routes.get_settings", return_value=mock_settings):
            client = TestClient(app)
            resp = client.get("/api/v1/wiki/coverage-report", params={"business_id": "x"})

        assert resp.status_code == 503
