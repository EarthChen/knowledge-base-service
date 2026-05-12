# Agent Wiki 质量修复 + 前端树适配 + 已知问题统一提案

**Created:** 2026-05-12  
**Last Updated:** 2026-05-12 (深度代码审阅后重排优先级)  
**Status:** 待审批  
**Priority:** P0  
**Type:** 统一提案（Spec）

---

## 1. 背景

2026-05-12 完成了 Agent 管线的首次端到端调试验证，发现并修复了 3 个阻塞性 Bug：

1. **`USE_AGENT_COMPOSE` 环境变量无法从 .env 加载** — `pipeline_graph.py` 直接用 `os.environ.get()`，改用 `_get_env()` 修复
2. **`from __future__ import annotations` 导致 LangGraph config=None** — LangGraph 反射无法匹配字符串注解的 `RunnableConfig`，移除该 import 修复
3. **`_make_page` 字段名不兼容下游** — `"type"` → `"page_type"`，补全 `diagrams`/`source_locations`/`metadata` 字段

修复后 Agent 管线成功运行：
- 24 个域页面生成，coverage=100%，citation_density 0.56~1.75
- quality_gate 解析 24/24 通过，heal 后 to_heal=0
- 页面包含 Mermaid 图、Java 代码块、`source://` 链接

但仍存在以下问题需要解决。

---

## 2. 当前发现的问题

### Issue A: 图分解输出未被 Agent 管线消费

**现状：** `graph_decompose_node` 产出 `module_tree`（WCC/SCC 分解结果），但 `compose_domain_agents_node` 仅消费 `domain_tree` 和 `module_summaries`，不读取 `module_tree` 或 `canonical_keys`。

**影响：** 图分解作为管线的"结构基础"未能约束 Agent 的上下文边界，违反设计文档 §3 的架构意图。

**建议方案：** 在 `_build_baseline()` 中注入 `module_tree` 中对应域的子树，让 Agent 了解模块间的依赖拓扑和层次关系。

### Issue B: Wiki 树前端显示不出内容

**现状：**
- `WikiTreeLinker._create_sections()` 为域生成 synthetic overview 页面，path 格式为 `/__domains__/{domain.name}/_overview`
- Agent 的 `_make_page()` 用 `key.replace(" ", "_").replace("/", "_")` 生成纯扁平 slug（如 `挚友关系管理`）
- 前端 `WikiShell` 用 exact path 匹配 → `useWikiPageByPath` → `GET /wiki/pages/by-path?path=...`
- 路径不一致 → "Wiki page not found"

**根因：** Agent 管线的页面路径与 TreeLinker 的 synthetic overview 路径不一致。

**建议方案：**
1. 修改 `_make_page()` 的 path 格式为 `/__domains__/{key}/_overview`，与 TreeLinker 对齐
2. 修改 TreeLinker `_create_sections`：在生成 synthetic overview 前，检查是否已有 Agent 生成的同路径 `domain_overview` 页面，如有则跳过合成、直接复用

### Issue C: Topic 文档缺失

**现状：** Agent 管线仅生成 `page_type=domain_overview` 类型页面，不生成 `page_type=topic` 页面。`plan_topic_structure_node` 和 `compose_leaf_pages_node` 未接入当前管线。

**影响：** 前端主题树中无 topic 叶子节点，域级文档虽有内容但导航结构不完整。

**建议方案：** 当前 domain_overview 已覆盖域级文档需求。考虑在 DomainDocAgent 中支持可选的 `_maybe_split()` 将大域拆分为多个 topic 子页面，或后续以单独 Phase 实现。

### Issue D: 部分页面内容混入工具调用过程

**现状：** 某些 domain_overview 页面内容中包含 `read_code(...)` 等工具调用描述，混入了 Agent 的"思考过程"到最终输出。

**根因：** `WikiPageAgent` 的 generate prompt 未严格要求"仅输出最终 Wiki 内容"。已有 `strip_agent_artifacts()` 后处理但正则覆盖可能不完整。

**建议方案：**
1. 在 `agent_prompts.py` 的 GENERATE prompt 增加明确的输出规范约束
2. 加强 `strip_agent_artifacts()` 的正则匹配覆盖面

### Issue E: heal_pages 阶段所有页面都需要 heal

**现状：** quality_gate 首轮 `to_heal=24`（100%），意味着所有 Agent 生成的页面都触发了 heal 流程。

**根因（代码级确认）：** `wiki/quality_evaluator.py` 的 structural_check 使用 heading marker 匹配，与 Agent prompt 指定的标题不一致：

| 检查项 | evaluator 期望的 heading | Agent prompt 产出的 heading | 匹配? | 扣分 |
|--------|-------------------------|---------------------------|-------|------|
| `_structural_has_overview` | `## 概述` | `## 概述` | ✅ | 0 |
| `_structural_has_components` | `## 核心服务要点`, `## 核心业务流程` 等 | `## 关键实现` | ❌ 不匹配 | -0.25 |
| `_structural_has_relationships` | `## Relationships`, `## 关联主题`, `## 关联关系` | `## 依赖关系` | ❌ 不匹配 | -0.2 |
| `no_diagrams` | `len(page.diagrams) > 0` | Mermaid 在 content 中，`diagrams` 字段为空列表 | ❌ | -0.15 |
| `content_too_short` | `len(body) > 200` | 大多数页面满足 | ✅ | 0 |

