"""Tests for GET /api/v1/llm/providers and wiki llm_provider override."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

import core.auth as auth_module
from api.routes.provider_routes import provider_router
from core.config import LLMConfig, Settings
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
