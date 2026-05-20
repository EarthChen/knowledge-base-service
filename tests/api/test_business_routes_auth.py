"""Business mutating routes require appropriate roles when require_auth is enabled."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

import core.auth as auth


@pytest.fixture
def require_auth_no_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REQUIRE_AUTH", "true")
    monkeypatch.setattr(auth, "_build_token_registry", lambda _s: {})
    auth._token_registry = None
    import core.config as config_module

    config_module.get_settings.cache_clear()
    yield
    config_module.get_settings.cache_clear()


async def test_create_business_requires_auth(require_auth_no_tokens: None) -> None:
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/v1/businesses", json={"name": "test", "description": "test"})
    assert r.status_code in (401, 403)


async def test_update_business_requires_auth(require_auth_no_tokens: None) -> None:
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.put(
            "/api/v1/businesses/business:abc",
            json={"name": "n", "description": "d"},
        )
    assert r.status_code in (401, 403)


async def test_delete_business_requires_auth(require_auth_no_tokens: None) -> None:
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.delete("/api/v1/businesses/business:abc")
    assert r.status_code in (401, 403)


async def test_bind_repositories_requires_auth(require_auth_no_tokens: None) -> None:
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.put(
            "/api/v1/businesses/business:abc/repositories",
            json={"repositories": ["repo-a"]},
        )
    assert r.status_code in (401, 403)
