"""Tests for LLMPortBridge extra_params support."""
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_provider():
    provider = MagicMock()
    provider.complete = AsyncMock(return_value="LLM response")
    provider.supports_streaming = False
    return provider


@pytest.mark.asyncio
async def test_generate_forwards_extra_params(mock_provider):
    from llm.base_provider import LLMPortBridge

    bridge = LLMPortBridge(mock_provider)
    result = await bridge.generate(
        "test prompt",
        system="be helpful",
        model="qwen3",
        extra_params={"chat_template_kwargs": {"enable_thinking": False}},
    )

    assert result == "LLM response"
    mock_provider.complete.assert_called_once()
    call_kwargs = mock_provider.complete.call_args[1]
    assert call_kwargs["chat_template_kwargs"] == {"enable_thinking": False}


@pytest.mark.asyncio
async def test_generate_without_extra_params(mock_provider):
    from llm.base_provider import LLMPortBridge

    bridge = LLMPortBridge(mock_provider)
    result = await bridge.generate("test prompt", model="qwen3")

    assert result == "LLM response"
    mock_provider.complete.assert_called_once()


@pytest.mark.asyncio
async def test_complete_passes_kwargs(mock_provider):
    from llm.base_provider import LLMPortBridge

    bridge = LLMPortBridge(mock_provider)
    result = await bridge.complete(
        [{"role": "user", "content": "hello"}],
        model="qwen3",
        temperature=0.1,
    )

    assert result == "LLM response"
    call_kwargs = mock_provider.complete.call_args[1]
    assert call_kwargs["model"] == "qwen3"
    assert call_kwargs["temperature"] == 0.1
