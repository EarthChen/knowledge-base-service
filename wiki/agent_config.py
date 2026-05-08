"""Configuration for Agent-Driven wiki generation."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class AgentConfig:
    """Controls when to use Agent-Driven generation vs template-based."""
    enabled: bool = False
    simple_threshold: int = 3

    @classmethod
    def from_env(cls) -> AgentConfig:
        enabled = os.environ.get("WIKI__AGENT_DRIVEN_GENERATION", "false").lower() in ("true", "1", "yes")
        try:
            threshold = int(os.environ.get("WIKI__AGENT_SIMPLE_THRESHOLD", "3"))
        except ValueError:
            threshold = 3
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
            enabled=os.getenv("WIKI__USE_HARNESS", "").lower() in ("true", "1", "yes"),
            max_repair_rounds=int(os.getenv("WIKI__HARNESS_MAX_REPAIR_ROUNDS", "2")),
            simple_threshold=int(os.getenv("WIKI__HARNESS_SIMPLE_THRESHOLD", "5")),
            complex_threshold=int(os.getenv("WIKI__HARNESS_COMPLEX_THRESHOLD", "15")),
            llm_judge_enabled=os.getenv("WIKI__HARNESS_LLM_JUDGE", "true").lower() in ("true", "1"),
        )
