"""Tests for LLMPortChatModel adapter."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage


@pytest.fixture
def mock_bridge():
    bridge = MagicMock()
    bridge.complete = AsyncMock(return_value="Hello from LLM")
    return bridge


@pytest.mark.asyncio
async def test_agenerate_converts_messages(mock_bridge):
    from wiki.langchain_adapter import LLMPortChatModel

    model = LLMPortChatModel(bridge=mock_bridge)
    messages = [
        SystemMessage(content="You are helpful."),
        HumanMessage(content="Say hello"),
    ]
    result = await model.ainvoke(messages)

    assert isinstance(result, AIMessage)
    assert result.content == "Hello from LLM"

    mock_bridge.complete.assert_called_once()
    call_args = mock_bridge.complete.call_args
    lm_messages = call_args[0][0]
    assert lm_messages[0] == {"role": "system", "content": "You are helpful."}
    assert lm_messages[1] == {"role": "user", "content": "Say hello"}


@pytest.mark.asyncio
async def test_agenerate_passes_model_kwarg(mock_bridge):
    from wiki.langchain_adapter import LLMPortChatModel

    model = LLMPortChatModel(bridge=mock_bridge, model_name="qwen3")
    messages = [HumanMessage(content="test")]
    await model.ainvoke(messages, model="qwen3-fast")

    call_kwargs = mock_bridge.complete.call_args[1]
    assert call_kwargs.get("model") == "qwen3-fast"


def test_sync_generate_raises(mock_bridge):
    from wiki.langchain_adapter import LLMPortChatModel

    model = LLMPortChatModel(bridge=mock_bridge)
    with pytest.raises(NotImplementedError):
        model.invoke([HumanMessage(content="test")])


def test_llm_type(mock_bridge):
    from wiki.langchain_adapter import LLMPortChatModel

    model = LLMPortChatModel(bridge=mock_bridge)
    assert model._llm_type == "llm-port-bridge"
