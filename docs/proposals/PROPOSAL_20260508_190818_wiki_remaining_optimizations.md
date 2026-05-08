# 提案: Wiki 生成剩余优化项 (统一汇总)

**状态**: Superseded → see `docs/superpowers/specs/2026-05-08-wiki-remaining-optimizations-design.md` and `docs/superpowers/plans/2026-05-08-wiki-remaining-optimizations.md`
**创建时间**: 2026-05-08 19:08
**优先级**: P2 (优化改进, 非阻塞)
**前置**: 所有核心功能已实现并接入 Pipeline (1858 测试通过)

---

## 背景

经过 2026-05-08 的集中开发，Wiki 生成管线的核心功能已全部完成：

| 已完成能力 | 状态 |
|-----------|------|
| CONTEXT_GAP 统一清理 | ✅ 全路径覆盖 |
| Markdown 围栏剥离 | ✅ 通用正则 |
| 图数据 CONTAINS 补全 | ✅ 接入 Indexer |
| Function→Module 调用链 Cypher | ✅ 已改造 |
| 域分类反幻觉 + 小域合并 | ✅ 接入 dependency_graph |
| Agent-Driven 生成 (opt-in) | ✅ 接入 Compose |
| 拓扑排序生成顺序 | ✅ 接入 compose_leaf_pages |
| 源码引用验证 | ✅ 接入 quality_gate |
| 自底向上 Overview 合成 | ✅ 接入 tree_linker |
| ContentContextBuilder | ✅ 统一上下文 |
| 统一 Prompt 模板 | ✅ 双模板体系 |
| DomainStabilizer | ✅ 域名稳定 |
| ProgressiveComposer | ✅ 分批生成 |
| SemanticWikiQuery | ✅ 语义搜索 |
| EntityCardsPanel | ✅ 前端实体卡片 |

本提案汇总所有**尚未完成的 P2 优化项**，来源于之前多个 spec 的剩余条目。

---

## 剩余任务

### R1: CCB 适配 caller_functions/callee_functions 字段

**来源**: 2026-05-08 spec W3 (4.2)
**优先级**: P2
**影响**: 调用链上下文展示更丰富

**现状**: `call_chain_cypher` 已返回 `caller_functions` / `callee_functions` 列（collect 采样 5 个函数名），但 `ContentContextBuilder._query_call_chains` 构建 `CallChainStep` 时未读取这两列。

**改动**: 在 `wiki/content_context_builder.py` 的调用链解析逻辑中，读取 `caller_functions` 和 `callee_functions` 字段，填入 `CallChainStep` 的 `caller_method` / `callee_method` 属性。

**预估**: ~20 行改动 + 测试

---

### R2: 图拓扑预分组 + 目录辅助域分类

**来源**: 2026-05-08 spec W7 (5.1)
**优先级**: P2
**影响**: 提升域分类准确度，减少 LLM 幻觉

**现状**: 域分类完全依赖 LLM + 反幻觉 prompt。图中已有的 Module→Module CALLS 关系和目录结构未被用于预分组。

**改动**:
1. 在 `classify_domains_node` 之前，基于模块间调用关系图构建连通分量，作为 LLM 分类的提示
2. 使用目录路径前缀（如 `com.example.meeting.*`）作为候选域名辅助信号
3. 将预分组结果注入 LLM prompt 作为参考

**预估**: ~150 行新代码 + 测试

---

### R3: 小域页面合并 (1-2 模块 → 单页)

**来源**: 2026-05-08 spec W8 (5.4)
**优先级**: P2
**影响**: 减少过于碎片化的页面

**现状**: `merge_small_domains` 在域分类层合并了小域的模块列表，但 compose 阶段仍然为每个域（即使只有 1-2 个模块）生成独立页面。

**改动**: 在 `compose_leaf_pages_node` 中，对 1-2 模块的域，合并到一个综合页面中，而非生成多个独立页面。

**预估**: ~50 行改动 + 测试

---

### R4: 部署验证 + 全量重新生成

**来源**: 2026-05-08 plan Task 14
**优先级**: P1 (需要生产环境)
**类型**: 运维操作，非代码变更

**检查清单**:
- [ ] 部署 `feat/wiki-quality-agent-driven` 分支到测试环境
- [ ] 对 ultron-composite 执行全量索引，验证 CONTAINS 关系补全日志
- [ ] 执行全量 wiki 重新生成 (business_id=default, incremental=false)
- [ ] 质量扫描：检查 CONTEXT_GAP 残留、虚构内容、citation 验证结果
- [ ] 可选：启用 `WIKI__AGENT_DRIVEN_GENERATION=true` 对部分域测试 Agent-Driven 生成
- [ ] 更新 `docs/KNOWN-ISSUES.md` 和 `docs/IMPLEMENTATION-STATUS.md`

---

## 实施建议

| 优先级 | 任务 | 依赖 |
|--------|------|------|
| P1 | R4 部署验证 | 需要测试环境 |
| P2 | R1 CCB 适配 | 独立，可随时做 |
| P2 | R3 小域合并 | 独立，可随时做 |
| P2 | R2 图拓扑预分组 | 较大，可延后 |

R1 和 R3 总计 ~70 行改动，可在 1 个 session 内完成。R2 较大但不阻塞任何功能。R4 需要运维配合。

---

## 与已归档文档的关系

本提案合并了以下已归档文档中的剩余项：

| 来源文档 | 状态 | 迁移项 |
|----------|------|--------|
| `specs/2026-05-08-wiki-quality-agent-driven-design.md` | ✅ Mostly Complete | R1, R2, R3, R4 |
| `specs/2026-05-06-wiki-topic-filter-parallel-design.md` | ✅ Implemented → archived | 无剩余 |
| `specs/2026-05-06-unified-wiki-enterprise-kb-design.md` | ✅ Mostly Implemented → archived | U6 已通过 overview_synthesizer 部分覆盖 |
| `plans/2026-05-08-wiki-quality-agent-driven.md` | ✅ T1-13 → archived | T14 → R4 |
| `plans/2026-05-08-wiki-pipeline-integration.md` | ✅ 7/7 → archived | 无剩余 |
| `plans/2026-05-08-wiki-pipeline-architecture-optimization.md` | ✅ 全部实现 → archived | 无剩余 |
