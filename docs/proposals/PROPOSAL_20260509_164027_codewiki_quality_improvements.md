# 统一 Backlog: Wiki 管道质量改进

> **Status**: ACTIVE — 统一跟踪文档
> **Created**: 2026-05-09
> **Updated**: 2026-05-09 (Harness-lite 方案补充)
> **Category**: Wiki Quality / Pipeline Enhancement
> **Source**: 聚合自 7 个已归档 spec/plan 文档 + CodeWiki 深度对比分析

---

## 已完成项目 (Sprint 1 — 2026-05-09)

| 编号 | 改进项 | 状态 | Commit |
|------|--------|------|--------|
| P0a | GraphModuleDecomposer 递归分解 (CC + path-prefix) | ✅ 已完成 | `f9dd063`..`b0e2e68` |
| P0b | compose_bottomup 集成 WikiPageAgent | ⚠️ 已回退 → B0 替代 | `42c0da8` (reverted) |
| P1b | LLMPort 协议清理 (移除 agenerate) | ✅ 已完成 | `60b9b03` |
| P1b+ | ParentSynthesizer agenerate→generate 对齐 | ✅ 已完成 | 另一 agent 修复 |
| — | ParentSynthesizer 激活验证 | ✅ 已完成 | `f6e6e66` |
| — | E2E 层次化树 smoke test | ✅ 已完成 | `d7608f6` |
| R1 | CCB call-chain 修复 (caller/callee) | ✅ 已完成 | 归档 |
| R2 | pre-group + real edges in decompose | ✅ 已完成 | 归档 |
| R3 | merge small leaves | ✅ 已完成 | 归档 |
| R5 | CCB + Agent fusion | ✅ 已完成 | 归档 |

---

## 待实现 Backlog

### B0: Harness-lite — 图查询增强单次 LLM 生成 (替代 P0b Agent 多轮)

**优先级**: P0 | **复杂度**: 中 | **来源**: P0b 性能回退后的替代方案

**背景**:

P0b 的 WikiPageAgent 集成因性能问题被另一个 agent 回退。Agent 多轮模式
（每叶子 3-6 次 LLM 调用, ~60s/叶子）过慢。但回退到裸单次 LLM（仅有模块名+文件路径）
产出的文档质量过低（~30%），LLM 无实际代码上下文时会生成幻觉内容。

**方案: 图查询增强 + 单次 LLM**

核心思路：不用 Agent 多轮循环，改用确定性图查询预取上下文，再做单次 LLM 调用。

```
对每个叶子节点:
1. 批量执行图数据库查询 (无 LLM, ~200ms):
   - METHODS_CY: 方法签名 + docstring
   - CALLERS_CY: 调用方信息
   - call_chain_cypher(2): 2层调用链
   - CHUNK_SNIPPETS_CY: 关键代码片段
2. 将查询结果组装为富上下文 prompt
3. 单次 llm.generate(富上下文prompt) (~10s)
```

**性能对比**:

| 指标 | 裸单次LLM(当前) | Harness-lite(本方案) | Agent多轮(已回退) |
|------|---------|-------------|----------|
| LLM 调用数/叶子 | 1 | 1 | 3-6 |
| 图查询数/叶子 | 0 | 3-4 | 5-15 |
| 延迟/叶子 | 5-15s | 6-16s | 30-90s |
| 有实际代码 | ✘ | ✔ | ✔ |
| 有调用链 | ✘ | ✔ | ✔ |
| 文档质量 | ~30% | ~80% | ~90% |

**实现要点**:

- [ ] 新增 `_enrich_leaf_context(node, graph_store) -> str` 函数
  - 复用 `wiki/cypher_queries.py` 中已有的查询常量
  - 4 个查询可并行执行 (`asyncio.gather`)
  - 结果拼接为结构化上下文字符串 (方法列表 / 调用链 / 代码片段)
  - 总上下文限制 ≤ 8000 chars