**总计系统性扣分 ≥ 0.6**，剩余得分 ≤ 0.4，低于标准阈值 0.5 → **所有页面必然触发 heal**。

**修复方案（不需要调整阈值）：**
1. `_STRUCT_COMPONENT_MARKERS` 扩展：加入 `"## 关键实现"`
2. `_STRUCT_RELATIONSHIP_MARKERS` 扩展：加入 `"## 依赖关系"`, `"## 外部依赖"`
3. `_structural_has_diagrams` 修改：除 `page.diagrams` 外，也检查 content 中是否有 `` ```mermaid `` 代码块

---

## 3. 历史遗留已知问题（来自 KNOWN-ISSUES.md）

### Issue #003 — `HierarchicalDecomposer` 批次分解超时与长尾延迟

| 字段 | 内容 |
|------|------|
| **状态** | **已缓解**（硬性超时 + 日志）；仍可 tuning |
| **严重程度** | P2 |
| **影响** | 模块数量极大时，层级分解部分批次 LLM 往返超过两分钟 |
| **缓解** | `decompose` 使用 `timeout=120`，超时跳过该批 |
| **可优化** | 下调 `max_tokens_per_batch`；对分类任务用更小模型 |

### Issue #004 — Qwen3 / 本地网关「思维链」导致分类批次极慢

| 字段 | 内容 |
|------|------|
| **状态** | **待调查** |
| **严重程度** | P2 |
| **影响** | 使用 Qwen3 经 ai-gateway 时，部分批次出现 100s+ 长尾 |
| **方向** | 查证网关是否支持关闭 thinking；拆分 fast/quality 模型路由 |

### Issue #005 — Wiki 生成 LLM 幻觉：虚构源码引用与业务逻辑

| 字段 | 内容 |
|------|------|
| **状态** | **已修复（Layer 1）**；Layer 2-3 待开发 |
| **严重程度** | P0 |
| **根因** | `run_langgraph_pipeline()` 未传递 `graph_store`/`wiki_store`，LLM 在空上下文中全面虚构 |
| **修复** | 已传递 graph_store/wiki_store；添加反幻觉 prompt 约束；citation_verifier Layer 1 |
| **待开发** | Layer 2 机械引用注入；Layer 3 事实核查 |

### Issue #006 — `_enrich_leaf_context` UID vs name 不匹配

| 字段 | 内容 |
|------|------|
| **状态** | **已绕过**（Agent 管线不走 compose_bottomup） |
| **严重程度** | P0（仅影响旧管线） |
| **根因** | entity UIDs 传入 Cypher 的 `$names` 参数，图查询返回零行 |
| **现状** | 新 Agent 管线绕过了此问题；旧管线已标记废弃 |

### Issue #007 — Phase1 跳过 data_model/framework_noise 但 Phase2 仍触发 LLM

| 字段 | 内容 |
|------|------|
| **状态** | **已绕过**（Agent 管线不走 compose_bottomup Phase2） |
| **严重程度** | P1（仅影响旧管线） |
| **根因** | Role-based exclusion 未传播到 Phase2 leaf composition |
| **现状** | 新 Agent 管线不依赖 Phase2；旧管线已标记废弃 |

### Issue #008 — Agent 管线生产输出质量低于 POC 基线

| 字段 | 内容 |
|------|------|
| **状态** | **已修复** ✅ (2026-05-12) |
| **严重程度** | P0 |
| **根因** | 三个 Bug 叠加：(1) `USE_AGENT_COMPOSE` 无法从 .env 加载，管线走 bottomup；(2) `from __future__ import annotations` 导致 config=None/LLM=None；(3) `_make_page` 字段名不兼容 quality_gate |
| **修复** | 见本文档 §1 背景段落 |
| **验证** | coverage=100%, citation_density 0.56~1.75, 页面含 Mermaid/代码块/source:// 链接 |

---

## 4. 实施任务（代码审阅后重排优先级）

> 排序依据：**用户可见影响** × **修复复杂度**。高影响 + 低复杂度优先。

### Task A: Wiki 树路径对齐 + quality_gate heading 修复 (Issue B + E) — P0

**阻塞性问题**：前端无法加载 Agent 生成的页面内容 + 100% 页面触发无意义 heal。

路径对齐（Issue B）：
- [ ] 修改 `wiki/domain_doc_agent.py` `_make_page()` path 格式为 `/__domains__/{key}/_overview`
- [ ] 修改 `wiki/tree_linker.py` `_create_sections`：检查是否已有 Agent 生成的 domain_overview 页面，已有则跳过 synthetic overview
- [ ] 验证前端主题树能正确显示并加载内容

Quality Gate heading 修复（Issue E 根因）：
- [ ] `wiki/quality_evaluator.py`: `_STRUCT_COMPONENT_MARKERS` 加入 `"## 关键实现"`
- [ ] `wiki/quality_evaluator.py`: `_STRUCT_RELATIONSHIP_MARKERS` 加入 `"## 依赖关系"`, `"## 外部依赖"`
- [ ] `wiki/quality_evaluator.py`: `_structural_has_diagrams` 除 `page.diagrams` 外，也检查 content 中 `` ```mermaid `` 块
- [ ] 验证 heal 比例显著降低（目标 < 30%）

