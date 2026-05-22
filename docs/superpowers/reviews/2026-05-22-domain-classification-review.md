# 域分类精度全面审阅报告

**日期**: 2026-05-22
**范围**: 域分类（domain classification）和 wiki 生成管线
**核心问题**: 域分类结果不精准
**验证状态**: 已逐问题通过代码回读验证，修正了 3 处不准确描述（详见各问题标注）

---

## 一、管线架构总览

```
Code Repo → Tree-sitter 解析 → FalkorDB 图存储 + 嵌入索引
                                        ↓
LangGraph Pipeline:
  classify_entity_roles       ← 实体角色过滤（5 种角色）
  → detect_reorg              ← 增量检测
  → graph_decompose           ← 模块级图分解 + 规范化键
  → compose_leaf_modules      ← 叶子模块页面生成
  → classify_domains          ← ★ 域分类（核心审查对象）
  → persist_classification
  → compose_domain_agents     ← 域级文档生成
  → ... → reassemble_domains  ← 后分类修正
  → quality_gate → heal 循环
  → create_links → finalize
```

域分类节点 `graph_driven_domain_decompose_node`（`wiki/nodes/graph_domain_decompose.py`）是主路径，
通过嵌入聚类 + LLM 命名 + 全局审查完成分类。当 graph_store 不可用时回退到纯 LLM 分类。

---

## 二、实体角色过滤（前置步骤）

> **注**: 初版审阅误认为缺乏通用模块过滤机制，实际过滤已相当完善。

`entity_role_classifier.py` 通过两阶段将模块分为 5 种角色：

| 角色 | 判定逻辑 | 是否进入域分类 |
|------|----------|---------------|
| `ENTRY_POINT` | @RestController / Controller / 路由注解 / Handler 后缀 | 是 |
| `HAS_BUSINESS_LOGIC` | 综合评分 >= 40（方法数 35% + 图连接 25% + 语义角色 25% + LOC 15%） | 是 |
| `SUPPORTING` | 综合评分 15~40 | 是 |
| `DATA_MODEL` | DTO/VO/Entity 后缀、@Data + 低方法数、enum/constants、评分<15 | 否 |
| `FRAMEWORK_NOISE` | LOC<10 + 0方法 + 0边、仅 @Component/@Configuration + 0方法 | 否 |

**过滤有效性**：`DATA_MODEL` 和 `FRAMEWORK_NOISE` 已被可靠过滤。`SUPPORTING` 中可能包含部分通用工具类，但它们有业务支撑价值，归入业务域是合理的设计决策。

**存在的小问题**：
- `_NOISE_ONLY_ANNOTATIONS` 仅覆盖 Spring 注解（`@Component`, `@Configuration` 等），非 Spring 项目的噪音检测较弱
- Phase 1 的 `_DATA_SUFFIXES` 用正则 `(DTO|VO|PO|...)$` 匹配，业务中可能存在的合法类名如 `ResultParser` 会被误判（`Result` 后缀）

---

## 三、域分类不精准的核心问题

### 问题 1：嵌入文本信息量不足 [严重]

**文件**: `wiki/domain_semantic_clusterer.py:43-64`

```python
@staticmethod
def build_embedding_texts(modules, summaries, paths) -> list[str]:
    for _repo, name in modules:
        path = _shorten_path(paths.get(name, ""))    # 只保留最后 2 级目录
        summary_text = str(summary_data.get("summary_text", ""))
        if summary_text:
            texts.append(f"{name} [{path}] — {summary_text}")
        else:
            texts.append(f"{name} [{path}]" if path else name)
```

**问题分析**：
- `_shorten_path` 只保留最后 2 级目录（默认 `levels=2`），丢失了项目内的层级结构信息。例如 `com.example.biz.user.service.UserService` 只保留 `user/service`
- `summary_text` 由 `compose_leaf_modules` 节点在域分类之前生成（管线顺序已确认），正常流程下不会为空。但在 LLM 生成失败的模块上确实可能为空
- 即使有摘要，嵌入文本 `{name} [{path}] — {summary}` 仍然偏薄：不包含方法签名、不包含导入关系、不包含注释中的业务术语
- 结果：嵌入向量区分度不足，聚类很大程度上依赖调用图而非语义