- [ ] 修改 `_compose_leaf_for_bottomup` 的 fallback 路径
  - 参数恢复 `graph_store: Any | None = None`
  - 当无 `module_summaries` 匹配且 `graph_store` 可用时，调用 `_enrich_leaf_context`
  - 将富上下文注入到 `llm.generate` 的 prompt 中
- [ ] 修改 `compose_bottomup_node` 传递 `graph_store` 到 `_bounded_leaf`
- [ ] 单元测试: mock graph_store 验证 prompt 包含代码片段
- [ ] 集成测试: 验证端到端富上下文生成

**注意**: 不删除 `WikiPageAgent`，保留供 heal_pages (B7) 和未来 sectional 模式 (B4) 使用。

---

### B1: Harness 上下文预算优化 (原 P1a)

**优先级**: P1 | **复杂度**: 低 | **来源**: 质量改进提案

**当前限制**:
- `SINGLE_RESULT_LIMIT = 4000` chars (page_agent.py)
- `CONTEXT_BUDGETS[medium].max_chars_per_section = 3000`
- `WorkingMemory` 总上限 50000

**待实现**:
- [ ] `read_code` / `read_file` 结果 per-section limit 提升到 6000
- [ ] `read_file` 范围扩大到 200 行 (当前 100 行)
- [ ] `module_summaries` 注入 Agent 初始上下文

---

### B2: delegate_submodule 真实实现 (原 P2)

**优先级**: P2 | **复杂度**: 中 | **来源**: CodeWiki 对齐 + 质量改进提案

**当前状态**: `wiki/page_agent.py` 中 `_tool_delegate_submodule` 返回占位内容。

**待实现**:
- [ ] 实现子 `WikiPageAgent` 实例创建
- [ ] 委托深度限制 ≤ 2，每 Agent 最多 3 次委托
- [ ] 子 Agent 结果合并到父 Agent 输出
- [ ] 集成测试

---

### B3: L3 质量评估统一 (4 维 1-5 分制)

**优先级**: P1 | **复杂度**: 中 | **来源**: codewiki-aligned-pipeline spec + graph-driven spec

**当前状态**:
- `WikiQualityEvaluator.llm_judge_evaluate` 使用 3 维 0-1 分制
- `HarnessEvaluator.evaluate_l3` 定义了 4 维 1-5 分制但未被 `evaluate()` 调用
- `quality_gate_node` 使用前者

**待实现**:
- [ ] 统一 L3 为 CodeWiki-style 4 维 (Completeness, Accuracy, Clarity, Usefulness) 1-5 分
- [ ] 将 `HarnessEvaluator.evaluate_l3` 集成到 `evaluate()` 流程
- [ ] 更新 `quality_gate_node` 使用统一的 L3 评估

---

### B4: Harness sectional 生成模式 + coherence pass

**优先级**: P2 | **复杂度**: 高 | **来源**: harness-design spec

**当前状态**: `WikiGenerationHarness.run` 只调用 `agent.generate` 一次，无 sectional 分段生成和 coherence 连贯性检查。

**待实现**:
- [ ] `generation_mode == "sectional"` 分支：逐 section 生成
- [ ] coherence pass：全文连贯性检查和修复
- [ ] 复杂模块自动路由到 sectional 模式

---

### B5: LLM clustering fallback (decomposer)

**优先级**: P3 | **复杂度**: 低 | **来源**: codewiki-aligned-pipeline spec §2.2 Step 4

**当前状态**: 当 CC 无法拆分单个巨型连通分量时，使用 path-prefix 分组 + bisect。Spec 设计了 LLM clustering 作为更智能的 fallback。

**待实现**:
- [ ] `_maybe_split_scc` 中在 path-prefix 之前尝试 LLM clustering (仅当 `self._llm` 存在)
- [ ] LLM prompt: 将成员列表聚类为 ≤5 个语义相关的组

---

