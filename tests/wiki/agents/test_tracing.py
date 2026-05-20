"""Tests for agent span tracing (Layer 2b)."""
from __future__ import annotations
import time
import pytest
from unittest.mock import MagicMock


class TestSpan:
    def test_span_default_values(self):
        from wiki.agents.tracing import Span

        s = Span(name="test_op", kind="tool_call")
        assert s.name == "test_op"
        assert s.kind == "tool_call"
        assert s.span_id
        assert s.parent_id is None
        assert s.status == "running"
        assert s.end_time is None
        assert s.duration_ms is None

    def test_span_duration(self):
        from wiki.agents.tracing import Span

        s = Span(name="op")
        s.start_time = 100.0
        s.end_time = 100.150
        assert abs(s.duration_ms - 150.0) < 0.01


class TestAgentTracer:
    def test_start_span_creates_root(self):
        from wiki.agents.tracing import AgentTracer

        tracer = AgentTracer(group_id="g1")
        span = tracer.start_span("explore", kind="agent_run")
        assert span.parent_id is None
        assert span.name == "explore"
        assert tracer.group_id == "g1"

    def test_nested_spans(self):
        from wiki.agents.tracing import AgentTracer

        tracer = AgentTracer()
        root = tracer.start_span("explore", kind="agent_run")
        child = tracer.start_span("query_module_detail", kind="tool_call")
        assert child.parent_id == root.span_id

    def test_end_span_sets_time_and_status(self):
        from wiki.agents.tracing import AgentTracer

        tracer = AgentTracer()
        span = tracer.start_span("op")
        time.sleep(0.01)
        tracer.end_span(span, status="completed")
        assert span.end_time is not None
        assert span.status == "completed"
        assert span.duration_ms > 0

    def test_end_span_with_error(self):
        from wiki.agents.tracing import AgentTracer

        tracer = AgentTracer()
        span = tracer.start_span("op")
        tracer.end_span(span, status="error", error="something broke")
        assert span.status == "error"
        assert span.metadata["error"] == "something broke"

    def test_processor_called_on_end(self):
        from wiki.agents.tracing import AgentTracer, Span

        received: list[Span] = []

        class TestProcessor:
            def on_span_end(self, span: Span) -> None:
                received.append(span)

        tracer = AgentTracer(processors=[TestProcessor()])
        span = tracer.start_span("op")
        tracer.end_span(span)
        assert len(received) == 1
        assert received[0] is span

    def test_multiple_children_same_parent(self):
        from wiki.agents.tracing import AgentTracer

        tracer = AgentTracer()
        root = tracer.start_span("explore", kind="agent_run")
        c1 = tracer.start_span("tool1", kind="tool_call")
        tracer.end_span(c1)
        c2 = tracer.start_span("tool2", kind="tool_call")
        assert c2.parent_id == root.span_id
        tracer.end_span(c2)

    def test_group_id_auto_generated(self):
        from wiki.agents.tracing import AgentTracer

        tracer = AgentTracer()
        assert tracer.group_id
        assert len(tracer.group_id) >= 6


class TestRunConfigTracer:
    def test_run_config_accepts_tracer(self):
        from wiki.agents.base_agent import RunConfig
        from wiki.agents.tracing import AgentTracer

        tracer = AgentTracer(group_id="t1")
        config = RunConfig(tracer=tracer)
        assert config.tracer is tracer
        assert config.tracer.group_id == "t1"

    def test_run_config_tracer_default_none(self):
        from wiki.agents.base_agent import RunConfig

        config = RunConfig()
        assert config.tracer is None
