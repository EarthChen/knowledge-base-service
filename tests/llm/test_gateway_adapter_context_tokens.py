from __future__ import annotations

from unittest.mock import MagicMock

from llm.base_provider import GatewayLLMProviderAdapter


def test_default_max_context_tokens():
    inner = MagicMock()
    adapter = GatewayLLMProviderAdapter(inner)
    assert adapter.max_context_tokens == 128_000


def test_explicit_max_context_tokens():
    inner = MagicMock()
    adapter = GatewayLLMProviderAdapter(inner, max_context_tokens=200_000)
    assert adapter.max_context_tokens == 200_000


def test_max_context_tokens_from_inner_config():
    inner = MagicMock()
    inner._config = MagicMock()
    inner._config.max_context_tokens = 64_000
    adapter = GatewayLLMProviderAdapter(inner)
    assert adapter.max_context_tokens == 64_000
