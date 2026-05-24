"""Tests for PipelineConcurrency utility."""
from __future__ import annotations

import asyncio
import os
from unittest.mock import patch


class TestPipelineConcurrencyLimit:
    def test_known_stage_returns_config_value(self):
        from wiki.pipeline_concurrency import PipelineConcurrency
        limit = PipelineConcurrency.limit("heal")
        assert limit == 5

    def test_unknown_stage_returns_compose_default(self):
        from wiki.pipeline_concurrency import PipelineConcurrency
        limit = PipelineConcurrency.limit("nonexistent_stage")
        assert limit == 12

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
        assert sem._value == 5

    def test_domain_agent_default(self):
        from wiki.pipeline_concurrency import PipelineConcurrency
        sem = PipelineConcurrency.semaphore("domain_agent")
        assert sem._value == 3

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
