# Remaining Work (Unified Backlog)

**Created:** 2026-05-09  
**Last Updated:** 2026-05-13  
**Status:** Active — items checked off when merged

---

## 进行中

_(当前无进行中任务)_

---

## 积压项

### P3 — 前端代码质量

- [ ] **F-04: API 响应无运行时校验** — `api/client.ts` 的 `api<T>()` 将 JSON 直接 cast 为 `T`，运行时数据形态完全信任服务端。
- [ ] **WikiSourceLocRow 死代码** — 组件存在但未被任何页面引用（仅测试引用），应清理。

### P1 — 语言插件扩展

- [ ] **C/C++, C#, Rust language plugins** (DEEP_ANALYSIS B-18 remainder) — 9 languages covered, 4 major ones still missing.

### P2 — Product Feature Gaps (from DEEP_ANALYSIS)

- [ ] **B-19: Generic document ingest** — Support PDF, Office (docx/xlsx), HTML as indexable knowledge sources beyond code.
- [ ] **B-20: Multi-modal analysis** — Support images, design files, and non-text content in the knowledge graph.
- [ ] **B-21: Automated quality benchmark** — End-to-end benchmark infrastructure for regression tracking.
- [ ] **B-22: Docker Compose one-click deploy** — Lower deployment barrier; compose file + env template + health probes.

### P2 — 死代码清理

- [ ] **N3: CCB / unified_prompt_templates / 旧 Composer 分支** — Agent 管线已成为唯一路径，`content_context_builder.py` + `unified_prompt_templates.py` + `compose_bottomup` 分支为死代码。

### P3 — 数据质量

- [ ] **source_locations 行号 0-0** — 图节点的 `start_line`/`end_line` 属性在部分节点（如 Java Module 级别）上为 0，导致 `source_locations` 中的行号信息无效。前端已移除源码位置渲染，但 exporter 导出 Markdown 时仍会输出 `file:0–0` 格式的无效链接。根因在代码索引器层面。

---

## 已完成归档

以下工作已全部完成，保留作为审计记录：

- [x] Agent-Driven Business Wiki Phase 0-4 ✅
- [x] Incremental Wiki Update ✅
- [x] Wiki pipeline hardening (2026-05-11) ✅
- [x] Issue #008 Agent 管线质量修复 ✅ (2026-05-12)
- [x] Wiki LLM P0 fix (`_enrich_leaf_context`) — 已通过新 Agent 管线绕过
- [x] Explore/Write 分离 ✅ (2026-05-12) — 固化至 `page_agent.py` + `domain_doc_agent.py`
- [x] Domain Agent 弹性超时 + Wiki⟷Code 深度关联 ✅ (2026-05-12)
- [x] Code Linking 合并 Bug (`_attach_domain_sources`) ✅ (2026-05-12)
- [x] 域分类 v2 slug 全链路传播 ✅ (2026-05-12)
- [x] 质量门改进 ✅ (2026-05-12)
- [x] Agent Compose 默认管线 ✅ (2026-05-12)
- [x] source_locations 覆盖 topic 页面 ✅ (2026-05-12)
- [x] 统一提案 A-D 路径/质量门/内容/Robustness ✅
- [x] 统一提案 F 核心 Explore/Write 分离 ✅
- [x] 统一提案 G 域分类 v2 核心（slug全链路+锚点+信号+持久化+质量） ✅
- [x] 统一提案 T2 存储层 10/10 方法 ✅ (list_domain_anchors, upsert_domain_anchor, delete_domain_anchor, pin_module_to_domain, unpin_module, list_pinned_modules, save_domain_classification, get_checkpoint_info, delete_checkpoint, list_domain_modules, rename_domain)
- [x] 统一提案 T10 Dashboard API 10/11 端点 ✅ (域 CRUD + pin/unpin + checkpoint + list_domain_modules + rename_domain)
- [x] 统一提案 T11 Dashboard UI 核心 ✅ (DomainManagement.tsx + CheckpointPanel.tsx + hooks + 域详情面板 + 重命名对话框)
- [x] 统一提案 T12 触发脚本 8/8 命令 ✅ (list-domains, move-module, unpin-module, reset-anchors, checkpoint-info, checkpoint-delete, resume, regenerate-domain)
- [x] S1: repo_path 传入激活文件读取工具 ✅ (2026-05-13)
- [x] S2: 预注入图索引代码片段到 WorkingMemory ✅ (2026-05-13)
- [x] S3: 工具动态解锁 (T1/T2/T3 三级) ✅ (2026-05-13)
- [x] WorkingMemory 质量改进 ✅ (2026-05-13) — error-aware incorporate + 代码片段去重 + 相关性淘汰
- [x] 前端移除源码位置渲染 ✅ (2026-05-13) — WikiSourceLocRow 从 WikiContent + WikiTopicContent 中移除
- [x] 统一 Agent 抽象 Phase 1 ✅ (2026-05-13) — GenericAgent + ToolRegistry + ToolDef + Memory + WikiPageAgent 继承 + DocOrchestrator
- [x] 统一 Agent 抽象 Phase 2-5 ✅ (2026-05-13) — DomainDocAgent 重构 + ResearchOrchestrator + AskOrchestrator + TopicDocAgent + FlowDocAgent (3396 tests)
- [x] 代码块真实性保障 ✅ (2026-05-13) — 混合验证：CODE_REF 注入 + 后验证替换，DocOrchestrator 自动集成 (3429 tests)

---

*Items here are non-blocking for the current sprint. Prioritise based on user impact and deployment timeline.*
