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
        threshold = int(os.environ.get("WIKI__AGENT_SIMPLE_THRESHOLD", "3"))
        return cls(enabled=enabled, simple_threshold=threshold)

    def should_use_agent(self, module_count: int) -> bool:
        """Return True if Agent-Driven generation should be used."""
        return self.enabled and module_count >= self.simple_threshold
