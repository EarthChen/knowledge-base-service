from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock


class TestCompleteJsonStrict:
    """Tests for F4: complete_json uses json_schema + strict when schema provided."""

    @pytest.mark.asyncio
    async def test_schema_used_in_request(self):
        from llm.openai_provider import OpenAIProvider

        provider = OpenAIProvider.__new__(OpenAIProvider)
        provider._model = "test-model"
        provider._temperature = 0.0
        provider._semaphore = AsyncMock()

        captured_body = {}

        async def mock_request(body):
            captured_body.update(body)
            return {"choices": [{"message": {"content": json.dumps({"title": "test"})}}]}

        provider._request_json = mock_request

        schema = {"title": "TestOutput", "type": "object", "properties": {"title": {"type": "string"}}}
        result = await provider.complete_json(
            [{"role": "user", "content": "hi"}],
            schema,
        )

        assert captured_body["response_format"]["type"] == "json_schema"
        assert captured_body["response_format"]["json_schema"]["strict"] is True
        sent_schema = captured_body["response_format"]["json_schema"]["schema"]
        assert sent_schema["title"] == "TestOutput"
        assert sent_schema["type"] == "object"
        assert sent_schema["additionalProperties"] is False
        assert "title" in sent_schema.get("required", [])
        assert captured_body["response_format"]["json_schema"]["name"] == "TestOutput"
        assert result == {"title": "test"}

    @pytest.mark.asyncio
    async def test_empty_schema_falls_back_to_json_object(self):
        from llm.openai_provider import OpenAIProvider

        provider = OpenAIProvider.__new__(OpenAIProvider)
        provider._model = "test-model"
        provider._temperature = 0.0
        provider._semaphore = AsyncMock()

        captured_body = {}

        async def mock_request(body):
            captured_body.update(body)
            return {"choices": [{"message": {"content": json.dumps({"key": "value"})}}]}

        provider._request_json = mock_request

        result = await provider.complete_json(
            [{"role": "user", "content": "hi"}],
            {},
        )

        assert captured_body["response_format"]["type"] == "json_object"
        assert result == {"key": "value"}

    @pytest.mark.asyncio
    async def test_custom_provider_strict(self):
        from llm.custom_provider import CustomOpenAIProvider

        provider = CustomOpenAIProvider.__new__(CustomOpenAIProvider)
        provider._model = "test-model"
        provider._temperature = 0.0
        provider._semaphore = AsyncMock()

        captured_body = {}

        async def mock_request(body):
            captured_body.update(body)
            return {"choices": [{"message": {"content": json.dumps({"ok": True})}}]}

        provider._request_json = mock_request

        schema = {"title": "Output", "type": "object", "properties": {"ok": {"type": "boolean"}}}
        result = await provider.complete_json(
            [{"role": "user", "content": "hi"}],
            schema,
        )

        assert captured_body["response_format"]["type"] == "json_schema"
        assert captured_body["response_format"]["json_schema"]["strict"] is True
        assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_azure_provider_strict(self):
        from llm.azure_provider import AzureOpenAIProvider

        provider = AzureOpenAIProvider.__new__(AzureOpenAIProvider)
        provider._temperature = 0.0
        provider._semaphore = AsyncMock()

        captured_body = {}

        async def mock_request(body):
            captured_body.update(body)
            return {"choices": [{"message": {"content": json.dumps({"ok": True})}}]}

        provider._request_json = mock_request

        schema = {"title": "Output", "type": "object", "properties": {"ok": {"type": "boolean"}}}
        result = await provider.complete_json(
            [{"role": "user", "content": "hi"}],
            schema,
        )

        assert captured_body["response_format"]["type"] == "json_schema"
        assert captured_body["response_format"]["json_schema"]["strict"] is True
        assert "model" not in captured_body
        assert result == {"ok": True}