**改进建议**：
- 路径保留 3~4 级目录
- 丰富嵌入文本：加入核心方法签名 + 类级 docstring + 导入的业务模块名
- 对空摘要的模块，用类名和方法名列表作为 fallback

---

### 问题 2：小样本直接跳过聚类 [严重]

**文件**: `wiki/domain_semantic_clusterer.py:122-124`

```python
def cluster(self, embeddings, modules, edges) -> list[set]:
    n = len(modules)
    if n < _SMALL_N_THRESHOLD:  # _SMALL_N_THRESHOLD = 10
        return [set(modules)]   # 全部归为一个域
```

**问题分析**：
- 5~9 个模块时完全不聚类，全部归为一个域
- 很多中小型项目恰好在这个范围内，所有模块被粗暴归入一个"大杂烩"域
- 即使模块间语义完全不同（如"用户管理"和"订单处理"），也强制合并

**改进建议**：
- 降低阈值到 3（3 以下确实无法有意义地聚类）
- 3~10 个模块时仍然运行嵌入聚类，但放宽 k 的搜索范围

---

### 问题 3：调用图边折扣因子过于粗暴 [中等]

**文件**: `wiki/domain_semantic_clusterer.py:84-89`

```python
def _compute_distance_matrix(self, embeddings, modules, edges) -> np.ndarray:
    dist = self._compute_cosine_distance(embeddings)
    for src, dst, _w in edges:       # ← 权重 _w 被完全忽略
        if i is not None and j is not None and i != j:
            dist[i, j] *= self._discount  # 固定 0.85
            dist[j, i] *= self._discount
```

**问题分析**：
- 所有边统一乘 0.85 折扣，完全忽略边权重
- 一次核心业务调用（weight=50）和一次偶然的工具类调用（weight=1）被同等对待
- 丢失了调用强度这一重要信号

**改进建议**：
- 权重感知折扣：`discount = 1 - 0.15 * min(w / max_w, 1.0)`
- 或对权重取 log 后归一化，避免极端权重主导

---

### 问题 4：k 值搜索范围过窄导致欠拟合 [中等]

**文件**: `wiki/domain_semantic_clusterer.py:92-94`

```python
def _find_best_k(self, dist, n) -> int:
    k_min = max(self._min_k, n // 20)      # n=60 → k_min=3
    k_max = min(max(k_min + 1, n // 3), self._max_k)  # n=60 → k_max=15, 硬上限
```

**问题分析**：
- `n//20` 起步太保守：60 个模块才搜 3~15 个簇
- 硬上限 `_MAX_CLUSTERS = 15` 对大型项目（200+ 模块）严重不足
- 只用 silhouette score 评估，对非凸簇和噪声数据不稳定
- `linkage="average"` 对嵌入距离矩阵容易产生不平衡的簇大小

**改进建议**：
- k_min 改为 `max(3, n//15)`
- k_max 改为 `min(n//4, 25)` 或动态计算
- 考虑同时用 silhouette + Calinski-Harabasz 综合评估
- 对大型数据集考虑 Ward linkage（更均衡的簇大小）

---

### 问题 5：全局 LLM 审查信息不足 [中等]

**文件**: `wiki/graph_semantic_corrector.py:254-261`

```python
async def review_global_consistency(self, domain_mapping, ...):
    # Build compact listing (top 5 modules per domain, no full summaries)
    for slug, pairs in sorted(domain_mapping.items(), key=lambda x: -len(x[1])):
        top_names = sorted([name for _, name in pairs])[:5]  # 只取前 5 个名字
        lines.append(f"- {slug} ({display}) — {len(pairs)} modules")
        lines.append(f"  {', '.join(top_names)}")            # 没有路径、没有摘要
```

**问题分析**：
- 只传递每个域的前 5 个模块名，没有路径、没有摘要
- LLM 仅凭模块名判断归属和重叠，判断依据严重不足
- 特别是对命名模糊的模块（如 `UserService`），无法区分属于哪个业务域