### Task B: Prompt 输出规范 + 后处理加强 (Issue D) — P1

- [ ] `wiki/agent_prompts.py`: GENERATE prompt 增加输出规范段落（禁止输出工具调用代码和中间推理过程）
- [ ] `wiki/page_agent.py`: 检查 `strip_agent_artifacts()` 正则覆盖面，补充缺失的清理模式
- [ ] 验证新 prompt 下无工具痕迹

### Task C: 图分解数据注入 Agent baseline (Issue A) — P2

- [ ] 在 `compose_domain_agents_node` 中从 state 读取 `module_tree`
- [ ] 在 `_build_baseline()` 中注入域对应子树的依赖拓扑信息
- [ ] 验证 Agent 工具调用是否利用了拓扑信息

### Task D: Topic 页面支持 (Issue C) — P2

- [ ] 评估是否在 DomainDocAgent 中通过 `_maybe_split()` 生成 topic 子页面
- [ ] 或设计独立的 topic 生成阶段
- [ ] 待 Task A 完成后根据前端效果决定优先级

### Task E: Anti-Hallucination Layer 2-3 (Issue #005 延续) — P2

- [ ] Layer 2：Mechanical Citation Injection — 自动注入经图数据库验证的 `source://` 引用
- [ ] Layer 3：Post-Generation Fact Check — 提取技术实体，在图数据库中验证存在性

### Task F: Robustness 加固 — P2

- [ ] `grep_code` 超时保护：`WikiPageAgent._tool_grep_code` 添加 `asyncio.wait_for` + 文件数上限
- [ ] `HarnessConfig.from_env` 错误处理：环境变量解析失败时 log warning + fallback
- [ ] `WorkingMemory` FIFO 效率：`_entries.pop(0)` 改为 `collections.deque`

### Task G: L2 业务流文档生成 — P3（来自设计文档 Phase 4 遗留）

- [ ] 创建 `BusinessFlowAgent`（从入口点追踪调用链：HTTP→RPC→Kafka 全链路）
- [ ] 创建 `compose_business_flow_node`（L2 业务流文档 + wikilink 引用 L1）
- [ ] 前端 Wiki 树：L3 概览 → L2 业务流 → L1 域文档 三层导航

### Task H: Prompt 代码层优化 — P3（来自设计文档 §14.2 遗留）

- [ ] Explore/Write 代码分离：将 `generate()` 拆分为两次独立 LLM 调用（Explore→JSON memo→Write）
- [ ] 工具动态解锁：初始只注册核心工具（~6），复杂场景时动态注册进阶工具（~10）
- [ ] baseline 相关性排序：按被调用次数排序模块（PageRank 思路），核心模块优先展示

---

## 5. 已完成工作（本次调试 2026-05-12）

以下修复已在代码中完成，待正式提交：

- [x] `wiki/pipeline_graph.py`: `_get_env()` 读取 `USE_AGENT_COMPOSE`
- [x] `wiki/nodes/domain_compose.py`: 移除 `from __future__ import annotations`
- [x] `wiki/domain_doc_agent.py`: `_make_page()` 字段名 `"type"` → `"page_type"` + 补全必要字段
- [x] `wiki/nodes/domain_compose.py`: `_make_error_placeholder()` 同步修复
- [x] `wiki/pipeline_graph.py`: 移除调试日志代码
- [x] `wiki/nodes/domain_compose.py`: 移除调试日志代码

---

## 6. 已清理的文档

以下提案/计划的主体工作已全部完成，已从文件系统中移除：

| 文件 | 原状态 | 处理 |
|------|--------|------|
| `plans/2026-05-11-agent-driven-wiki-implementation.md` | Phase 1-3 全部完成 | 已删除 |
| `plans/2026-05-11-incremental-wiki-update.md` | 6 个 Task 全部完成 | 已删除 |
| `plans/2026-05-12-agent-l1-quality-fix-and-robustness.md` | 被本提案取代 | 已删除 |
| `plans/2026-05-12-l2-business-flow-and-hardening.md` | 被本提案取代 | 已删除 |
| `specs/2026-05-11-agent-wiki-implementation-proposal.md` | 已合并入设计文档 | 已删除 |
| `specs/2026-05-11-incremental-wiki-update-design.md` | Implemented ✅（全部完成） | 已删除 |
| `specs/2026-05-11-agent-driven-business-wiki-design.md` | Phase 0-4 ✅，遗留项已迁移至本提案 | 已删除 |
| `DEEP_ANALYSIS_20260502_101930_code_audit_and_competitor_gap.md` | 审计全部完成，遗留项已迁移至 REMAINING-WORK.md | 已删除 |
