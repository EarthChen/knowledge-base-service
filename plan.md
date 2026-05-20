# Plan

## In Progress

Next: Layer 3 (Handoff formalization)

## Completed

1. ~~Embedding HTTP 抽象层~~ → `indexer/embedding_generator.py` (_HttpBackend)
2. ~~Agent framework 调研~~ → `docs/superpowers/specs/2026-05-19-agent-framework-research.md`
3. ~~Agent Quality Patterns 实现~~ → 6 patterns committed (Tool Guardrails, Smart Early Stop, Context Trimming, Structured Output, Output Guardrail, Quality Trace)
4. ~~Layer 0: RunContext DI~~ → `wiki/agents/context.py`, dispatch ctx threading, WikiPageAgent._deps (5 commits)
5. ~~Layer 1a: Guardrails~~ → `wiki/agents/guardrails.py`, RunConfig input/output guardrails, tripwire semantics
6. ~~Layer 1b: output_type~~ → `GenericAgent.output_type` + `_render_output()` + complete_json fallback
7. ~~Layer 2a: @function_tool~~ → `wiki/agents/tool_decorator.py`, auto-schema from type hints, ctx injection, collect_tools()
8. ~~Layer 2b: Span Tracing~~ → `wiki/agents/tracing.py`, AgentTracer wired into run_tool_loop (agent_run + tool_call spans)
