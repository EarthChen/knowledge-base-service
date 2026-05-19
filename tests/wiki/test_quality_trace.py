"""Tests for quality trace collection."""

from datetime import datetime, timezone

import pytest

from wiki.quality_trace import AgentTrace, TraceCollector, ToolCallRecord


class TestAgentTrace:
    def test_create_trace(self):
        trace = AgentTrace(
            domain="auth",
            page_title="Auth Service",
            timestamp=datetime.now(timezone.utc),
            explore_rounds=4,
            tools_called=[
                ToolCallRecord(name="read_code", args_summary="entity=AuthService", duration_ms=120),
            ],
            quality_score=0.85,
            modules_expected=["AuthService", "TokenManager"],
            modules_covered=["AuthService"],
            generation_time_ms=5000,
        )
        assert trace.domain == "auth"
        assert trace.coverage == 0.5
        assert len(trace.tools_called) == 1

    def test_coverage_calculation(self):
        trace = AgentTrace(
            domain="orders",
            page_title="Orders",
            timestamp=datetime.now(timezone.utc),
            explore_rounds=3,
            tools_called=[],
            quality_score=0.9,
            modules_expected=["A", "B", "C", "D"],
            modules_covered=["A", "B", "C"],
            generation_time_ms=3000,
        )
        assert trace.coverage == 0.75

    def test_coverage_empty_expected(self):
        trace = AgentTrace(
            domain="misc",
            page_title="Misc",
            timestamp=datetime.now(timezone.utc),
            explore_rounds=1,
            tools_called=[],
            quality_score=1.0,
            modules_expected=[],
            modules_covered=[],
            generation_time_ms=1000,
        )
        assert trace.coverage == 1.0


class TestTraceCollector:
    @pytest.fixture
    def collector(self, tmp_path):
        return TraceCollector(trace_dir=str(tmp_path))

    @pytest.mark.asyncio
    async def test_record_creates_file(self, collector, tmp_path):
        trace = AgentTrace(
            domain="test",
            page_title="Test Page",
            timestamp=datetime.now(timezone.utc),
            explore_rounds=2,
            tools_called=[],
            quality_score=0.8,
            modules_expected=["A"],
            modules_covered=["A"],
            generation_time_ms=2000,
        )
        await collector.record(trace)
        files = list(tmp_path.glob("*.jsonl"))
        assert len(files) == 1

    @pytest.mark.asyncio
    async def test_record_multiple_appends(self, collector, tmp_path):
        for i in range(3):
            trace = AgentTrace(
                domain=f"domain_{i}",
                page_title=f"Page {i}",
                timestamp=datetime.now(timezone.utc),
                explore_rounds=i + 1,
                tools_called=[],
                quality_score=0.5 + i * 0.1,
                modules_expected=[],
                modules_covered=[],
                generation_time_ms=1000,
            )
            await collector.record(trace)
        files = list(tmp_path.glob("*.jsonl"))
        assert len(files) == 1
        lines = files[0].read_text().strip().split("\n")
        assert len(lines) == 3