**改进建议**：
- 传递 top 10 模块 + 路径 + 摘要的精简版
- 对模块数 < 5 的域传递全部模块
- 在 prompt 中增加每个域的代表性方法签名

---

### 问题 6：硬编码关键词合并过于局限 [中等]

**文件**: `wiki/nodes/graph_domain_decompose.py:40-43`

```python
_RELATED_KEYWORDS = [
    frozenset({"intimacy", "closedfriend", "closed"}),  # 社交领域
    frozenset({"family", "guild"}),                      # 游戏/社区领域
]
```

**问题分析**：
- 只覆盖社交/游戏领域，其他业务域完全无效
- 基于子串匹配（`kw in name_lower`），理论上可误匹配（如 `closedLoop` 匹配到 `closed`），但 >50% 阈值过滤了大部分单点误匹配，实际误匹配风险可控
- 核心问题是覆盖范围过于局限，无法处理同义词（如 `auth`/`authentication`/`login`）

**改进建议**：
- 改为基于嵌入向量的自动近义词检测，或至少将子串匹配改为单词边界匹配
- 从配置文件读取关键词组，而非硬编码，方便不同业务域扩展

---

### 问题 7：`_consolidate_split_entities` 前缀正则不鲁棒 [低-中]

**文件**: `wiki/nodes/classify.py:117`

```python
_PREFIX_RE = re.compile(r"^([A-Z][a-z]{2,})")  # 只匹配大写开头 + 3 个以上小写
```

**问题分析**：
- `IOHandler`、`AJAXUtil`、`XMLParser` 等不匹配（无连续小写）
- 阈值 3（共享前缀的模块数）过于随意：两个模块共享前缀就合并可能误伤
- `_GENERIC_PREFIXES` 列表不完整，可能遗漏常见的通用前缀

---

### 问题 8：嵌入失败时丢失全部语义信号 [中等]

**文件**: `wiki/nodes/graph_domain_decompose.py:289-291`

```python
except Exception:
    log.warning("embedding_generation_failed_fallback_louvain", exc_info=True)
    return await _louvain_fallback_clustering(biz_modules, edges), None
```

**问题分析**：
- 嵌入失败后直接降级到纯图论 Louvain 算法
- 完全丢弃所有语义信息（模块名、路径、摘要均未利用）
- Louvain 仅基于调用图拓扑，对弱连接的模块无能为力

**改进建议**：
- Fallback 时使用模块名 + 路径的 n-gram TF-IDF 作为替代嵌入
- 或使用简单的名称相似度（编辑距离）作为补充信号

---

### 问题 9：`correct_module_assignments` 是生产死代码 [低]

**文件**: `wiki/graph_semantic_corrector.py:104`

经 grep 验证：`correct_module_assignments()` 仅在定义处（line 104）和测试文件 `test_graph_semantic_corrector.py` 中出现。生产管线（`graph_domain_decompose_node`）只调用 `review_global_consistency()`，后者已包含合并、重命名和移动的全部功能。`_MODULE_CORRECTION_PROMPT` 也仅在此方法内使用。

**建议**: 保留测试覆盖的功能以备将来拆分使用，或合并到 `review_global_consistency` 后删除冗余代码。

---

### 问题 10：域稳定器阈值过高 [低-中]

**文件**: `wiki/domain_stabilizer.py`

Jaccard 相似度阈值 0.85 意味着只有近乎相同的域才会被稳定映射。改名/重组后的新域很难匹配到历史记录，导致每次运行可能产生不同的域 slug，前端 URL 不稳定。

**建议**: 降低阈值到 0.7~0.75，加编辑距离（Levenshtein）作为辅助匹配手段。

---

## 四、管线架构层面的问题

### 4.1 域分类未利用已生成的叶子页面内容

管线顺序为 `compose_leaf_modules → classify_domains`，但域分类只使用模块的 `business_summary`/`docstring`，不利用已生成的叶子页面内容（最丰富的语义信息）。叶子页面的 Markdown 内容作为嵌入文本会大幅提升聚类质量。

