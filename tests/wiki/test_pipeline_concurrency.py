"""Tests for PipelineConcurrency utility."""
from __future__ import annotations

import asyncio
import os
from unittest.mock import patch


class TestPipelineConcurrencyLimit:
    def test_known_stage_returns_config_value(self):
        from wiki.pipeline_concurrency import PipelineConcurrency
        limit = PipelineConcurrency.limit("heal")
        assert limit == 8

    def test_unknown_stage_returns_compose_default(self):
        from wiki.pipeline_concurrency import PipelineConcurrency
        limit = PipelineConcurrency.limit("nonexistent_stage")
        assert limit == 16

    def test_env_var_override_takes_priority(self):
        from wiki.pipeline_concurrency import PipelineConcurrency
        with patch.dict(os.environ, {"WIKI_HEAL_CONCURRENCY": "10"}):
            limit = PipelineConcurrency.limit("heal")
            assert limit == 10

    def test_legacy_env_var_alias(self):
        from wiki.pipeline_concurrency import PipelineConcurrency
        with patch.dict(os.environ, {"DOMAIN_AGENT_CONCURRENCY": "7"}):
            limit = PipelineConcurrency.limit("domain_agent")
            assert limit == 7

    def test_new_env_var_beats_legacy(self):
        from wiki.pipeline_concurrency import PipelineConcurrency
        with patch.dict(os.environ, {
            "WIKI_DOMAIN_AGENT_CONCURRENCY": "8",
            "DOMAIN_AGENT_CONCURRENCY": "7",
        }):
            limit = PipelineConcurrency.limit("domain_agent")
            assert limit == 8


class TestPipelineConcurrencySemaphore:
    def setup_method(self) -> None:
        from wiki.pipeline_concurrency import PipelineConcurrency

        PipelineConcurrency.reset()

    def teardown_method(self) -> None:
        from wiki.pipeline_concurrency import PipelineConcurrency

        PipelineConcurrency.reset()

    def test_returns_semaphore_with_correct_limit(self):
        from wiki.pipeline_concurrency import PipelineConcurrency
        sem = PipelineConcurrency.semaphore("heal")
        assert isinstance(sem, asyncio.Semaphore)
        assert sem._value == 8

    def test_domain_agent_default(self):
        from wiki.pipeline_concurrency import PipelineConcurrency
        sem = PipelineConcurrency.semaphore("domain_agent")
        assert sem._value == 6

    def test_semaphore_returns_same_instance(self):
        from wiki.pipeline_concurrency import PipelineConcurrency

        sem1 = PipelineConcurrency.semaphore("compose")
        sem2 = PipelineConcurrency.semaphore("compose")
        assert sem1 is sem2

    def test_semaphore_different_stages_different_instances(self):
        from wiki.pipeline_concurrency import PipelineConcurrency

        sem_compose = PipelineConcurrency.semaphore("compose")
        sem_heal = PipelineConcurrency.semaphore("heal")
        assert sem_compose is not sem_heal

    def test_reset_clears_cache(self):
        from wiki.pipeline_concurrency import PipelineConcurrency

        sem_before = PipelineConcurrency.semaphore("compose")
        PipelineConcurrency.reset()
        sem_after = PipelineConcurrency.semaphore("compose")
        assert sem_before is not sem_after


class TestPipelineConcurrencyRefresh:
    """Tests for PipelineConcurrency.refresh() — hot-reload support."""

    def setup_method(self) -> None:
        from wiki.pipeline_concurrency import PipelineConcurrency
        PipelineConcurrency.reset()

    def teardown_method(self) -> None:
        from wiki.pipeline_concurrency import PipelineConcurrency
        PipelineConcurrency.reset()

    def test_refresh_clears_cached_semaphores(self):
        from wiki.pipeline_concurrency import PipelineConcurrency
        sem_before = PipelineConcurrency.semaphore("heal")
        PipelineConcurrency.refresh()
        sem_after = PipelineConcurrency.semaphore("heal")
        assert sem_before is not sem_after

    def test_refresh_picks_up_new_config_values(self):
        from wiki.pipeline_concurrency import PipelineConcurrency
        # Initially heal_concurrency=8
        sem_before = PipelineConcurrency.semaphore("heal")
        assert sem_before._value == 8
        # Simulate config change via env var
        with patch.dict(os.environ, {"WIKI_HEAL_CONCURRENCY": "15"}):
            PipelineConcurrency.refresh()
            sem_after = PipelineConcurrency.semaphore("heal")
            assert sem_after._value == 15

    def test_refresh_with_overrides(self):
        from wiki.pipeline_concurrency import PipelineConcurrency
        PipelineConcurrency.refresh(overrides={"heal": 20, "compose": 30})
        assert PipelineConcurrency.limit("heal") == 20
        assert PipelineConcurrency.limit("compose") == 30

    def test_refresh_overrides_take_priority_over_env(self):
        from wiki.pipeline_concurrency import PipelineConcurrency
        with patch.dict(os.environ, {"WIKI_HEAL_CONCURRENCY": "10"}):
            PipelineConcurrency.refresh(overrides={"heal": 25})
            assert PipelineConcurrency.limit("heal") == 25

    def test_refresh_without_overrides_uses_config(self):
        from wiki.pipeline_concurrency import PipelineConcurrency
        PipelineConcurrency.refresh()
        # Should still resolve from config defaults
        assert PipelineConcurrency.limit("heal") == 8
