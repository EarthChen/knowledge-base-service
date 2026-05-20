# Plan

## In Progress

Next: Layer 1b (output_type structured output) → Layer 2a (@function_tool) → Layer 2b (Tracing) → Layer 3 (Handoff)

## Completed

1. ~~Embedding HTTP 抽象层~~ → `indexer/embedding_generator.py` (_HttpBackend)
2. ~~Agent framework 调研~~ → `docs/superpowers/specs/2026-05-19-agent-framework-research.md`
3. ~~Agent Quality Patterns 实现~~ → 6 patterns committed (Tool Guardrails, Smart Early Stop, Context Trimming, Structured Output, Output Guardrail, Quality Trace)
4. ~~Layer 0: RunContext DI~~ → `wiki/agents/context.py`, dispatch ctx threading, WikiPageAgent._deps (5 commits)
5. ~~Layer 1a: Guardrails~~ → `wiki/agents/guardrails.py`, RunConfig input/output guardrails, tripwire semantics
