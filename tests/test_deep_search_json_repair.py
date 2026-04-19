from __future__ import annotations

import logging

import pytest

from query.deep_search import _parse_json_object_from_llm


def test_valid_json_passes_without_repair_warning(caplog: pytest.LogCaptureFixture) -> None:
    text = '{"intent": "search", "sub_queries": []}'
    with caplog.at_level(logging.WARNING):
        result = _parse_json_object_from_llm(text)
    assert result == {"intent": "search", "sub_queries": []}
    repair_warnings = [
        r
        for r in caplog.records
        if "json_repair" in r.message.lower() or "malformed" in r.message.lower()
    ]
    assert not repair_warnings


def test_trailing_commas_repaired_and_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    text = '{"a": 1,}'
    with caplog.at_level(logging.WARNING):
        result = _parse_json_object_from_llm(text)
    assert result == {"a": 1}
    assert any(
        "repair" in r.message.lower() or "malformed" in r.message.lower()
        for r in caplog.records
    )


def test_missing_quotes_on_keys_repaired(caplog: pytest.LogCaptureFixture) -> None:
    text = '{foo: "bar"}'
    with caplog.at_level(logging.WARNING):
        result = _parse_json_object_from_llm(text)
    assert result == {"foo": "bar"}
    assert any("malformed" in r.message.lower() for r in caplog.records)


def test_json_embedded_in_markdown_code_block(caplog: pytest.LogCaptureFixture) -> None:
    text = """Here you go:

```json
{"ok": true, "items": [1, 2],}
```
"""
    with caplog.at_level(logging.WARNING):
        result = _parse_json_object_from_llm(text)
    assert result == {"ok": True, "items": [1, 2]}
    assert any("malformed" in r.message.lower() for r in caplog.records)


def test_completely_invalid_text_returns_none() -> None:
    assert _parse_json_object_from_llm("not json at all {{{") is None
