# Remaining Work (Unified Backlog)

**Created:** 2026-05-09  
**Source:** Sprint 2 post-audit + DEEP_ANALYSIS B-items + code review findings + Wiki LLM efficiency review (2026-05-11)  
**Status:** Active — items checked off when merged

---

## Agent-Driven Business Wiki (核心迭代)

> 参见统一提案 [`specs/2026-05-11-agent-driven-business-wiki-design.md`](superpowers/specs/2026-05-11-agent-driven-business-wiki-design.md)  
> 参见执行计划 [`plans/2026-05-11-agent-driven-wiki-implementation.md`](superpowers/plans/2026-05-11-agent-driven-wiki-implementation.md)

**Phase 0 — 图数据质量修复** ✅ 代码已完成
- [x] Module UID 加 file 属性（消除同名冲突）
- [x] 停止删除 IMPORTS 边（恢复模块依赖关系）
- [x] WCC-first 图分解 + INHERITS/IMPLEMENTS 依赖查询
- [ ] 部署 + 清空图 + 重新索引

**Phase 0.5 — Prompt 体系 + QualityReport** ✅ 已完成
- [x] `wiki/quality_report.py`: `evaluate_quality()` + `QualityReport` 程序化质量评估
- [x] `wiki/agent_prompts.py`: 完整 prompt 体系（CORE_CONSTRAINTS + TOOL_USAGE_GUIDE + Explore/Write/Generate）
- [x] `tests/wiki/test_quality_report.py`: 9 个单元测试

**Phase 1 — 管线域分类接入 + WikiPageAgent 重构** ✅ 已完成
- [x] 将 `classify_domains_node` 接入 `pipeline_graph.py`
- [x] 将 `decompose_hierarchy_node` 接入 `pipeline_graph.py`
- [x] WikiPageAgent `__init__` 接受 `max_rounds` / `max_tool_calls` 构造参数
- [x] `enrich()` 扩展 `focus_modules` / `quality_report` / `domain_name` 可选参数
- [ ] 验证 Dashboard 出现域导航树（需部署验证）

**Phase 2 — Agent 驱动的域级文档生成** ✅ 已完成
- [x] 创建 `wiki/domain_doc_agent.py`: `DomainDocAgent`（质量驱动迭代 + `_build_baseline` + `_maybe_split`）
- [x] 创建 `wiki/nodes/domain_compose.py`: `compose_domain_agents_node`（并发 + 故障隔离 + 超时）
- [x] 修改 `compose_leaf_modules_node` 仅产出 `module_summaries`（`USE_AGENT_COMPOSE=true` 时）
- [x] 管线注册 `compose_domain_agents_node`（A/B 切换）

**Phase 3 — 管线切换 + 可观测性** ✅ 已完成
- [x] `USE_AGENT_COMPOSE` 环境变量切换新旧管线
- [x] `compose_bottomup` 标记废弃（代码保留 + deprecation warning）
- [x] Agent 日志增强（每轮 iteration_history、QualityReport、elapsed_time）
- [x] 域级进度追踪（`domain_agent_done` / `domain_agent_failed` 结构化日志）
- [x] 错误占位页面（`_make_error_placeholder` 含 `_error` 字段）
- [x] ~~Fix Issue #006: `_enrich_leaf_context` UID→name 映射~~ — 已修复，Phase 2 后随 compose_bottomup 废弃

**Phase 4 — 前端适配 + 增量更新** (1-2 天)
- [ ] `WikiTopicContent` domain_overview 完整宽度布局
- [ ] Mermaid 渲染增强（sequenceDiagram + classDiagram + 大图自动缩放）
- [ ] 树状导航适配新域级结构
- [ ] 增量 wiki 更新设计（git diff → 受影响域 → Agent 重新生成）

---

## Wiki LLM call optimization (cost & quality)

Ordered by **ROI** (see [`KNOWN-ISSUES.md`](KNOWN-ISSUES.md) Issue #006 / #007 for root causes).

- [ ] **P0 — Fix `_enrich_leaf_context` UID vs name alignment** — `wiki/nodes/graph_nodes.py`: pass graph keys that match the Cypher predicate (`m.name` vs `entity_uids`); restores context for Phase2 LLM calls.
- [ ] **P1 — Template-first leaf generation for `data_model` / DTO-style modules** — Skip Phase2 LLM for simple structural modules; reuse Phase1 role signals consistently.
- [ ] **P2 — Fix Phase1 `framework_noise` early veto in `_generate_single_module_summary`** — Same logical module in multiple repos: visiting the `framework_noise` copy first must not block summaries for the “real” module (improves Phase1 coverage and Phase2 reuse).
- [ ] **P3 — Batch LLM calls per WCC / cluster** — Group related modules in one prompt where safe to cut round-trips (medium–high effort).
- [ ] **P4 — Iterative refinement (skeleton → detail)** — Quality-focused; may not reduce total tokens.

---

## Completed — Wiki pipeline hardening (2026-05-11)

These fixes landed in-repo around this date; keep for audit trail.

- [x] **Module summaries key consistency** — `compose_leaf_modules_node` stored summaries by **name** while `compose_bottomup_node` read by **UID**; **fixed** by making `module_summaries` include **both** UID and name keys.
- [x] **Parent node concurrency in `compose_bottomup_node`** — Parents moved from strictly sequential execution to **batched concurrency** (`asyncio.gather` + `Semaphore`).
- [x] **Dashboard page visibility** — `link_pages_to_tree` now resolves Wiki pages via **`business_id`** when applicable.
- [x] **Async task TTL** — default raised from **30** to **120** minutes for long Wiki runs.
- [x] **Per-node timeouts** — **leaf/parent** LLM or compose steps wrapped with **`asyncio.wait_for`** for bounded latency.

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
