"""Tests for GET /api/v1/llm/providers and wiki llm_provider override."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

import auth as auth_module
from api.routes.provider_routes import provider_router
from api.routes.wiki_routes import (
    WikiTaskRegistry,
    get_task_registry_dep,
    get_wiki_service_dep,
    wiki_router,
)
from config import LLMConfig, Settings
from llm.provider_factory import provider_config_from_llm


@pytest.fixture(autouse=True)
def _open_access_no_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_module, "_token_registry", {})


@pytest.fixture
def list_providers_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    settings = Settings(
        _env_file=None,
        llm=LLMConfig(
            default_provider="gateway",
            providers={"openai": {"api_key": "x"}},
        ),
    )
    monkeypatch.setattr(
        "api.routes.provider_routes.get_settings",
        lambda: settings,
    )
    app = FastAPI()
    app.include_router(provider_router)
    return TestClient(app)


@pytest.fixture
def wiki_generate_client() -> tuple[TestClient, MagicMock]:
    app = FastAPI()
    app.state.wiki_tasks = WikiTaskRegistry()

    mock_svc = MagicMock()
    mock_svc.generate = AsyncMock(
        return_value={
            "pages": [],
            "structure": {"repository": "r", "root": {}, "total_pages": 0},
            "stats": {},
            "degraded": False,
        }
    )

    async def override_wiki() -> MagicMock:
        return mock_svc

    def override_registry() -> WikiTaskRegistry:
        return app.state.wiki_tasks

    app.include_router(wiki_router)
    app.dependency_overrides[get_wiki_service_dep] = override_wiki
    app.dependency_overrides[get_task_registry_dep] = override_registry

    return TestClient(app), mock_svc


def test_list_providers(list_providers_client: TestClient) -> None:
    r = list_providers_client.get("/api/v1/llm/providers")
    assert r.status_code == 200
    body = r.json()
    assert "providers" in body
    assert isinstance(body["providers"], list)
    assert "gateway" in body["providers"]
    assert "openai" in body["providers"]


def test_list_providers_default(list_providers_client: TestClient) -> None:
    r = list_providers_client.get("/api/v1/llm/providers")
    assert r.status_code == 200
    assert r.json().get("default") == "gateway"


def test_generate_with_default_provider(wiki_generate_client: tuple) -> None:
    client, mock_svc = wiki_generate_client
    r = client.post(
        "/api/v1/wiki/generate",
        json={
            "repository": "r1",
            "scope": "module:src/a.py",
            "mode": "structure",
            "format": "json",
        },
    )
    assert r.status_code == 200
    mock_svc.generate.assert_awaited()
    kwargs = mock_svc.generate.await_args.kwargs
    assert kwargs.get("llm_provider") is None


def test_generate_with_override_provider(wiki_generate_client: tuple) -> None:
    client, mock_svc = wiki_generate_client
    r = client.post(
        "/api/v1/wiki/generate",
        json={
            "repository": "r1",
            "scope": "module:src/a.py",
            "mode": "structure",
            "format": "json",
            "llm_provider": "openai",
        },
    )
    assert r.status_code == 200
    mock_svc.generate.assert_awaited()
    kwargs = mock_svc.generate.await_args.kwargs
    assert kwargs.get("llm_provider") == "openai"


def test_provider_config_from_settings() -> None:
    llm = LLMConfig(
        default_provider="openai",
        fallback_provider="custom",
        providers={
            "openai": {"api_key": "sk-test", "model": "gpt-4o-mini"},
            "custom": {"base_url": "http://localhost:8080/v1"},
        },
    )
    pc = provider_config_from_llm(llm)
    assert pc.default_provider == "openai"
    assert pc.fallback_provider == "custom"
    assert pc.providers["openai"]["model"] == "gpt-4o-mini"

    empty_fb = LLMConfig(default_provider="gateway", fallback_provider="")
    pc2 = provider_config_from_llm(empty_fb)
    assert pc2.fallback_provider is None


def test_provider_config_legacy_llm_defaults() -> None:
    llm = LLMConfig()
    pc = provider_config_from_llm(llm)
    assert pc.default_provider == "gateway"
    assert pc.fallback_provider is None
    assert pc.providers == {}
