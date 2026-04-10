import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from config import LLMConfig


@pytest.fixture
def llm_config():
    return LLMConfig(
        enabled=True,
        base_url="https://api.openai.com/v1",
        api_key="test-key",
        model="gpt-4o-mini",
    )


class TestLLMProvider:
    @pytest.mark.asyncio
    async def test_complete_returns_string(self, llm_config):
        from llm.provider import LLMProvider

        provider = LLMProvider(llm_config)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "test response"}}]
        }
        mock_response.raise_for_status = MagicMock()
        with patch.object(provider, "_client") as mock_client:
            mock_client.post = AsyncMock(return_value=mock_response)
            result = await provider.complete([{"role": "user", "content": "hello"}])
        assert result == "test response"

    @pytest.mark.asyncio
    async def test_complete_json_returns_dict(self, llm_config):
        from llm.provider import LLMProvider

        provider = LLMProvider(llm_config)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": '{"name": "test"}'}}]
        }
        mock_response.raise_for_status = MagicMock()
        with patch.object(provider, "_client") as mock_client:
            mock_client.post = AsyncMock(return_value=mock_response)
            result = await provider.complete_json(
                [{"role": "user", "content": "hello"}],
                schema={"type": "object"},
            )
        assert result == {"name": "test"}

    @pytest.mark.asyncio
    async def test_complete_retries_on_failure(self, llm_config):
        from llm.provider import LLMProvider
        import httpx

        llm_config.retry_count = 2
        provider = LLMProvider(llm_config)
        fail_resp = MagicMock()
        fail_resp.status_code = 500
        fail_resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "Server Error", request=MagicMock(), response=fail_resp
            )
        )
        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.raise_for_status = MagicMock()
        ok_resp.json.return_value = {
            "choices": [{"message": {"content": "ok"}}]
        }
        with patch.object(provider, "_client") as mock_client:
            mock_client.post = AsyncMock(side_effect=[fail_resp, ok_resp])
            result = await provider.complete([{"role": "user", "content": "hi"}])
        assert result == "ok"
