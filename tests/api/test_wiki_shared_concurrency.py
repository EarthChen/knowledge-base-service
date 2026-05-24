"""Tests for wiki generation semaphore dependency."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from starlette.datastructures import State

from api.routes.wiki_shared import get_wiki_generation_sem


def test_get_wiki_generation_sem_returns_semaphore(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = asyncio.Semaphore(5)
    mock_semaphore = MagicMock(return_value=expected)
    monkeypatch.setattr("api.routes.wiki_shared.PipelineConcurrency.semaphore", mock_semaphore)

    request = SimpleNamespace(app=SimpleNamespace(state=State()))
    sem = get_wiki_generation_sem(request)  # type: ignore[arg-type]

    assert sem is expected
    mock_semaphore.assert_called_once_with("wiki_generation")


def test_get_wiki_generation_sem_caches_on_app_state(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_semaphore = MagicMock(return_value=asyncio.Semaphore(5))
    monkeypatch.setattr("api.routes.wiki_shared.PipelineConcurrency.semaphore", mock_semaphore)

    request = SimpleNamespace(app=SimpleNamespace(state=State()))
    first = get_wiki_generation_sem(request)  # type: ignore[arg-type]
    second = get_wiki_generation_sem(request)  # type: ignore[arg-type]

    assert first is second
    mock_semaphore.assert_called_once()
