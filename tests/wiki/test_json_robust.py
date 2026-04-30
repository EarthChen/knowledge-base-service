"""Tests for robust JSON parsing with 3-level repair."""
import pytest
from unittest.mock import AsyncMock, MagicMock


def test_parse_valid_json():
    from wiki.json_robust import parse_json_robust_sync
    result = parse_json_robust_sync('{"key": "value"}')
    assert result == {"key": "value"}


def test_parse_json_with_markdown_fences():
    from wiki.json_robust import parse_json_robust_sync
    raw = '```json\n{"key": "value"}\n```'
    result = parse_json_robust_sync(raw)
    assert result == {"key": "value"}


def test_parse_json_with_trailing_comma():
    from wiki.json_robust import parse_json_robust_sync
    raw = '{"key": "value",}'
    result = parse_json_robust_sync(raw)
    assert result is not None
    assert result["key"] == "value"


def test_parse_json_with_unclosed_bracket():
    from wiki.json_robust import parse_json_robust_sync
    raw = '{"domains": {"auth": ["UserService", "AuthController"]}'
    result = parse_json_robust_sync(raw)
    assert result is not None
    assert "domains" in result


def test_parse_json_array():
    from wiki.json_robust import parse_json_robust_sync
    result = parse_json_robust_sync('[1, 2, 3]')
    assert result == [1, 2, 3]


def test_parse_totally_invalid_returns_none():
    from wiki.json_robust import parse_json_robust_sync
    result = parse_json_robust_sync("This is not JSON at all. Just plain text.")
    assert result is None


@pytest.mark.asyncio
async def test_async_parse_with_llm_fallback():
    from wiki.json_robust import parse_json_robust

    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(return_value=MagicMock(content='{"fixed": true}'))

    result = await parse_json_robust(
        "totally broken {{{not json",
        llm=mock_llm,
    )
    assert result is not None


@pytest.mark.asyncio
async def test_async_parse_valid_skips_llm():
    from wiki.json_robust import parse_json_robust

    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock()

    result = await parse_json_robust('{"ok": true}', llm=mock_llm)
    assert result == {"ok": True}
    mock_llm.ainvoke.assert_not_called()


def test_strip_fences_handles_various_formats():
    from wiki.json_robust import _strip_fences
    assert _strip_fences('```json\n{"a":1}\n```') == '{"a":1}'
    assert _strip_fences('```\n{"a":1}\n```') == '{"a":1}'
    assert _strip_fences('{"a":1}') == '{"a":1}'
