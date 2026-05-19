"""Quality trace collection for agent improvement loop.

Records structured traces of each page generation for analysis and
strategy optimization. Phase 1: file-based persistence (JSONL).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)


@dataclass
class ToolCallRecord:
    name: str
    args_summary: str = ""
    duration_ms: int = 0


@dataclass
class AgentTrace:
    domain: str
    page_title: str
    timestamp: datetime
    explore_rounds: int
    tools_called: list[ToolCallRecord]
    quality_score: float
    modules_expected: list[str]
    modules_covered: list[str]
    generation_time_ms: int

    @property
    def coverage(self) -> float:
        if not self.modules_expected:
            return 1.0
        return len(self.modules_covered) / len(self.modules_expected)


class TraceCollector:
    """Persist traces to JSONL file for later analysis."""

    def __init__(self, trace_dir: str = "data/traces") -> None:
        self._trace_dir = Path(trace_dir)
        self._trace_dir.mkdir(parents=True, exist_ok=True)
        self._file = self._trace_dir / "agent_traces.jsonl"

    async def record(self, trace: AgentTrace) -> None:
        try:
            record = asdict(trace)
            record["timestamp"] = trace.timestamp.isoformat()
            record["coverage"] = trace.coverage
            with self._file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except Exception:
            log.warning("trace_record_failed", domain=trace.domain, exc_info=True)
