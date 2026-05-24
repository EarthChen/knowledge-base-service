"""Centralized pipeline concurrency management.

Provides stage-specific semaphores from unified config.
Priority: env var WIKI_{STAGE}_CONCURRENCY > legacy env var > config field > default.
"""
from __future__ import annotations

import asyncio
import os
from typing import ClassVar

from core.config import get_settings


class PipelineConcurrency:
    """Provides stage-specific semaphores from unified config."""

    _LEGACY_ENV_ALIASES: ClassVar[dict[str, str]] = {
        "domain_agent": "DOMAIN_AGENT_CONCURRENCY",
    }

    @classmethod
    def _parse_env_int(cls, value: str) -> int | None:
        """Parse env var value to int, returning None if invalid or < 1."""
        try:
            n = int(value)
            return n if n >= 1 else None
        except (ValueError, TypeError):
            return None

    @classmethod
    def _resolve_limit(cls, stage: str) -> int:
        env_key = f"WIKI_{stage.upper()}_CONCURRENCY"
        env_val = os.environ.get(env_key)
        if env_val is not None:
            parsed = cls._parse_env_int(env_val)
            if parsed is not None:
                return parsed

        legacy_key = cls._LEGACY_ENV_ALIASES.get(stage)
        if legacy_key:
            legacy_val = os.environ.get(legacy_key)
            if legacy_val is not None:
                parsed = cls._parse_env_int(legacy_val)
                if parsed is not None:
                    return parsed

        cfg = get_settings().wiki
        mapping = {
            "domain_agent": cfg.domain_agent_concurrency,
            "heal": cfg.heal_concurrency,
            "compose": cfg.compose_concurrency,
            "bottomup": cfg.bottomup_concurrency,
            "title_gen": cfg.bottomup_concurrency,
            "module_compose": cfg.module_compose_concurrency,
            "domain_naming": cfg.domain_naming_concurrency,
            "flow_compose": cfg.flow_compose_concurrency,
        }
        return mapping.get(stage, cfg.compose_concurrency)

    @classmethod
    def semaphore(cls, stage: str) -> asyncio.Semaphore:
        """Create a Semaphore with the resolved concurrency limit for the given stage."""
        return asyncio.Semaphore(cls._resolve_limit(stage))

    @classmethod
    def limit(cls, stage: str) -> int:
        """Return concurrency limit as int (for logging/metrics)."""
        return cls._resolve_limit(stage)
