# 域分类 + 管线性能 精准修复设计

**Created:** 2026-05-24T18:38  
**Status:** Approved  
**Approach:** A — Surgical Fixes (逐项独立修复，不引入新抽象)

---

## 概述

基于对 `docs/superpowers/TODO.md` §二(域分类精度) + §三(管线质量与性能) 全部 6 项 TODO 的深度代码审计，采用精准手术方案：每项修复独立可测、独立可回退，最小化变更面。

**审计发现 vs TODO 描述差异：**
- §三-3 "最多 4 次检查" 实际审计为 **最坏 28 次**
- §二-3 "IOHandler/AJAXUtil 不匹配" 实际已能匹配，残存 gap 是 `DbUtil`/snake_case
- §三-1 `claim()/remaining()` 在生产中 **从未被调用**

---

## Fix 1 — classify LLM 回退路径接入 module_summaries [P1]

**文件**: `wiki/nodes/classify.py`  
**问题**: `classify_domains_node` 调用 `CrossRepoBusinessDomainPlanner.classify()` 时不传 `enriched_signals`。planner 只读图节点 `business_summary` + `docstring`，而 pipeline state 中已有 `module_summaries`（含 summary_text、key_methods、dependencies、callers）。

**修复**:

在 `classify_domains_node` 内，调用 `planner.classify()` 前构建 `enriched_signals` 字典：

```python
module_summaries = state.get("module_summaries", {})
enriched_signals = {}
for repo, nodes in planner_modules.items():
    for n in nodes:
        name = str(n.properties.get("name", ""))
        if name in module_summaries:
            enriched_signals[(repo, name)] = module_summaries[name]

await planner.classify(..., enriched_signals=enriched_signals)
```

**约束**:
- 仅影响 LLM 回退路径（无 graph_store 时）
- 图路径（`graph_domain_decompose_node`）已独立消费 `module_summaries`

**测试**: Mock planner 验证 `enriched_signals` 参数非空且包含 summaries。

---

## Fix 2 — TF-IDF fallback 复用 build_embedding_texts [P2]

**文件**: `wiki/nodes/graph_domain_decompose.py`  
**问题**: `_tfidf_fallback_clustering()` 仅用 `f"{name} {path}"` 做 char n-gram，丢弃 summary/methods/deps 信号。

**修复**:

```python
def _tfidf_fallback_clustering(
    biz_modules, module_paths, edges, module_summaries_raw=None,
):
    texts = DomainSemanticClusterer.build_embedding_texts(
        biz_modules, module_summaries_raw or {}, module_paths,
    )
    if not texts or len(texts) != len(biz_modules):
        texts = [f"{name} {module_paths.get(name, '')}" for _, name in biz_modules]
    # ... 后续 TfidfVectorizer 不变
```

**约束**:
- 需要在函数签名中新增 `module_summaries_raw` 参数
- 调用方 `_embedding_clustering` 已持有此数据，只需传递

**测试**: 验证 TF-IDF 路径调用 `build_embedding_texts`；验证空 summaries 时降级到 name+path。

---

## Fix 3 — 前缀正则扩展 + snake_case + 可配置阈值 [P3]

**文件**: `wiki/nodes/classify.py`, `core/config.py`  
**问题**: 正则 `[A-Z][a-z]{2,}` 不匹配 2 字符 PascalCase（`DbUtil`），不处理 snake_case（`user_service`）。合并阈值硬编码。

**修复**:

1. 正则改为 `[A-Z][a-z]+`（去掉 `{2,}` 最小长度限制）
2. 新增 snake_case 处理函数 `_extract_prefix(name)`:
   - `_` 分割取第一段 → capitalize
   - PascalCase 走正则
3. 合并阈值可配置:
   ```python
   # core/config.py AppWikiFlags:
   consolidation_min_count: int = Field(default=3, ge=2)
   consolidation_min_domains: int = Field(default=2, ge=2)
   ```
4. **不**将 `Db`/`Io` 加入 `_GENERIC_PREFIXES`（它们是有意义的业务前缀，应允许合并）

**测试**: 验证 `DbUtil`→`Db`、`IoHandler`→`Io`、`user_service`→`User`、黑名单前缀（`Base`/`Common`）仍被阻止、配置化阈值生效。

---

## Fix 4 — Token 预算跨组件协调 [P2]

**文件**: `wiki/pipeline_graph.py`, `wiki/nodes/aggregate.py`, `wiki/nodes/compose.py`, `wiki/token_budget.py`  
**问题**: `WikiService._budget_resolver` 未穿透到 pipeline；各 node 各自新建默认 resolver；`claim()/remaining()` 生产未调用；snippet 线性公式 55+ 模块撞顶。

**修复 (3 步)**:

**Step 1 — Pipeline configurable 注入 resolver:**
```python
# wiki/pipeline_graph.py run_pipeline():
config = RunnableConfig(configurable={
    ...,
    "budget_resolver": wiki_service._budget_resolver,
})

# 各 node:
budget_resolver = config.get("configurable", {}).get(
    "budget_resolver", TokenBudgetResolver()
)
```