### 4.2 Reassembly 阈值不合理

- `reassembly_merge_threshold: 0.85` 过高：两个域的 overview 页嵌入相似度很难达到 0.85
- `reassembly_orphan_threshold: 0.60` 偏低：可能将不相关的 orphan 错误匹配到域
- 建议：merge 降至 0.75，orphan 升至 0.65

### 4.3 正确性已确认：通用模块过滤有效

~~初版认为缺乏显式基础设施域检测~~ → 实际 `entity_role_classifier.py` 的两阶段过滤已有效排除 `DATA_MODEL` 和 `FRAMEWORK_NOISE`，不需要额外的基础设施域步骤。

---

## 五、改进建议汇总（按优先级）

| 优先级 | 问题 | 改进项 | 文件 | 预期收益 |
|--------|------|--------|------|----------|
| P0 | #1 | 丰富嵌入文本（路径 3-4 级 + 方法签名 + docstring）；摘要正常情况下已由上游节点填充 | `domain_semantic_clusterer.py` | 嵌入区分度显著提升 |
| P0 | #2 | 降低最小聚类阈值到 3 | `domain_semantic_clusterer.py` | 解决中小项目分类 |
| P1 | #3 | 调用图边折扣改为权重感知 | `domain_semantic_clusterer.py` | 强/弱依赖区分 |
| P1 | #4 | 扩大 k 搜索范围，多指标评估 | `domain_semantic_clusterer.py` | 更优簇数量 |
| P1 | #5 | 全局审查传递更多上下文 | `graph_semantic_corrector.py` | LLM 判断更准 |
| P2 | #6 | 关键词合并改为嵌入近义词或可配置关键词 | `graph_domain_decompose.py` | 通用化 |
| P2 | #8 | 嵌入失败 fallback 保留语义信号 | `graph_domain_decompose.py` | 降级质量提升 |
| P2 | #10 | 域稳定器降低阈值 + 编辑距离 | `domain_stabilizer.py` | 跨运行稳定性 |
| P3 | #7 | 前缀正则鲁棒性改进 | `classify.py` | 减少误合并 |
| P3 | #9 | 清理生产死代码 `correct_module_assignments` | `graph_semantic_corrector.py` | 降低维护成本 |
| P3 | 架构 | Reassembly 阈值调整 | `core/config.py` | 更合理合并粒度 |

---

## 六、管线质量与性能审阅（补充）

### 6.1 图查询：两条独立 Cypher 串行执行 [性能，P1]

**文件**: `wiki/graph_call_query.py:41`

```python
for cypher in (_MODULE_CALLS_CYPHER, _MODULE_DEPENDS_ON_CYPHER):
    result = await graph_store.execute_query(cypher, {"repos": repositories})
```

两条查询完全独立（CALLS vs DEPENDS_ON，Function vs Class），串行执行浪费了约一倍的等待时间。

**建议**: 改为 `asyncio.gather()` 并行执行。

### 6.2 图查询：变长路径 `CONTAINS*1..3` 双侧遍历 [性能，P2]

**文件**: `wiki/graph_call_query.py:10-26`

```cypher
MATCH (m1:Module)-[:CONTAINS*1..3]->(f1)-[:CALLS]->(f2)<-[:CONTAINS*1..3]-(m2:Module)
```

双侧 `CONTAINS*1..3` 在大型代码库上产生笛卡尔爆炸。模块层级越深、CONTAINS 边越多，查询时间指数级增长。

**建议**:
- 评估是否可将深度降到 `*1..2`（绝大多数项目的模块嵌套不超过 2 层）
- 添加 `USING INDEX` hint 引导 FalkorDB 查询计划
- 考虑预计算模块→函数/类的映射关系，避免每次查询都做路径遍历

### 6.3 图查询：Python 侧过滤而非 Cypher WHERE [性能，P3]

**文件**: `wiki/graph_call_query.py:53-54`

```python
if source_node not in valid_modules or target_node not in valid_modules:
    continue
```