### B6: canonical_key 链接统一 (移除 _find_best_domain 启发式)

**优先级**: P2 | **复杂度**: 中 | **来源**: graph-driven-deterministic-decomposition spec

**当前状态**: `wiki/tree_linker.py` 中 nested topic linking 仍使用 `_find_best_domain` 启发式匹配。`_find_domain_by_canonical_key` 已定义但未在该流程中使用。

**待实现**:
- [ ] 将 tree_linker 链接逻辑迁移到基于 `canonical_key` 的确定性匹配
- [ ] 移除或降级 `_find_best_domain` 启发式

---

### B7: heal_pages 暴露图查询工具

**优先级**: P2 | **复杂度**: 低 | **来源**: codewiki-aligned-pipeline spec

**当前状态**: `heal_pages_node` 修复低分页面但不使用 graph 工具获取额外上下文。

**待实现**:
- [ ] heal 流程中将 `graph_store` 传入 repair agent
- [ ] Agent 可使用 `read_code`/`query_call_chain` 获取缺失上下文

---

### B8: HarnessEvaluator L2 真实实现

**优先级**: P2 | **复杂度**: 中 | **来源**: harness-design spec

**当前状态**: `wiki/harness_evaluator.py` 中 `evaluate_l2` 是 stub，直接返回 L1 结果。

**待实现**:
- [ ] 实现真正的 L2 benchmark 评估 (代码块引用覆盖率、Mermaid 图表完整性等)

---

### B9: 竞品差距项 (DEEP_ANALYSIS 遗留)

**优先级**: P3 | **复杂度**: 高 | **来源**: DEEP_ANALYSIS_20260502

长期 backlog，非当前迭代重点：
- B-19: 通用文档摄取 (PDF/Confluence/Notion)
- B-20: 多模态支持 (图像/UML)
- B-21: 学术 benchmark 基础设施
- B-22: 部署简化 (Docker compose one-click)
- Phase 3 语言支持: C/C++/C#/Rust

---

## CodeWiki 对比总结

### 我们的优势
- **持久化增量更新**: 基于 FalkorDB 的增量管道，CodeWiki 每次全量重建
- **多租户/多仓库**: 原生支持多业务隔离，CodeWiki 单仓库设计
- **质量门 + 自愈**: L1/L2/L3 评估层 + heal loop
- **确定性分解**: 真正的图算法 (SCC + topo sort + CC 递归)

### CodeWiki 的优势 (待弥补)
- ~~递归分解~~ → **已实现** (P0a)
- ~~底层源码上下文~~ → P0b 已回退, **B0 Harness-lite 替代方案待实现**
- **Agent 动态委派** → B2 (delegate_submodule)
- **层次化评估** → B3 (L3 统一)

---

## 已归档文档清单

以下文档已在审计后删除（内容已聚合到本文档或已完全实现）：

| 文档 | 归档原因 |
|------|---------|
| `specs/2026-05-08-wiki-remaining-optimizations-design.md` | R1-R5 全部实现 |
| `plans/2026-05-08-wiki-remaining-optimizations.md` | 全部任务完成 |
| `proposals/PROPOSAL_20260508_190818_wiki_remaining_optimizations.md` | 已实现 |
| `specs/2026-05-08-wiki-agent-driven-enhancement-analysis.md` | 研究性分析，有价值内容已迁移 |
| `specs/2026-05-08-wiki-quality-agent-driven-design.md` | 已被 codewiki-aligned 替代 |
| `plans/2026-05-08-wiki-generation-harness.md` | harness 核心已实现 |
| `specs/2026-05-08-wiki-generation-harness-design.md` | harness 核心已实现，残余项入 B4/B8 |
| `plans/2026-05-09-codewiki-quality-improvements.md` | 已执行完成 (Sprint 1) |
| `plans/2026-05-09-codewiki-aligned-pipeline.md` | 大部分已实现，残余项入 B2-B7 |
