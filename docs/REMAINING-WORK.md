# Remaining Work (Unified Backlog)

**Created:** 2026-05-09  
**Source:** Sprint 2 post-audit + DEEP_ANALYSIS B-items + code review findings  
**Status:** Active — items checked off when merged

---

## P1 — Robustness & Code Quality

These are addressable within the current codebase without new features.

- [ ] **`grep_code` timeout / scan budget** — `WikiPageAgent._tool_grep_code` has no execution timeout or scan-size cap; a pathological regex on a large repo could block the agent loop. Add `asyncio.wait_for` + file-count limit.
- [ ] **`HarnessConfig.from_env` error handling** — Environment parse failures silently fall back to defaults; should log a warning with the offending key/value.
- [ ] **`WorkingMemory` FIFO eviction** — `_entries.pop(0)` is O(n) on a list; replace with `collections.deque` for amortised O(1).
- [ ] **C/C++, C#, Rust language plugins** (DEEP_ANALYSIS B-18 remainder) — 9 languages covered, 4 major ones still missing.

## P2 — Product Feature Gaps (from DEEP_ANALYSIS)

Larger feature work, each requires a standalone proposal.

- [ ] **B-19: Generic document ingest** — Support PDF, Office (docx/xlsx), HTML as indexable knowledge sources beyond code.
- [ ] **B-20: Multi-modal analysis** — Support images, design files, and non-text content in the knowledge graph.
- [ ] **B-21: Automated quality benchmark** — End-to-end benchmark infrastructure (Wiki accuracy, retrieval precision, generation quality) for regression tracking.
- [ ] **B-22: Docker Compose one-click deploy** — Lower deployment barrier vs DeepWiki et al; compose file + env template + health probes.

## P3 — Anti-Hallucination Layers 2 & 3

Currently only Layer 1 (citation verification + penalty in `quality_gate_node`) is implemented.

- [ ] **Layer 2: Mechanical Citation Injection** — Auto-inject `source://` references verified against the graph database into generated pages.
- [ ] **Layer 3: Post-Generation Fact Check** — Extract technical entities from generated content and verify their existence/accuracy against the graph.

---

*Items here are non-blocking for the current sprint. Prioritise based on user impact and deployment timeline.*