受影响 node: `aggregate.py`, `compose.py`, `heal.py`

**Step 2 — snippet 选择使用 `claim()`:**
```python
# wiki/nodes/aggregate.py:
snippet_budget = budget_resolver.claim("snippets", budget_calc.budget_for_snippets(n))
```

**Step 3 — Snippet 公式改为对数增长:**
```python
def budget_for_snippets(self, module_count: int) -> int:
    import math
    return min(500 + int(300 * math.log2(max(module_count, 1) + 1)), 8000)
```

| 模块数 | 旧公式 | 新公式 |
|--------|--------|--------|
| 5 | 1000 | 1275 |
| 20 | 2500 | 1832 |
| 55 | 6000 | 2249 |
| 100 | 6000 | 2501 |

**测试**: 验证 pipeline resolver 非默认；验证 `claim()` 减少 remaining；验证公式边界值。

---

## Fix 5 — Cypher 复合键过滤 [P3]

**文件**: `wiki/graph_call_query.py`  
**问题**: Cypher `WHERE m1.name IN $valid_names` 不含 repo 维度，同名跨仓库模块产生虚假边（由 Python 侧后过滤修正）。

**修复**:

```python
valid_pairs = [f"{repo}|{name}" for repo, name in valid_modules]
repos_only = list({repo for repo, _ in valid_modules})

_MODULE_CALLS_CYPHER = (
    "MATCH (m1:Module)-[:CONTAINS*1..2]->(f1)"
    "-[:CALLS]->(f2)<-[:CONTAINS*1..2]-(m2:Module) "
    "WHERE (m1.repository + '|' + m1.name) IN $valid_pairs "
    "AND (m2.repository + '|' + m2.name) IN $valid_pairs "
    "AND m1 <> m2 "
    "RETURN ..."
)
```

保留 Python 侧 `if source_node not in valid_modules` 作为安全网。

**测试**: Mock graph_store 验证新参数；同名跨仓库模块不再产生虚假边。

---

## Fix 6 — Quality/Heal 结构检查去重 [P3]

**文件**: `wiki/nodes/heal.py`  
**问题**: 单页最坏 28 次 `structural_check`。冗余源：`_page_passes_post_heal` 不读缓存、`bench_score` 内嵌检查不复用。

**修复 (3 步)**:

**Fix 6a — `_page_passes_post_heal` 读 `_structural_check_cache`:**
```python
def _page_passes_post_heal(page, evaluator, threshold, check_cache):
    content_hash = hashlib.md5(page.content.encode()).hexdigest()
    cached = check_cache.get(page.path)
    if cached and cached.get("content_hash") == content_hash:
        l1 = cached["score"]
    else:
        l1 = evaluator.structural_check(page)
        check_cache[page.path] = {"score": dict(l1), "content_hash": content_hash}
    return l1.get("total", 0) >= threshold
```

**Fix 6b — `_update_heal_hint` 写入缓存供下游复用:**
```python
def _update_heal_hint(page, evaluator, ..., check_cache):
    bench = evaluator.bench_score(page)
    content_hash = hashlib.md5(page.content.encode()).hexdigest()
    check_cache[page.path] = {
        "score": dict(bench.structure), "content_hash": content_hash,
    }
    return bench
```

**Fix 6c — `_bounded_heal` 复用 bench 结果判断通过:**
```python
bench = _update_heal_hint(page, ...)
if bench.structure.get("total", 0) >= threshold:
    break  # 已通过，跳过 _page_passes_post_heal
```

**预期收益**: 每 heal 轮次从 3 次降至 1 次 `structural_check`；典型 2-pass 循环从 ~10 次降至 ~4 次。

**测试**: 验证缓存命中跳过检查；验证 bench.structure 复用；验证 content 变更后缓存失效。

---

## 实施建议

| Batch | Fix 项 | 预估改动行 | 依赖 |
|-------|--------|-----------|------|
| C (域分类) | Fix 1, 2, 3 | ~30 行 | 无 |
| D (管线性能) | Fix 4, 5, 6 | ~60 行 | 无 |

两个 Batch 无互相依赖，可并行实施。建议优先 Batch C（P1 项在内）。

---

## Understand-Anything 对比总结

| UA 特性 | 本项目现状 | 可借鉴方向（不在本 spec 范围） |
|---------|----------|---------------------------|
| 40+ LanguageConfig | 8 语言 Tree-sitter | TODO FEAT-3 |
| FrameworkRegistry (10+) | 无 | 未来域分类增强信号源 |
| 4 层 Graph Schema 容错 | 基本验证 | 未来 LLM 输出鲁棒性 |
| domain-analyzer Agent | pipeline node | TODO FEAT-2 |
| Heuristic + LLM 双层 layer detection | 多信号投票 | 已有类似能力 |
| Content hash 增量指纹 | Git-diff based | 可互补（不在本 spec）|

---

*本文档作为 §二 + §三 的统一修复设计规格。实施计划由 writing-plans 生成。*
