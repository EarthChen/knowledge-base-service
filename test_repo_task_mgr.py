"""Lightweight unit tests for gateway parsing, batch constants, and RepoTaskManager."""

from __future__ import annotations

import pytest

from indexer.incremental_indexer import _ENRICH_BATCH_SIZE
from llm.gateway_client import (
    GatewayTaskClient,
    RepoTaskManager,
    _MAX_ENTITIES_PER_ROUND,
    _format_entity,
    _parse_json_summaries,
)


class TestParseJsonSummaries:
    def test_plain_json_array(self) -> None:
        text = '[{"name": "foo", "summary": "desc a"}, {"name": "bar", "summary": "desc b"}]'
        assert _parse_json_summaries(text) == {"foo": "desc a", "bar": "desc b"}

    def test_json_inside_code_block(self) -> None:
        text = """Here is the result:
```json
[{"name": "x", "summary": "sx"}]
```
done."""
        assert _parse_json_summaries(text) == {"x": "sx"}

    def test_code_block_without_json_tag(self) -> None:
        text = """```
[{"name": "y", "summary": "sy"}]
```"""
        assert _parse_json_summaries(text) == {"y": "sy"}

    def test_malformed_returns_empty(self) -> None:
        assert _parse_json_summaries("not json at all {{{") == {}

    def test_object_not_list_returns_empty(self) -> None:
        assert _parse_json_summaries('{"name": "only", "summary": "obj"}') == {}

    def test_skips_entries_without_name(self) -> None:
        text = '[{"name": "", "summary": "x"}, {"summary": "orphan"}, {"name": "ok", "summary": "good"}]'
        assert _parse_json_summaries(text) == {"ok": "good"}


class TestFormatEntity:
    def test_minimal_name_only(self) -> None:
        out = _format_entity(0, {"name": "MyFunc"})
        assert "### 实体 1: MyFunc" in out
        assert "文件:" not in out

    def test_full_entity(self) -> None:
        item = {
            "name": "CartService",
            "file": "src/Cart.java",
            "signature": "public class CartService",
            "docstring": "Handles cart",
            "code_snippet": "class CartService {}",
        }
        out = _format_entity(2, item)
        assert "### 实体 3: CartService" in out
        assert "文件: src/Cart.java" in out
        assert "签名: public class CartService" in out
        assert "文档: Handles cart" in out
        assert "class CartService {}" in out


@pytest.mark.asyncio
class TestGatewayTaskClientEnrichBatch:
    async def test_empty_items_returns_empty_list(self) -> None:
        client = GatewayTaskClient(
            gateway_ws_url="ws://127.0.0.1:9/nope",
            gateway_http_url="http://127.0.0.1:9",
        )
        try:
            assert await client.enrich_batch([]) == []
        finally:
            await client.close()


class TestConstants:
    def test_max_entities_per_round_is_50(self) -> None:
        assert _MAX_ENTITIES_PER_ROUND == 50

    def test_enrich_batch_size_is_50(self) -> None:
        assert _ENRICH_BATCH_SIZE == 50


class TestRepoTaskManagerInit:
    def test_initialization(self) -> None:
        mgr = RepoTaskManager(
            gateway_ws_url="ws://127.0.0.1:9/acp",
            gateway_http_url="http://127.0.0.1:9",
            api_key="test-key",
            model="test-model",
            idle_timeout=120.0,
            response_timeout=60.0,
        )
        assert mgr._ws_url == "ws://127.0.0.1:9/acp"
        assert mgr._http_url == "http://127.0.0.1:9"
        assert mgr._api_key == "test-key"
        assert mgr._model == "test-model"
        assert mgr._idle_timeout == 120.0
        assert mgr._response_timeout == 60.0
        assert mgr._tasks == {}
