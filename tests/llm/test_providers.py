"""Tests for OpenAI, Azure, Custom providers and factory integration."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from llm.azure_provider import AzureOpenAIProvider
from llm.custom_provider import CustomOpenAIProvider
from llm.openai_provider import OpenAIProvider
from llm.provider_factory import LLMProviderFactory, ProviderConfig

SUCCESS_BODY = {
    "choices": [
        {
            "message": {
                "role": "assistant",
                "content": "hello world",
            }
        }
    ]
}


def _make_openai_transport(
    *,
    fail_once: bool = False,
    fail_always: bool = False,
) -> tuple[httpx.MockTransport, list[int]]:
    """HTTP handler for OpenAI-style /chat/completions."""
    attempts = [0]

    def handler(request: httpx.Request) -> httpx.Response:
        attempts[0] += 1
        assert request.headers.get("authorization") == "Bearer sk-test-key"
        if fail_always:
            return httpx.Response(500)
        if fail_once and attempts[0] == 1:
            return httpx.Response(500)
        return httpx.Response(200, json=SUCCESS_BODY)

    return httpx.MockTransport(handler), attempts


@pytest.fixture
def patch_openai_async_client():
    """Patch AsyncClient factory used by OpenAIProvider."""

    def _patch(transport: httpx.MockTransport):
        real_build = httpx.AsyncClient

        def factory(*args, **kwargs):
            kwargs["transport"] = transport
            return real_build(*args, **kwargs)

        return patch("llm.openai_provider.httpx.AsyncClient", side_effect=factory)

    return _patch


@pytest.mark.asyncio
async def test_openai_complete(patch_openai_async_client) -> None:
    transport, _ = _make_openai_transport()
    with patch_openai_async_client(transport):
        p = OpenAIProvider(api_key="sk-test-key", model="gpt-4o-mini")
        out = await p.complete([{"role": "user", "content": "hi"}])
        assert out == "hello world"
        await p.close()


@pytest.mark.asyncio
async def test_openai_complete_json(patch_openai_async_client) -> None:
    json_body = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": json.dumps({"a": 1}),
                }
            }
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        req_body = json.loads(request.content.decode())
        rf = req_body.get("response_format", {})
        assert rf.get("type") == "json_schema"
        assert rf.get("json_schema", {}).get("strict") is True
        return httpx.Response(200, json=json_body)

    transport = httpx.MockTransport(handler)
    with patch_openai_async_client(transport):
        p = OpenAIProvider(api_key="sk-test-key")
        result = await p.complete_json([{"role": "user", "content": "x"}], schema={"type": "object"})
        assert result == {"a": 1}
        await p.close()


def test_openai_provider_name(patch_openai_async_client) -> None:
    transport, _ = _make_openai_transport()
    with patch_openai_async_client(transport):
        p = OpenAIProvider(api_key="sk-test-key")
        assert p.provider_name == "openai"


def test_openai_supports_streaming(patch_openai_async_client) -> None:
    transport, _ = _make_openai_transport()
    with patch_openai_async_client(transport):
        p = OpenAIProvider(api_key="sk-test-key")
        assert p.supports_streaming is True


@pytest.mark.asyncio
async def test_openai_retry_on_failure(patch_openai_async_client) -> None:
    transport, _ = _make_openai_transport(fail_once=True)
    with patch_openai_async_client(transport):
        with patch("llm.openai_provider.asyncio.sleep", new_callable=AsyncMock):
            p = OpenAIProvider(api_key="sk-test-key", retry_count=3)
            out = await p.complete([{"role": "user", "content": "hi"}])
            assert out == "hello world"
            await p.close()


@pytest.mark.asyncio
async def test_openai_close(patch_openai_async_client) -> None:
    transport, _ = _make_openai_transport()
    with patch_openai_async_client(transport):
        p = OpenAIProvider(api_key="sk-test-key")
        await p.close()


# --- Azure ---


def _azure_transport_ok() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "api-key" in request.headers
        assert request.headers["api-key"] == "azure-key"
        assert "authorization" not in {k.lower() for k in request.headers}
        q = str(request.url)
        assert "api-version=2024-02-15-preview" in q
        assert "/chat/completions" in q
        assert "myresource.openai.azure.com" in q
        assert "/openai/deployments/my-deploy/" in q or "deployments/my-deploy" in q
        return httpx.Response(200, json=SUCCESS_BODY)

    return httpx.MockTransport(handler)


@pytest.fixture
def patch_azure_async_client():
    def _patch(transport: httpx.MockTransport):
        real_build = httpx.AsyncClient

        def factory(*args, **kwargs):
            kwargs["transport"] = transport
            return real_build(*args, **kwargs)

        return patch("llm.azure_provider.httpx.AsyncClient", side_effect=factory)

    return _patch


@pytest.mark.asyncio
async def test_azure_complete(patch_azure_async_client) -> None:
    transport = _azure_transport_ok()
    with patch_azure_async_client(transport):
        p = AzureOpenAIProvider(
            api_key="azure-key",
            resource_name="myresource",
            deployment_name="my-deploy",
        )
        out = await p.complete([{"role": "user", "content": "hi"}])
        assert out == "hello world"
        await p.close()


@pytest.mark.asyncio
async def test_azure_api_version_in_url(patch_azure_async_client) -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json=SUCCESS_BODY)

    transport = httpx.MockTransport(handler)
    with patch_azure_async_client(transport):
        p = AzureOpenAIProvider(
            api_key="k",
            resource_name="r",
            deployment_name="d",
            api_version="2024-02-15-preview",
        )
        await p.complete([{"role": "user", "content": "x"}])
        await p.close()
    assert "api-version=2024-02-15-preview" in captured["url"]


@pytest.mark.asyncio
async def test_azure_auth_header(patch_azure_async_client) -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = dict(request.headers)
        return httpx.Response(200, json=SUCCESS_BODY)

    transport = httpx.MockTransport(handler)
    with patch_azure_async_client(transport):
        p = AzureOpenAIProvider(api_key="secret-azure", resource_name="x", deployment_name="y")
        await p.complete([{"role": "user", "content": "z"}])
        await p.close()
    assert seen["headers"].get("api-key") == "secret-azure"
    assert not any(k.lower() == "authorization" for k in seen["headers"])


def test_azure_provider_name(patch_azure_async_client) -> None:
    transport = _azure_transport_ok()
    with patch_azure_async_client(transport):
        p = AzureOpenAIProvider(api_key="k", resource_name="r", deployment_name="d")
        assert p.provider_name == "azure"


@pytest.mark.asyncio
async def test_azure_close(patch_azure_async_client) -> None:
    transport = _azure_transport_ok()
    with patch_azure_async_client(transport):
        p = AzureOpenAIProvider(api_key="k", resource_name="r", deployment_name="d")
        await p.close()


# --- Custom ---


@pytest.fixture
def patch_custom_async_client():
    def _patch(transport: httpx.MockTransport):
        real_build = httpx.AsyncClient

        def factory(*args, **kwargs):
            kwargs["transport"] = transport
            return real_build(*args, **kwargs)

        return patch("llm.custom_provider.httpx.AsyncClient", side_effect=factory)

    return _patch


@pytest.mark.asyncio
async def test_custom_complete(patch_custom_async_client) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith("http://localhost:11434/v1/chat/completions")
        return httpx.Response(200, json=SUCCESS_BODY)

    transport = httpx.MockTransport(handler)
    with patch_custom_async_client(transport):
        p = CustomOpenAIProvider(
            base_url="http://localhost:11434/v1",
            api_key="optional",
            model="llama3",
        )
        out = await p.complete([{"role": "user", "content": "hi"}])
        assert out == "hello world"
        await p.close()


@pytest.mark.asyncio
async def test_custom_no_auth(patch_custom_async_client) -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = dict(request.headers)
        return httpx.Response(200, json=SUCCESS_BODY)

    transport = httpx.MockTransport(handler)
    with patch_custom_async_client(transport):
        p = CustomOpenAIProvider(base_url="http://127.0.0.1:8080/v1", api_key="")
        await p.complete([{"role": "user", "content": "x"}])
        await p.close()
    assert "authorization" not in {k.lower() for k in seen["headers"]}


def test_custom_provider_name(patch_custom_async_client) -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json=SUCCESS_BODY))
    with patch_custom_async_client(transport):
        p = CustomOpenAIProvider(base_url="http://x/v1")
        assert p.provider_name == "custom"


# --- Factory ---


@pytest.mark.asyncio
async def test_factory_create_openai(patch_openai_async_client) -> None:
    transport, _ = _make_openai_transport()
    with patch_openai_async_client(transport):
        cfg = ProviderConfig(
            default_provider="openai",
            providers={
                "openai": {
                    "api_key": "sk-test-key",
                    "model": "gpt-4o-mini",
                }
            },
        )
        factory = LLMProviderFactory(cfg)
        prov = factory.get_provider("openai")
        assert prov.provider_name == "openai"
        out = await prov.complete([{"role": "user", "content": "q"}])
        assert out == "hello world"
        await factory.close_all()


@pytest.mark.asyncio
async def test_factory_create_azure(patch_azure_async_client) -> None:
    transport = _azure_transport_ok()
    with patch_azure_async_client(transport):
        cfg = ProviderConfig(
            default_provider="azure",
            providers={
                "azure": {
                    "api_key": "azure-key",
                    "resource_name": "myresource",
                    "deployment_name": "my-deploy",
                }
            },
        )
        factory = LLMProviderFactory(cfg)
        prov = factory.get_provider("azure")
        assert prov.provider_name == "azure"
        out = await prov.complete([{"role": "user", "content": "q"}])
        assert out == "hello world"
        await factory.close_all()


@pytest.mark.asyncio
async def test_factory_create_custom(patch_custom_async_client) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=SUCCESS_BODY)

    transport = httpx.MockTransport(handler)
    with patch_custom_async_client(transport):
        cfg = ProviderConfig(
            default_provider="custom",
            providers={
                "custom": {
                    "base_url": "http://localhost:11434/v1",
                    "model": "m",
                }
            },
        )
        factory = LLMProviderFactory(cfg)
        prov = factory.get_provider("custom")
        assert prov.provider_name == "custom"
        out = await prov.complete([{"role": "user", "content": "q"}])
        assert out == "hello world"
        await factory.close_all()


@pytest.mark.asyncio
async def test_factory_fallback_openai_to_azure(patch_openai_async_client, patch_azure_async_client) -> None:
    openai_transport, _ = _make_openai_transport(fail_always=True)
    azure_transport = _azure_transport_ok()

    real_build = httpx.AsyncClient

    def combined_factory(*args, **kwargs):
        base = str(kwargs.get("base_url", "") or "")
        if "azure.com" in base:
            kwargs["transport"] = azure_transport
        else:
            kwargs["transport"] = openai_transport
        return real_build(*args, **kwargs)

    with (
        patch("llm.openai_provider.httpx.AsyncClient", side_effect=combined_factory),
        patch("llm.azure_provider.httpx.AsyncClient", side_effect=combined_factory),
        patch("llm.openai_provider.asyncio.sleep", new_callable=AsyncMock),
    ):
        cfg = ProviderConfig(
            default_provider="openai",
            fallback_provider="azure",
            providers={
                "openai": {"api_key": "sk-test-key"},
                "azure": {
                    "api_key": "azure-key",
                    "resource_name": "myresource",
                    "deployment_name": "my-deploy",
                },
            },
        )
        factory = LLMProviderFactory(cfg)
        result = await factory.complete_with_fallback([{"role": "user", "content": "x"}])
        assert result == "hello world"
        await factory.close_all()
