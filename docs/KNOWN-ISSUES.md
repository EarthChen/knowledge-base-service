# 已知问题与待处理项（Known Issues）

**最后更新：** 2026-05-02  

本文档对已知问题进行**编号管理**，每条包含：**状态**、**影响**、**根因**、**已采取修复或缓解措施**、以及**可在仓库内核验的线索**（源码路径或日志关键字）。条目会在代码演进后过时——若行为已变，请以源码与 [`IMPLEMENTATION-STATUS.md`](IMPLEMENTATION-STATUS.md) 为准并更新本条。

> **已归档**：Issue #001（Wiki 页面粒度过细）、Issue #002（跨仓库域分类合并连接中断）、Issue #005（`_link_pages_to_tree` 循环依赖）已修复并从本文档移除。

---

## Issue #003 — `HierarchicalDecomposer` 批次分解超时与长尾延迟

| 字段 | 内容 |
|------|------|
| **状态** | **已缓解**（硬性超时 + 日志）；仍可 tuning |
| **严重程度** | P2（性能与完整性权衡） |
| **影响描述** | 当模块数量极大时，层级分解将模块拆为多批次；部分批次 LLM 往返 **超过两分钟**，阻塞整体 Wiki 生成进度或导致不稳定。 |

**根因**

- 单批次 prompt token 预算与模块描述拼接体积过大。
- 模型侧长尾延迟（排队、思考链型模型更慢）。

**已采取的缓解**

- **`wiki/dependency_graph.py`**：`decompose` 在逐批调用 `_single_pass` 时使用 **`timeout=120`**，超时或异常则 **`log.warning("hierarchical_decompose_batch_failed", ...)`** 并跳过该批，继承其余批次结果。
- **批次开始/结束结构化日志**：`hierarchical_decompose_batch_start` / `hierarchical_decompose_batch_done`，便于在生产日志中分段计时。
- **SSE / 流式**：上游若在其它路径使用流式 Provider，可降低空闲断开概率（参见 Issue #002）。

**仍可优化的方向**

- 下调 **`max_tokens_per_batch`**（默认 `30_000`）以减少单批模块数。
- 对「按仓库并行分类」等其它批次路径统一超时与降级策略。
- 对「分类-only」任务换用更小更快的模型 profile（结合 `wiki/model_strategy.py`）。

**验证**

- **单元测试**：`tests/wiki/test_nested_domain_tree.py` 等对 `HierarchicalDecomposer` 行为有直接覆盖。
- **运行时**：检索日志关键字 `hierarchical_decompose_batch_failed` 与 `batch_done` 可量化跳过率与耗时。

---

## Issue #004 — Qwen3 / 本地网关「思维链」导致分类批次极慢（疑）

| 字段 | 内容 |
|------|------|
| **状态** | **待调查 / 待证实** |
| **严重程度** | P2 |
| **影响描述** | 在使用 **Local-Qwen**（如 Qwen3-Coder 系列）经 **ai-gateway** 转发时，部分大批量分类批次出现 **100s+** 长尾，怀疑与网关或模型侧的 **thinking / reasoning** 模式有关（尚未在仓库内用单一集成测试锁定根因）。 |

**根因（假设）**

- 模型默认启用思维链或等价「扩展推理」路径，导致 token 产出变慢。
- 网关对特定 `reasoning_effort` 或未知参数 passthrough 行为与预期不符。

**建议解决方向（尚未在仓库内统一开关）**

1. 查证网关是否支持关闭 thinking 的参数（取决于部署版本）。
2. 在分类类 prompt 侧尝试厂商推荐的「禁用思考」指令（若适用）。
3. 对分类与合成任务拆分 **fast / quality** 模型路由（`wiki/model_strategy.py` + 配置）。

**验证**

- 暂无与本 Issue 绑定的自动化断言；需在目标网关 + 模型版本上采集 **单次 `generate`/`generate_stream` 耗时分布** 与 **服务端日志** 后结案。

---

## Issue #005 — Wiki 生成 LLM 幻觉：虚构源码引用与业务逻辑

| 字段 | 内容 |
|------|------|
| **状态** | **已修复（Layer 1）**；Layer 2-3 待开发 |
| **严重程度** | P0（内容正确性） |
| **影响描述** | Wiki 页面出现虚构的 `source://` 行号引用和编造的业务逻辑描述（如幂等校验、风控调用），与真实代码完全不符。 |

**根因**

- **直接原因**：`wiki/service.py` 调用 `run_langgraph_pipeline()` 时未传递 `graph_store` 和 `wiki_store`，导致 `ContentContextBuilder` 在空图上查询，返回零上下文，LLM 全面虚构。
- **间接原因**：缺乏系统级反幻觉防线（机械引用注入、事实核查）。

**已采取的修复**

- **P0 修复**（2026-05-07）：
  - `wiki/service.py`：传递 `graph_store=self._store` 和 `wiki_store=self._wiki_store` 到 `run_langgraph_pipeline`。
  - `wiki/pipeline_orchestrator.py`：接受并透传 `graph_store`/`wiki_store` 到 LangGraph `configurable`。
  - `wiki/persistence.py`：新增 `cleanup_stale_wiki_pages()` 方法，非增量全量生成后自动清理旧 topic 页面。
  - `wiki/unified_prompt_templates.py`：添加反幻觉约束指令。
  - `wiki/content_context_builder.py`：修复 `_CHUNK_SNIPPETS_CY` 关系类型（`HAS_CHUNK` → `PART_OF`）。

**仍待开发**

- **Layer 2**（P1）：Mechanical Citation Injection — 系统自动注入经图数据库验证的 `source://` 引用。
- **Layer 3**（P2）：Post-Generation Fact Check — 提取技术实体，在图数据库中验证存在性。
- 当前已实现 `wiki/citation_verifier.py` + `quality_gate_node` 中的引用校验与惩罚机制（Layer 1 级别）。

**验证**

- 全量重新生成后，新页面内容中类名/方法名/服务名与真实代码吻合。
- `source://` 引用的文件路径和行号经人工抽查确认准确。
- 旧的幻觉页面在非增量重生成后被自动清理。

---

## 维护说明

- 新增 Issue 时请沿用 **`Issue #NNN`** 编号（三位序号）、并补齐「状态 / 影响 / 根因 / 修复 / 验证」五要素。
- 若条目对应的代码路径迁移或行为变更，请同步更新 [`CODEMAPS/INDEX.md`](CODEMAPS/INDEX.md) 或 [`IMPLEMENTATION-STATUS.md`](IMPLEMENTATION-STATUS.md) 中的交叉引用。
