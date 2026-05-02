"""SPA fallback must not serve files outside static/ (path traversal)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def spa_client():
    from main import create_app

    return TestClient(create_app())


def test_spa_fallback_blocks_dotdot_leaving_static(spa_client: TestClient) -> None:
    """Request for ../pyproject.toml must return dashboard shell, not repo pyproject."""
    resp = spa_client.get("/%2e%2e/pyproject.toml")
    assert resp.status_code == 200
    body = resp.text
    assert "Knowledge Base Dashboard" in body
    assert "[project]" not in body


def test_spa_fallback_still_serves_file_inside_static(spa_client: TestClient) -> None:
    """Legitimate files under static/ are still served."""
    resp = spa_client.get("/favicon.svg")
    assert resp.status_code == 200
    assert "svg" in resp.headers.get("content-type", "").lower() or resp.content[:5] == b"<svg "
