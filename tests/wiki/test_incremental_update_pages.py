"""Tests for P3.9: LLM-guided incremental page update."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from wiki.nodes.compose import _incremental_update_pages, _INCREMENTAL_CHANGE_RATIO


class TestIncrementalUpdatePages:
    @pytest.mark.asyncio
    async def test_returns_updated_pages_on_success(self):
        llm = AsyncMock()
        llm.complete_json = AsyncMock(return_value="# Updated Content\nNew stuff here.")

        old_pages = [{"title": "Payment", "content": "# Payment\nOld content.", "path": "/wiki/payment"}]
        new_summaries = {"NewService": "Handles new payment method"}

        with patch("wiki.nodes.compose.LLMPort", llm.__class__):
            result = await _incremental_update_pages("Payment", old_pages, new_summaries, llm)

        assert result is not None
        assert len(result) == 1
        assert result[0]["title"] == "Payment"

    @pytest.mark.asyncio
    async def test_returns_none_when_no_old_pages(self):
        llm = AsyncMock()
        result = await _incremental_update_pages("Payment", [], {"New": "summary"}, llm)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_new_summaries(self):
        llm = AsyncMock()
        old_pages = [{"title": "Payment", "content": "content", "path": "/p"}]
        result = await _incremental_update_pages("Payment", old_pages, {}, llm)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_llm(self):
        old_pages = [{"title": "Payment", "content": "content", "path": "/p"}]
        result = await _incremental_update_pages("Payment", old_pages, {"New": "s"}, None)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_llm_failure(self):
        llm = AsyncMock()
        llm.complete_json = AsyncMock(side_effect=RuntimeError("LLM error"))

        old_pages = [{"title": "Payment", "content": "content", "path": "/p"}]

        with patch("wiki.nodes.compose.LLMPort", llm.__class__):
            result = await _incremental_update_pages("Payment", old_pages, {"New": "s"}, llm)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_page_content_empty(self):
        llm = AsyncMock()
        old_pages = [{"title": "Payment", "content": "", "path": "/p"}]
        result = await _incremental_update_pages("Payment", old_pages, {"New": "s"}, llm)
        assert result is None

    def test_change_ratio_constant_defined(self):
        assert _INCREMENTAL_CHANGE_RATIO == 0.3
