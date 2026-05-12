# Remaining Work (Unified Backlog)

**Created:** 2026-05-09  
**Last Updated:** 2026-05-12  
**Status:** Active — items checked off when merged

---

## 当前活跃提案

所有待办工作已统一至唯一活跃提案：

> [`specs/2026-05-12-agent-wiki-quality-and-tree-fix.md`](superpowers/specs/2026-05-12-agent-wiki-quality-and-tree-fix.md)

| Task | 优先级 | 状态 |
|------|--------|------|
| A-D: 路径/质量门/内容/Robustness | P0-P2 | ✅ 已完成 |
| F: Explore/Write 分离 | 核心 ✅ / 优化 P3 | 核心已完成，剩工具动态解锁+PageRank |
| G: 域分类准确度提升 | P1 | Proposed（丰富模块描述+prompt、调用矩阵、共享服务） |
| H: 域调整机制 (Dashboard) | P1 | Proposed（domain_pinned + 域管理 API + UI） |
| E: L2 业务流文档 | P3 | 待 L1 稳定后启动 |

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
- [x] Explore/Write 分离 ✅ (2026-05-12) — 固化至 `page_agent.py` + `domain_doc_agent.py`
- [x] Domain Agent 弹性超时 + Wiki⟷Code 深度关联 ✅ (2026-05-12) — 固化至 `domain_doc_agent.py` + `page_agent.py`
- [x] Code Linking 合并 Bug (`_attach_domain_sources`) ✅ (2026-05-12) — 固化至 `nodes/domain_compose.py`

---

*Items here are non-blocking for the current sprint. Prioritise based on user impact and deployment timeline.*
