"""Span-based tracing for agent tool loops.

Provides hierarchical span tracking for agent runs, tool calls,
and generation steps. Processors receive completed spans for
logging, metrics, or export.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class Span:
    """A single timing span in the agent execution tree."""

    name: str = ""
    kind: str = "generic"  # agent_run | generation | tool_call | guardrail | handoff
    span_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    parent_id: str | None = None
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    status: str = "running"  # running | completed | error

    @property
    def duration_ms(self) -> float | None:
        if self.end_time is None:
            return None
        return (self.end_time - self.start_time) * 1000


class TraceProcessor(Protocol):
    """Pluggable backend for processing completed spans."""

    def on_span_end(self, span: Span) -> None: ...


class AgentTracer:
    """Hierarchical span tree manager."""

    def __init__(
        self,
        group_id: str | None = None,
        processors: list[TraceProcessor] | None = None,
    ) -> None:
        self._group_id = group_id or uuid.uuid4().hex[:8]
        self._processors = processors or []
        self._span_stack: list[Span] = []

    @property
    def group_id(self) -> str:
        return self._group_id

    def start_span(self, name: str, kind: str = "generic", **meta: Any) -> Span:
        parent_id = self._span_stack[-1].span_id if self._span_stack else None
        span = Span(
            name=name,
            kind=kind,
            parent_id=parent_id,
            metadata={"group_id": self._group_id, **meta},
        )
        self._span_stack.append(span)
        return span

    def end_span(
        self, span: Span, *, status: str = "completed", error: str | None = None
    ) -> None:
        span.end_time = time.time()
        span.status = status
        if error:
            span.metadata["error"] = error
        for proc in self._processors:
            proc.on_span_end(span)
        # Pop from stack (find and remove)
        if span in self._span_stack:
            idx = self._span_stack.index(span)
            self._span_stack = self._span_stack[:idx]


class JsonlTraceProcessor:
    """Writes completed spans as JSONL to a file for offline analysis."""

    def __init__(self, output_path: str = "data/traces/agent_traces.jsonl") -> None:
        self._output_path = output_path

    def on_span_end(self, span: Span) -> None:
        import json
        from pathlib import Path

        path = Path(self._output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        record = {
            "span_id": span.span_id,
            "parent_id": span.parent_id,
            "name": span.name,
            "kind": span.kind,
            "status": span.status,
            "start_time": span.start_time,
            "end_time": span.end_time,
            "duration_ms": span.duration_ms,
            "metadata": span.metadata,
        }

        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
