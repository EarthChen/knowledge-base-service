# Remaining Work (Unified Backlog)

**Created:** 2026-05-09  
**Last Updated:** 2026-05-12  
**Status:** Active — items checked off when merged

---

## 当前活跃提案

所有 Agent Wiki 相关的待办工作（质量修复、前端树适配、已知问题、L2/L3 业务流、Prompt 优化等）已统一至：

> [`specs/2026-05-12-agent-wiki-quality-and-tree-fix.md`](superpowers/specs/2026-05-12-agent-wiki-quality-and-tree-fix.md) — 9 个 Task，涵盖全部待办

---

## 独立积压项（不属于统一提案范围）

### P1 — 前端代码质量

- [ ] **F-04: API 响应无运行时校验** (P3) — `api/client.ts` 的 `api<T>()` 将 JSON 直接 cast 为 `T`，运行时数据形态完全信任服务端。

### P1 — 语言插件扩展

- [ ] **C/C++, C#, Rust language plugins** (DEEP_ANALYSIS B-18 remainder) — 9 languages covered, 4 major ones still missing.

### P2 — Product Feature Gaps (from DEEP_ANALYSIS)

Larger feature work, each requires a standalone proposal.

- [ ] **B-19: Generic document ingest** — Support PDF, Office (docx/xlsx), HTML as indexable knowledge sources beyond code.
- [ ] **B-20: Multi-modal analysis** — Support images, design files, and non-text content in the knowledge graph.
- [ ] **B-21: Automated quality benchmark** — End-to-end benchmark infrastructure (Wiki accuracy, retrieval precision, generation quality) for regression tracking.
- [ ] **B-22: Docker Compose one-click deploy** — Lower deployment barrier vs DeepWiki et al; compose file + env template + health probes.

---

## 已完成归档

以下工作已全部完成，保留作为审计记录：

- [x] Agent-Driven Business Wiki Phase 0-4 ✅
- [x] Incremental Wiki Update ✅
- [x] Wiki pipeline hardening (2026-05-11) ✅
- [x] Issue #008 Agent 管线质量修复 ✅ (2026-05-12)
- [x] Wiki LLM P0 fix (`_enrich_leaf_context`) — 已通过新 Agent 管线绕过

---

*Items here are non-blocking for the current sprint. Prioritise based on user impact and deployment timeline.*
