"""Tests for log.setup_logging LOG_FORMAT switching."""

from __future__ import annotations

import json

import pytest
import structlog

from core.log import get_logger, setup_logging


@pytest.fixture(autouse=True)
def reset_structlog() -> None:
    structlog.reset_defaults()
    yield
    structlog.reset_defaults()


def test_setup_logging_json_emits_parseable_json(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("LOG_FORMAT", "json")
    setup_logging()
    get_logger("test_log_json").info("hello_event", answer=42)
    err = capsys.readouterr().out
    line = err.strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["event"] == "hello_event"
    assert payload["answer"] == 42
    assert "timestamp" in payload


def test_setup_logging_default_uses_console_not_json(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    setup_logging()
    get_logger("test_log_console").info("plain")
    out = capsys.readouterr().out
    # ConsoleRenderer human output, not a single JSON object line
    with pytest.raises(json.JSONDecodeError):
        json.loads(out.strip().splitlines()[-1])
