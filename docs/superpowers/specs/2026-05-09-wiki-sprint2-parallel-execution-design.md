# Wiki Sprint 2: 并行分组执行设计

> **Status**: APPROVED
> **Created**: 2026-05-09
> **Category**: Architecture / Wiki Quality / Pipeline Enhancement
> **Approach**: 3 并行工作流 + TDD + Subagent-Driven
> **Source**: `docs/proposals/PROPOSAL_20260509_164027_codewiki_quality_improvements.md` B0-B8

---

## 1. Background

Sprint 1 完成了递归分解 (P0a)、Agent 集成 (P0b，后回退)、LLMPort 清理 (P1b)。
当前 Backlog 有 9 项待实现 (B0-B8)，需要在保持代码稳定性的前提下并行推进。

**核心问题**: P0b 的 WikiPageAgent 多轮集成因性能问题回退，导致叶子节点文档质量从 ~90% 降至 ~30%。

---

## 2. Execution Architecture

3 个独立工作流并行执行，最后 B4 收尾。

```
┌─────────────────────────────────────────────────────┐
│               Sprint 2: 并行执行                     │
│                                                     │
│  ┌──────────────┐ ┌─────────────┐ ┌──────────────┐  │
│  │ 工作流A:      │ │ 工作流B:     │ │ 工作流C:      │  │
│  │ 上下文增强    │ │ 评估体系     │ │ 基础设施      │  │
│  ├──────────────┤ ├─────────────┤ ├──────────────┤  │
│  │ A1: B0       │ │ B1: B3      │ │ C1: B5       │  │
│  │ Harness-lite │ │ L3评估统一   │ │ LLM cluster  │  │
│  ├──────────────┤ ├─────────────┤ ├──────────────┤  │
│  │ A2: B1       │ │ B2: B8      │ │ C2: B6       │  │
│  │ 上下文预算    │ │ L2实现      │ │ canonical_key│  │
│  ├──────────────┤ └─────────────┘ ├──────────────┤  │
│  │ A3: B7       │                │ C3: B2       │  │
│  │ heal图查询    │                │ delegate     │  │
│  └──────────────┘                └──────────────┘  │
│                                                     │
│  ─────────── 待 A+C 完成 ────────────────────       │
│                                                     │
│  ┌────────────────────────────────────────┐          │
│  │ 收尾: B4                               │          │
│  │ Harness sectional + coherence pass     │          │
│  └────────────────────────────────────────┘          │
└─────────────────────────────────────────────────────┘
```

### 2.1 文件冲突分析

各工作流修改的文件无交叉:

| 工作流 | 主要修改文件 | 冲突风险 |
|--------|------------|---------|
| A (B0/B1/B7) | `graph_nodes.py`, `page_agent.py`, `heal.py` | 无 |
| B (B3/B8) | `quality_evaluator.py`, `harness_evaluator.py`, `pipeline_graph.py` | 无 |
| C (B5/B6/B2) | `graph_module_decomposer.py`, `tree_linker.py`, `page_agent.py` | ⚠️ A2与C3共享 `page_agent.py` |

`page_agent.py` 冲突缓解: A2 修改常量 (`SINGLE_RESULT_LIMIT`)，C3 修改方法 (`_tool_delegate_submodule`)，不同区域，可安全并行。

---

## 3. 工作流 A: 上下文增强 (B0 → B1 → B7)

### A1: B0 — Harness-lite 图查询增强单次 LLM

**目标**: 在不增加 LLM 调用次数的前提下，通过预取图数据库上下文将叶子文档质量从 ~30% 提升至 ~80%。

**实现**:

1. 新增 `_enrich_leaf_context(node, graph_store) -> str`:
   - 并行执行 4 个 Cypher 查询 (`asyncio.gather`):
     - `METHODS_CY`: 方法签名 + docstring
     - `CALLERS_CY`: 调用方信息
     - `call_chain_cypher(2)`: 2 层调用链
     - `CHUNK_SNIPPETS_CY`: 关键代码片段
   - 结果组装为结构化上下文字符串，总限 ≤ 8000 chars
   - 位置: `wiki/nodes/graph_nodes.py`

2. 修改 `_compose_leaf_for_bottomup`:
   - 恢复 `graph_store: Any | None = None` 参数
   - 当无 `module_summaries` 匹配且 `graph_store` 可用时，调用 `_enrich_leaf_context`
   - 将富上下文注入 `llm.generate` 的 prompt

3. 修改 `compose_bottomup_node`:
   - 从 `config` 提取 `graph_store`
   - 传递给 `_bounded_leaf`

**测试**:
- `test_enrich_leaf_context_returns_structured_text`: mock graph_store 返回方法/调用链/代码，验证输出格式
- `test_compose_leaf_uses_enriched_context_when_graph_available`: 验证 prompt 包含实际代码片段
- `test_compose_leaf_fallback_without_graph_store`: 无 graph_store 时行为不变

### A2: B1 — 上下文预算优化

**目标**: 提升 Agent 工具返回的上下文量。

**实现**:
- `page_agent.py`: `SINGLE_RESULT_LIMIT = 4000` → `6000`
- `page_agent.py`: `_tool_read_file` 默认范围 100 行 → 200 行
- `page_agent.py`: `WorkingMemory.MAX_TOTAL_CHARS = 50000` → `80000`

