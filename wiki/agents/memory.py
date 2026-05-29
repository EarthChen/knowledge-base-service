from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


class AgentMemory(ABC):
    """Framework-level agent memory interface."""

    @abstractmethod
    def incorporate(self, tool_name: str, result: dict) -> None: ...

    @abstractmethod
    def to_prompt(self, max_chars: int | None = None) -> str: ...

    @abstractmethod
    def merge(self, other: AgentMemory) -> None: ...

    @abstractmethod
    def slice(self, keys: set[str]) -> AgentMemory: ...

    @abstractmethod
    def inject_findings(self, findings: list[str]) -> None: ...


@runtime_checkable
class MemoryBackend(Protocol):
    async def store(self, question: str, answer: str, **kwargs: Any) -> str: ...

    async def retrieve(self, topic: str, limit: int = 5) -> list: ...

    async def record_access(self, uid: str) -> None: ...


@dataclass
class Memory:
    """Generic key-value memory with size limits.

    Subclasses (e.g. CodeMemory) add domain-specific fields and
    override enforce_limit() for smarter eviction.
    """

    entries: dict[str, list[str]] = field(default_factory=dict)
    max_total_chars: int = 200_000

    def add(self, category: str, value: str) -> None:
        self.entries.setdefault(category, []).append(value)

    def total_chars(self) -> int:
        return sum(
            len(v) for values in self.entries.values() for v in values
        )

    def enforce_limit(self) -> None:
        while self.total_chars() > self.max_total_chars and self.entries:
            for key in list(self.entries):
                if self.entries[key]:
                    self.entries[key].pop(0)
                    break
            else:
                break

    def merge(self, other: Memory) -> None:
        for key, values in other.entries.items():
            self.entries.setdefault(key, []).extend(values)
        self.enforce_limit()
