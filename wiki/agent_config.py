"""Configuration for Agent-Driven wiki generation."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_env_fallback() -> dict[str, str]:
    """Parse .env file as fallback when vars are not in os.environ."""
    env_path = Path.cwd() / ".env"
    if not env_path.is_file():
        return {}
    result: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        result[key.strip()] = val.strip().strip("'\"")
    return result


def _get_env(key: str, default: str = "") -> str:
    """Read from os.environ first, then fallback to .env file."""
    val = os.environ.get(key)
    if val is not None:
        return val
    if not hasattr(_get_env, "_dotenv_cache"):
        _get_env._dotenv_cache = _load_env_fallback()  # type: ignore[attr-defined]
    return _get_env._dotenv_cache.get(key, default)  # type: ignore[attr-defined]


@dataclass
class AgentConfig:
    """Controls when to use Agent-Driven generation vs template-based."""
    enabled: bool = False
    simple_threshold: int = 1

    @classmethod
    def from_env(cls) -> AgentConfig:
        enabled = _get_env("WIKI__AGENT_DRIVEN_GENERATION", "false").lower() in ("true", "1", "yes")
        try:
            threshold = int(_get_env("WIKI__AGENT_SIMPLE_THRESHOLD", "1"))
        except ValueError:
            threshold = 1
        return cls(enabled=enabled, simple_threshold=threshold)

    def should_use_agent(self, module_count: int) -> bool:
        """Return True if Agent-Driven generation should be used."""
        return self.enabled and module_count >= self.simple_threshold


@dataclass
class HarnessConfig:
    enabled: bool = False
    max_repair_rounds: int = 2
    simple_threshold: int = 5
    complex_threshold: int = 15
    llm_judge_enabled: bool = True

    @classmethod
    def from_env(cls) -> "HarnessConfig":
        return cls(
            enabled=_get_env("WIKI__USE_HARNESS", "").lower() in ("true", "1", "yes"),
            max_repair_rounds=int(_get_env("WIKI__HARNESS_MAX_REPAIR_ROUNDS", "2")),
            simple_threshold=int(_get_env("WIKI__HARNESS_SIMPLE_THRESHOLD", "5")),
            complex_threshold=int(_get_env("WIKI__HARNESS_COMPLEX_THRESHOLD", "15")),
            llm_judge_enabled=_get_env("WIKI__HARNESS_LLM_JUDGE", "true").lower() in ("true", "1"),
        )
