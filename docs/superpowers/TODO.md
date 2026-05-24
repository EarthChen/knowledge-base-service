# 待办事项与改进建议

**Created:** 2026-05-24
**Last Updated:** 2026-05-24
**Sources:** 合并自 specs/2026-05-12、specs/2026-05-20、reviews/2026-05-22、reviews/2026-05-24

---

## 一、未实现设计提案

### 1. 多视图 Wiki 结构 [P3]

> 来源: specs/2026-05-12-multi-view-wiki-structure-idea.md

当前 Wiki 仅有"业务域视图"（`/__domains__/`）。构想三种视图：

| 视图 | 路由前缀 | 使用场景 |
|------|---------|---------|
| **业务域视图** | `/__domains__/` | 理解业务功能、跨仓库业务流 |
| **仓库视图** | `/__repos__/` | 代码导航、仓库级架构理解 |
| **技术文档** | `/__tech__/` | 技术决策参考、新人 onboarding |

**待解决**:
- 域概览 vs 主题页面的内容定位（广而浅 vs 窄而深）
- HierarchicalDecomposer 按模块聚类拆分主题（替代 `_maybe_split` 的机械 token 拆分）
- 前端视图切换 UI

### 2. Parent Domain Overview Agent 重构 [P2]

> 来源: specs/2026-05-20-parent-domain-agent-overview-design.md

将 `compose_parent_pages_node` 重构为 Agent 模式（`ParentDomainDocAgent`）。

**核心改造**:
- 继承 `DocOrchestrator`，复用 explore → write → verify 模板方法
- 注入 Wiki 工具（`read_wiki_page`、`query_domain_dependencies` 等）
- 配置开关 `wiki.parent_overview_agent_mode: bool = True`
- 失败降级到现有直接 LLM 模式

**文件清单**: `wiki/parent_domain_doc_agent.py`(新建)、`wiki/agent_prompts.py`、`wiki/nodes/aggregate.py`、`wiki/pipeline_graph.py`、`core/config.py`

### 3. 非代码文件轻量解析 [P2]

> 来源: reviews/2026-05-24 §3.3

`indexer/languages/` 新增 Dockerfile/K8s YAML/Protobuf 轻量 parser。先支持结构提取（service 名、端口、依赖），不需要完整 Tree-sitter AST。参考 Understand-Anything 的 40+ LanguageConfig。

---

## 二、域分类精度优化 [P0-P2]

> 来源: reviews/2026-05-22-domain-classification-review.md

### 已修复

- [x] #6: 硬编码关键词合并 → LLM 动态发现 (Batch 1)
- [x] #9(§6.9): 域命名 LLM 串行 → asyncio.gather 并行化 (Batch 1)

### 未修复

| 优先级 | 问题 | 文件 | 说明 |
|--------|------|------|------|
| P0 | #1: 嵌入文本信息量不足 | `wiki/domain_semantic_clusterer.py` | 路径保留 3-4 级 + 方法签名 + docstring |
| P0 | #2: 小样本跳过聚类 | `wiki/domain_semantic_clusterer.py` | 降低 `_SMALL_N_THRESHOLD` 到 3 |
| P1 | #3: 调用图边折扣因子无权重感知 | `wiki/domain_semantic_clusterer.py` | `discount = 1 - 0.15 * min(w/max_w, 1.0)` |
| P1 | #4: k 值搜索范围过窄 | `wiki/domain_semantic_clusterer.py` | k_min → `max(3, n//15)`, k_max → `min(n//4, 25)` |
| P1 | #5: 全局 LLM 审查信息不足 | `wiki/graph_semantic_corrector.py` | top 10 模块 + 路径 + 摘要 |
| P2 | #8: 嵌入失败 fallback 丢失语义 | `wiki/nodes/graph_domain_decompose.py` | TF-IDF 或名称相似度替代嵌入 |
| P2 | #10: 域稳定器阈值过高 | `wiki/domain_stabilizer.py` | Jaccard 0.85 → 0.7-0.75 + 编辑距离 |
| P3 | #7: 前缀正则不鲁棒 | `wiki/nodes/classify.py` | `IOHandler`、`AJAXUtil` 等不匹配 |
| P3 | #9: 死代码 `correct_module_assignments` | `wiki/graph_semantic_corrector.py` | 生产未调用 |

---

## 三、管线质量与性能 [P1-P3]

> 来源: reviews/2026-05-22 §六

| 优先级 | 问题 | 文件 | 说明 |
|--------|------|------|------|
| P1 | 图查询串行执行 | `wiki/graph_call_query.py:41` | 两条独立 Cypher → `asyncio.gather()` |
| P2 | 变长路径笛卡尔爆炸 | `wiki/graph_call_query.py:10-26` | `CONTAINS*1..3` 双侧遍历考虑降到 `*1..2` |
| P2 | 异常静默吞没 | `wiki/graph_call_query.py:58-59` | 返回 `(edges, errors)` 元组 |
| P2 | Healing 二次 LLM 调用 | `wiki/nodes/heal.py:128-139` | TargetedHealer 成功后仍可能触发 enrich |
| P2 | Token 预算无跨组件协调 | `wiki/token_budget.py` | snippet 预算 3000 对大域不足 |
| P3 | Python 侧过滤应推入 Cypher | `wiki/graph_call_query.py:53-54` | `valid_modules` 过滤在 WHERE 子句 |
| P3 | Quality Gate 和 Healing 重复结构检查 | 多文件 | 同一页面最多检查 4 次 |

### 架构层面

| 问题 | 说明 |
|------|------|
| 域分类未利用叶子页面内容 | `classify_domains` 只用 `business_summary`，不用已生成的叶子页面 Markdown |
| Reassembly 阈值不合理 | merge 0.85 过高建议 0.75，orphan 0.60 偏低建议 0.65 |
| 信号量跨管线场景 | `PipelineConcurrency.semaphore()` 每次新建，多管线并行时全局限制失效 |

---

## 四、已完成归档（2026-05-24 Batch 1-3 + Pipeline Refactor）

以下来自 reviews/2026-05-24 的 12 项建议已全部完成（#11 除外）：

- [x] #1: 子域命名 LLM 并行化 (Batch 1)
- [x] #2: `_RELATED_KEYWORDS` → LLM 动态发现 (Batch 1)
- [x] #3: WikiKnowledgeGraph dagre 布局 (Batch 2)
- [x] #4: 架构层自动标注 `classify_architecture_layers` (Batch 2)
- [x] #5: 增量更新三级变更分类 (Batch 2)
- [x] #6: Guided Tour `generate_tour` (Batch 3)
- [x] #7: 语言概念注入 Agent Prompt (Batch 1)
- [x] #8: Agent Runner 交替重复检测 (Batch 1)
- [x] #9: Heal fallback 策略模式 (Batch 3)
- [x] #10: Business Flow 三级域模型 (Batch 3)
- [ ] #11: 非代码文件轻量解析 (见 §一.3)
- [x] #12: Quality Gate L3 heal 后触发 (Batch 1)

---

*本文档合并自 `docs/superpowers/` 下多份已归档的 spec 和 review 文件，作为统一的待办追踪入口。*