`valid_modules` 过滤在 Python 侧完成，FalkorDB 返回了大量后续被丢弃的行。应将过滤推入 Cypher 的 `WHERE` 子句，减少数据传输量。

### 6.4 图查询：异常静默吞没 [质量，P2]

**文件**: `wiki/graph_call_query.py:58-59`

```python
except Exception:
    log.warning("fetch_module_edges_query_failed", cypher=cypher[:40], exc_info=True)
```

查询失败时仅记录日志继续执行，调用方无法区分"无边"和"查询失败"。域分类完全依赖调用图，部分边缺失可能导致错误的聚类结果。

**建议**: 返回 `(edges, errors)` 元组，或至少记录失败的查询名称供下游参考。

### 6.5 Healing 过程中 TargetedHealer 成功后仍可能触发二次 LLM 调用 [性能，P2]

**文件**: `wiki/nodes/heal.py:128-139`

```python
if targeted_result:
    raw_content = targeted_result.content or ""
    cleaned = cleanup_context_gaps(raw_content)
    page_dict["content"] = cleaned
    if graph_store is not None and (raw_has_context_gap or too_short_after_clean):
        agent = WikiPageAgent(llm, graph_store)
        new_content = await agent.enrich(...)  # 二次 LLM 调用
```

TargetedHealer 成功后，如果内容仍有 CONTEXT_GAP 标记或长度不足 200 字符，会再触发一次 `WikiPageAgent.enrich()` LLM 调用。这在 healing 循环中可能导致大量额外的 LLM 调用。

**建议**: 在 TargetedHealer 的 prompt 中明确要求不要留下 CONTEXT_GAP 标记，或对 enrich 调用设置更严格的触发条件。

### 6.6 Quality Gate 和 Healing 重复执行结构检查 [性能，P3]

管线中同一个页面的结构检查可能被执行多次：
1. `quality_gate_node` 对所有页面执行 `structural_check`
2. `heal_pages_node._update_heal_hint` 再次对 healing 页面执行 `bench_score` / `structural_check`
3. `heal_pages_node._page_passes_post_heal` healing 后再次执行 `structural_check`
4. 页面返回 `quality_gate` 后再次执行全部检查

对 healing 中的页面来说，同一次管线运行中同一页面的结构检查最多执行 4 次。

**建议**: 将 quality_gate 的检查结果传递给 heal 节点复用，healing 后只做增量验证。

### 6.7 Token 预算无跨组件协调 [质量，P2]

**文件**: `wiki/token_budget.py`

各组件（topic_page_generate、domain_classify、domain_overview 等）独立从同一 base（30,000 tokens）分配预算，无全局记账。当多个组件在并行 LLM 调用中同时运行时，总 token 消耗可能超过上下文窗口。

Snippet 预算硬上限 3,000 tokens（约 25 个模块后截断），对大型域可能丢失关键代码上下文，影响生成质量。

**建议**: 对 snippet 预算改为 `min(500 + module_count * 100, 6000)`，或根据域的 ImportanceTier 动态调整。

### 6.8 信号量正确性：单管线内有效，跨管线场景需注意 [正确性，已验证]

经核实 `PipelineConcurrency.semaphore("heal")` 在每次调用时创建新信号量（`pipeline_concurrency.py:60-62`）。在**单管线单节点**场景下，信号量在节点函数内共享给所有子任务，正确限制了并发。但在**跨管线**（多个 pipeline 并行运行）场景下，各管线独立持有信号量，全局并发限制失效。

**当前影响**: 生产中通常是单管线运行，暂无实际影响。如未来支持多管线并行，需改为单例模式。

### 6.9 域命名的 LLM 调用是串行的 [性能，P2]

**文件**: `wiki/nodes/graph_domain_decompose.py:371-401`

```python
for community in communities:
    naming = await namer.name_community(...)  # 串行 await
```

每个域的命名是串行 LLM 调用。10 个域 = 10 次串行 LLM 调用。

**建议**: 改为 `asyncio.gather()` 并行命名（注意去重逻辑需后置）。或使用 `name_communities_batch` 方法（已定义但未被使用）。