**测试**: 更新现有 `test_page_agent.py` 中的断言值。

### A3: B7 — heal_pages 暴露图查询工具

**目标**: heal 流程中修复低分页面时可使用图查询获取缺失上下文。

**实现**:
1. `heal.py`: `heal_pages_node` 从 `config` 提取 `graph_store`
2. 实例化 `WikiPageAgent(llm, graph_store)` 并调用 `agent.enrich(content)` 替代纯 LLM rewrite
3. 复用 B0 中已验证的 graph_store 传递模式

**测试**: mock graph_store + mock llm，验证 heal 后内容包含图查询结果。

---

## 4. 工作流 B: 评估体系 (B3 → B8)

### B1: B3 — L3 质量评估统一

**目标**: 统一 L3 评估为 CodeWiki-style 4 维 1-5 分制。

**当前状态**:
- `WikiQualityEvaluator.llm_judge_evaluate` (3 维 0-1 分)
- `WikiPageEvaluator.evaluate_l3` (4 维 1-5 分) — 已实现但未接入

**实现**:
1. `quality_evaluator.py`: `llm_judge_evaluate` 调用 `HarnessEvaluator.evaluate_l3` 并将 1-5 分制归一化到 0-1
2. `pipeline_graph.py` `quality_gate_node`: L3 分数写入 `quality_scores` dict
3. 统一 4 维: Completeness, Accuracy, Readability, Structure

**测试**: 验证 `llm_judge_evaluate` 返回 4 维分数，分值在 0-1 范围。

### B2: B8 — HarnessEvaluator L2 真实实现

**目标**: 实现基于静态分析的 L2 benchmark 评估。

**实现**:
- `harness_evaluator.py` `evaluate_l2`:
  - 代码块引用覆盖率: `re.findall(r'`[A-Z]\w+`', content)` vs modules
  - Mermaid 图表完整性: 检查 `mermaid` fence 存在且语法正确
  - 交叉引用完整性: `[[...]]` 链接是否指向已知 canonical_key
  - 输出: 加权 EvalResult (不再 stub 返回 L1)

**测试**: 构造含/不含代码块、Mermaid、链接的 content，验证分数差异。

---

## 5. 工作流 C: 基础设施 (B5 → B6 → B2)

### C1: B5 — LLM clustering fallback

**目标**: 当 CC 和 path-prefix 均无法有效拆分巨型 SCC 时，使用 LLM 进行语义聚类。

**实现**:
- `graph_module_decomposer.py` `_maybe_split_scc`:
  - 在 `_group_by_path_prefix` 之前，若 `self._llm` 存在且成员数 > 10:
    - 调用 `self._llm.generate()` 请求将成员聚类为 ≤5 个语义组
    - 解析 JSON 结果，若失败则 fallback 到 path-prefix
  - 非关键路径: LLM 失败时静默降级

**测试**: mock llm 返回聚类结果，验证分组正确; mock llm 异常，验证 fallback 到 path-prefix。

### C2: B6 — canonical_key 链接统一

**目标**: 移除 `_find_best_domain` 启发式，使用 canonical_key 确定性匹配。

**实现**:
- `tree_linker.py`: 将模糊匹配逻辑替换为精确的 `canonical_key` 查找
- 保留 `_find_best_domain` 作为降级 fallback (不删除，标记 deprecated)

**测试**: 构造含 canonical_key 的 pages，验证链接使用精确匹配。

### C3: B2 — delegate_submodule 真实实现

**目标**: WikiPageAgent 可创建子 Agent 实例处理子模块。

**实现**:
- `page_agent.py` `_tool_delegate_submodule`:
  - 创建子 `WikiPageAgent` 实例 (共享 `graph_store`, `llm`)
  - 设置 `_delegation_depth = parent_depth + 1`
  - 调用 `sub_agent.generate(entity_names, focus)` 
  - 返回子 Agent 生成的内容
  - 保持深度限制 ≤ 2，每 Agent 最多 3 次委托

**测试**: mock 子 Agent，验证委托链限制和结果合并。

---

## 6. 收尾: B4 — Harness sectional + coherence pass

**前置条件**: 工作流 A (B1 上下文优化) + 工作流 C (B2 delegation) 完成。

**目标**: 复杂模块使用分段生成策略，最后做连贯性检查。

**实现**:
1. `harness.py` `WikiGenerationHarness.run`:
   - `assessment.level == "complex"` 时进入 sectional 模式
   - 按 plan.outline sections 逐段调用 `agent.generate`
   - 最终 coherence pass: 单次 LLM 检查全文连贯性并修复

**测试**: mock complex assessment，验证 sectional 模式触发和 coherence pass 调用。

---

## 7. TDD + Subagent 执行规则

每个工作流作为一组 subagent 任务:

1. **Red**: 写失败测试 → `pytest` 验证失败
2. **Green**: 实现最小代码 → `pytest` 验证通过
3. **Refactor**: 清理 → `pytest` 验证仍通过
4. **Commit**: 每个 B-item 一个 commit

双层审查:
- **Spec compliance**: 实现与本文档描述一致
- **Code quality**: 无引入 linter 错误，测试覆盖关键路径
