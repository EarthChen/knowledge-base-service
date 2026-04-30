"""Tests for StructlogCallbackHandler."""
import pytest
from unittest.mock import patch, MagicMock


@pytest.mark.asyncio
async def test_on_llm_start_logs():
    from wiki.structlog_callback import StructlogCallbackHandler
    handler = StructlogCallbackHandler()

    with patch("wiki.structlog_callback.log") as mock_log:
        await handler.on_llm_start(
            serialized={"id": ["langchain", "chat_models", "qwen3"]},
            prompts=["Hello world, this is a test prompt"],
        )
        mock_log.info.assert_called_once()
        call_kwargs = mock_log.info.call_args
        assert call_kwargs[0][0] == "llm_call_start"


@pytest.mark.asyncio
async def test_on_llm_end_logs():
    from wiki.structlog_callback import StructlogCallbackHandler
    handler = StructlogCallbackHandler()

    with patch("wiki.structlog_callback.log") as mock_log:
        mock_response = MagicMock()
        mock_response.__str__ = lambda self: "Generated response text"
        await handler.on_llm_end(response=mock_response)
        mock_log.info.assert_called_once()
        call_kwargs = mock_log.info.call_args
        assert call_kwargs[0][0] == "llm_call_done"


@pytest.mark.asyncio
async def test_on_llm_error_logs():
    from wiki.structlog_callback import StructlogCallbackHandler
    handler = StructlogCallbackHandler()

    with patch("wiki.structlog_callback.log") as mock_log:
        await handler.on_llm_error(error=RuntimeError("timeout"))
        mock_log.error.assert_called_once()
        call_kwargs = mock_log.error.call_args
        assert call_kwargs[0][0] == "llm_call_failed"
