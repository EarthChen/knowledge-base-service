"""Tests for api.kb_state shim binding to AppContainer."""

from __future__ import annotations

import asyncio

import api.kb_state as kb_state
from core.config import get_settings
from core.container import AppContainer


def test_bind_unifies_semaphores_with_container() -> None:
    container = AppContainer(
        settings=get_settings(),
        reindex_sem=asyncio.Semaphore(1),
        index_sem=asyncio.Semaphore(2),
    )
    assert kb_state.reindex_sem is not container.reindex_sem
    kb_state._bind(container)
    assert kb_state.reindex_sem is container.reindex_sem
    assert kb_state.index_sem is container.index_sem
