from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from api import kb_state
from api.routes.settings_routes import HOT_RELOAD_KEYS
from core.config import LLMConfig
from core.container import AppContainer
from llm.provider import LLMProvider
from services.settings_service import SettingsService
from store.settings_store import SettingsStore


def test_llm_keys_hot_reload() -> None:
    assert "llm.providers" in HOT_RELOAD_KEYS
    assert "llm.strategy.classification" in HOT_RELOAD_KEYS
    assert "llm.strategy.generation" in HOT_RELOAD_KEYS
    assert "llm.strategy.rag_plan" in HOT_RELOAD_KEYS
    assert "llm.strategy.rag_generate" in HOT_RELOAD_KEYS


def test_wiki_auto_update_still_hot() -> None:
    assert "wiki.auto_update_on_index" in HOT_RELOAD_KEYS


def test_pipeline_concurrency_keys_hot_reload() -> None:
    """All pipeline concurrency settings should be hot-reloadable."""
    concurrency_keys = [
        "wiki.compose_concurrency",
        "wiki.domain_agent_concurrency",
        "wiki.wiki_generation_concurrency",
        "wiki.heal_concurrency",
        "wiki.bottomup_concurrency",
        "wiki.module_compose_concurrency",
        "wiki.domain_naming_concurrency",
        "wiki.flow_compose_concurrency",
    ]
    for key in concurrency_keys:
        assert key in HOT_RELOAD_KEYS, f"{key} should be hot-reloadable"


def test_llm_rate_limit_keys_hot_reload() -> None:
    assert "wiki.llm_global_rpm_limit" in HOT_RELOAD_KEYS
    assert "wiki.llm_global_tpm_limit" in HOT_RELOAD_KEYS


def test_domain_agent_tuning_keys_hot_reload() -> None:
    assert "wiki.domain_agent_max_iterations_core" in HOT_RELOAD_KEYS
    assert "wiki.domain_agent_max_iterations_standard" in HOT_RELOAD_KEYS
    assert "wiki.domain_agent_max_iterations_skeleton" in HOT_RELOAD_KEYS


def test_heal_tuning_keys_hot_reload() -> None:
    assert "wiki.heal_max_rounds_core" in HOT_RELOAD_KEYS
    assert "wiki.heal_max_rounds_standard" in HOT_RELOAD_KEYS
    assert "wiki.heal_loop_max_total_attempts" in HOT_RELOAD_KEYS


def test_quality_keys_hot_reload() -> None:
    assert "wiki.quality_min_score" in HOT_RELOAD_KEYS
    assert "wiki.quality_sample_size" in HOT_RELOAD_KEYS


def test_domain_split_keys_hot_reload() -> None:
    assert "wiki.domain_split_threshold" in HOT_RELOAD_KEYS
    assert "wiki.domain_split_max_depth" in HOT_RELOAD_KEYS


def test_llm_max_concurrent_in_hot_reload_keys() -> None:
    assert "llm.max_concurrent" in HOT_RELOAD_KEYS


@pytest.mark.asyncio
async def test_llm_max_concurrent_hot_reload_updates_semaphore(tmp_path) -> None:
    """Updating llm.max_concurrent via settings should refresh the live LLM semaphore."""
    provider = LLMProvider(LLMConfig(max_concurrent=10, enabled=True, api_key="test-key"))
    assert provider.max_concurrent == 10
    assert provider._semaphore._value == 10  # type: ignore[attr-defined]

    kb_svc = MagicMock()
    kb_svc.llm_provider = provider
    registry = MagicMock()
    registry._services = {"default": kb_svc}

    previous_container = kb_state._container
    kb_state._container = AppContainer.create_test(registry=registry)
    try:
        service = SettingsService(SettingsStore(db_path=str(tmp_path / "settings.db")))
        await service.update_settings(
            [{"key": "llm.max_concurrent", "value": "25", "category": "llm"}],
        )
    finally:
        kb_state._container = previous_container

    assert provider.max_concurrent == 25
    assert provider._semaphore._value == 25  # type: ignore[attr-defined]
