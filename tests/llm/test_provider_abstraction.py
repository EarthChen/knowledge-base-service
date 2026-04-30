"""Tests for BaseLLMProvider, GatewayLLMProviderAdapter, factory, and LLMPortBridge."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from llm.base_provider import GatewayLLMProviderAdapter, LLMPortBridge
from llm.provider_factory import LLMProviderFactory, ProviderConfig

# --- GatewayLLMProviderAdapter ---


@pytest.mark.asyncio
async def test_gateway_adapter_complete() -> None:
    inner = MagicMock()
    inner.complete = AsyncMock(return_value="delegated")
    adapter = GatewayLLMProviderAdapter(inner)
    messages = [{"role": "user", "content": "hi"}]
    result = await adapter.complete(messages, model="m", temperature=0.5)
    inner.complete.assert_awaited_once_with(messages, model="m", temperature=0.5)
    assert result == "delegated"


@pytest.mark.asyncio
async def test_gateway_adapter_complete_json() -> None:
    inner = MagicMock()
    inner.complete_json = AsyncMock(return_value={"ok": True})
    adapter = GatewayLLMProviderAdapter(inner)
    messages = [{"role": "user", "content": "x"}]
    schema = {"type": "object"}
    result = await adapter.complete_json(messages, schema, model="m")
    inner.complete_json.assert_awaited_once_with(messages, schema, model="m")
    assert result == {"ok": True}


def test_gateway_adapter_provider_name() -> None:
    inner = MagicMock()
    adapter = GatewayLLMProviderAdapter(inner)
    assert adapter.provider_name == "gateway"


def test_gateway_adapter_supports_streaming() -> None:
    inner = MagicMock()
    adapter = GatewayLLMProviderAdapter(inner)
    assert adapter.supports_streaming is True


def test_gateway_adapter_max_context_tokens() -> None:
    inner = MagicMock()
    adapter = GatewayLLMProviderAdapter(inner)
    assert isinstance(adapter.max_context_tokens, int)
    assert adapter.max_context_tokens > 0


@pytest.mark.asyncio
async def test_gateway_adapter_close() -> None:
    inner = MagicMock()
    inner.close = AsyncMock()
    adapter = GatewayLLMProviderAdapter(inner)
    await adapter.close()
    inner.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_gateway_adapter_complete_stream() -> None:
    # spec avoids MagicMock auto-adding complete_stream (adapter would otherwise
    # delegate to a mock async iterator that yields nothing).
    inner = MagicMock(spec=["complete"])
    inner.complete = AsyncMock(return_value="full")
    adapter = GatewayLLMProviderAdapter(inner)
    chunks: list[str] = []
    async for piece in adapter.complete_stream([{"role": "user", "content": "q"}]):
        chunks.append(piece)
    assert chunks == ["full"]
    inner.complete.assert_awaited()


# --- LLMProviderFactory ---


def test_factory_default_provider() -> None:
    gw = MagicMock()
    gw.complete = AsyncMock()
    gw.close = AsyncMock()
    factory = LLMProviderFactory(ProviderConfig(default_provider="gateway"), gateway_provider=gw)
    assert factory.get_provider() is gw


def test_factory_named_provider() -> None:
    gw = MagicMock()
    gw.complete = AsyncMock()
    gw.close = AsyncMock()
    factory = LLMProviderFactory(ProviderConfig(), gateway_provider=gw)
    assert factory.get_provider("gateway") is gw


@pytest.mark.asyncio
async def test_factory_fallback_on_error() -> None:
    primary = MagicMock()
    primary.complete = AsyncMock(side_effect=ConnectionError("primary down"))
    primary.close = AsyncMock()

    secondary = MagicMock()
    secondary.complete = AsyncMock(return_value="from secondary")
    secondary.close = AsyncMock()

    config = ProviderConfig(default_provider="primary", fallback_provider="secondary")
    factory = LLMProviderFactory(config)
    factory._providers["primary"] = primary  # noqa: SLF001
    factory._providers["secondary"] = secondary  # noqa: SLF001

    result = await factory.complete_with_fallback([{"role": "user", "content": "x"}])
    assert result == "from secondary"
    secondary.complete.assert_awaited_once()


@pytest.mark.asyncio
async def test_factory_fallback_none() -> None:
    primary = MagicMock()
    primary.complete = AsyncMock(side_effect=ConnectionError("boom"))
    primary.close = AsyncMock()

    config = ProviderConfig(default_provider="primary", fallback_provider=None)
    factory = LLMProviderFactory(config)
    factory._providers["primary"] = primary  # noqa: SLF001

    with pytest.raises(ConnectionError, match="boom"):
        await factory.complete_with_fallback([{"role": "user", "content": "x"}])


def test_factory_list_providers() -> None:
    gw = MagicMock()
    factory = LLMProviderFactory(
        ProviderConfig(providers={"openai": {"x": 1}}),
        gateway_provider=gw,
    )
    names = factory.list_providers()
    assert names == ["gateway", "openai"]


def test_factory_list_providers_inserts_gateway_when_absent() -> None:
    """``gateway`` is listed even when not yet registered or present in config."""
    factory = LLMProviderFactory(ProviderConfig(providers={"openai": {}}))
    assert factory.list_providers() == ["gateway", "openai"]


def test_factory_unknown_provider() -> None:
    factory = LLMProviderFactory(ProviderConfig(), gateway_provider=MagicMock())
    with pytest.raises(ValueError, match="not configured"):
        factory.get_provider("unknown")


@pytest.mark.asyncio
async def test_factory_close_all() -> None:
    a = MagicMock()
    a.close = AsyncMock()
    b = MagicMock()
    b.close = AsyncMock()

    factory = LLMProviderFactory(ProviderConfig(), gateway_provider=a)
    factory._providers["extra"] = b  # noqa: SLF001

    await factory.close_all()
    a.close.assert_awaited_once()
    b.close.assert_awaited_once()


# --- LLMPortBridge ---


@pytest.mark.asyncio
async def test_bridge_generate_with_system() -> None:
    prov = MagicMock()
    prov.supports_streaming = False
    prov.complete = AsyncMock(return_value="out")
    bridge = LLMPortBridge(prov)
    result = await bridge.generate("user text", system="sys")
    prov.complete.assert_awaited_once_with(
        [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "user text"},
        ],
        model=None,
    )
    assert result == "out"


@pytest.mark.asyncio
async def test_bridge_generate_no_system() -> None:
    prov = MagicMock()
    prov.supports_streaming = False
    prov.complete = AsyncMock(return_value="only user")
    bridge = LLMPortBridge(prov)
    result = await bridge.generate("hello")
    prov.complete.assert_awaited_once_with(
        [{"role": "user", "content": "hello"}],
        model=None,
    )
    assert result == "only user"


@pytest.mark.asyncio
async def test_bridge_generate_passes_model_to_complete() -> None:
    prov = MagicMock()
    prov.supports_streaming = False
    prov.complete = AsyncMock(return_value="out")
    bridge = LLMPortBridge(prov)
    result = await bridge.generate("q", system="s", model="cheap-model")
    prov.complete.assert_awaited_once_with(
        [
            {"role": "system", "content": "s"},
            {"role": "user", "content": "q"},
        ],
        model="cheap-model",
    )
    assert result == "out"


@pytest.mark.asyncio
async def test_bridge_generate_always_uses_complete() -> None:
    """generate() always uses complete(), even when streaming is available."""
    provider = MagicMock()
    provider.supports_streaming = True
    provider.complete = AsyncMock(return_value="complete result")

    bridge = LLMPortBridge(provider)
    result = await bridge.generate("test prompt", system="sys")

    assert result == "complete result"
    provider.complete.assert_awaited_once()


@pytest.mark.asyncio
async def test_bridge_generate_fallback_no_streaming() -> None:
    """When provider does not support streaming, generate() falls back to complete()."""
    provider = MagicMock()
    provider.supports_streaming = False
    provider.complete = AsyncMock(return_value="non-stream result")

    bridge = LLMPortBridge(provider)
    result = await bridge.generate("prompt")

    assert result == "non-stream result"
    provider.complete.assert_awaited_once()


@pytest.mark.asyncio
async def test_bridge_collect_stream_retries_on_transport_error() -> None:
    """_collect_stream retries on httpx.TransportError, returns result on success."""
    import httpx

    provider = MagicMock()
    provider.supports_streaming = True
    call_count = 0

    async def flaky_stream(messages, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise httpx.ReadError("connection reset")
        for chunk in ["retry", " ", "ok"]:
            yield chunk

    provider.complete_stream = MagicMock(side_effect=flaky_stream)

    bridge = LLMPortBridge(provider)
    result = await bridge.generate_stream("prompt", system="sys")

    assert result == "retry ok"
    assert call_count == 2
