# 搜索质量与用户体验增强提案

| 元信息 | 值 |
|---------|------|
| **提案编号** | PROPOSAL_20260418_195157 |
| **状态** | `[Completed]` — P1 + P2 + P3 全部完成 |
| **前置依赖** | P3 已完成 (PROPOSAL_20260418_175423) |
| **竞品参考** | [tobi/qmd](https://github.com/tobi/qmd), [deepwiki-open](https://github.com/AsyncFuncAI/deepwiki-open) |
| **执行方法论** | TDD + Subagent 并行 |

---

## 1. 背景

### 1.1 竞品分析发现

对 KBS 与 `tobi/qmd`、`deepwiki-open` 进行深度对比后，发现以下改进机会：

| 发现 | 来源 | 严重度 |
|------|------|--------|
| KB hybrid search 的融合算法（简单 dedup + score sort）落后于 Wiki search 已有的 RRF 算法 | 内部代码审计 | 高 |
| Reranker 启用时完全替换原始排序，可能破坏高置信度精确匹配 | qmd position-aware blending 设计 | 中 |
| Deep Search 无流式返回，多轮 LLM 调用期间用户无进度反馈 | deepwiki-open DeepResearch UI | 高 |
| code_snippet 截断到 1000 chars，长函数丢失尾部信息 | qmd AST-aware chunking | 中 |
| Ask 功能被嵌套在 Wiki 页面内部，发现性低 | dashboard 审查 | 低 |

### 1.2 现状架构

```
当前搜索链路:
                                
KB Hybrid (/hybrid):                        Wiki Search (/wiki/search):
  keyword_search → dedup                      graph → RRF(k=60, w=2.0)
  semantic_search → dedup                     vector → RRF(k=60, w=1.0)
  _fuse_results: keyword优先,                 FTS    → RRF(k=60, w=1.5)
    按 raw score sort                          + top-rank bonus
  [可选] reranker: 纯替换                     [无 reranker]
  → graph expansion                           → 结果
```

**核心问题**：KB hybrid 的融合 (`_fuse_results`) 将不同尺度的 score 直接比较（keyword score ≈ 1.0 vs semantic score ∈ [0,1]），且项目内已有更优的 RRF 实现（在 `wiki/search.py` 中）但未被复用。

### 1.3 Ask vs Deep Search 定位

| 维度 | Wiki Ask (v2) | Deep Search |
|------|:-------------|:------------|
| **入口** | Wiki 页面内嵌 AskPanel | Search 页面 Deep tab |
| **检索范围** | WikiPage nodes (RRF 融合) | 全 KB 实体 (简单融合) |
| **LLM 策略** | 1 次 complete + 图增强上下文 | 多轮 plan→execute→synthesize |
| **输出** | 流式回答 + sources | Markdown analysis + code_locations + trace |
| **会话** | 支持 conversation thread | 单次无状态 |

**结论**：两者互补不重复。Ask = 快速 Wiki Q&A；Deep Search = 复杂多轮研究。

---

## 2. 目标

1. **统一检索融合算法**：KB hybrid search 与 Wiki search 共用 RRF，提升检索质量
2. **优化 reranker 集成**：引入 position-aware blending，保护精确匹配
3. **Deep Search 流式化**：SSE 实时推送研究阶段，可视化进度
4. **Ask + Deep Research 融合**：Wiki AskPanel 支持 Deep Research toggle
5. **嵌入质量优化**：智能截断 + Document smart chunking
6. **图扩展 Query Expansion**：将 Wiki 的图邻居扩展能力上提到 KB 检索层

---

## 3. 设计方案

### 3.1 P1 — 搜索质量核心升级

#### 3.1.1 公共 RRF 工具模块

**新建** `search/fusion.py`，抽取 `wiki/search.py` 中已验证的 RRF 算法：

```python
# search/fusion.py
def rrf_fusion(
    ranked_lists: list[list[tuple[str, float]]],
    weights: list[float],
    k: int = 60,
) -> list[tuple[str, float]]:
    """Weighted Reciprocal Rank Fusion with top-rank bonus.
    
    Args:
        ranked_lists: Each list is [(doc_id, original_score), ...] in rank order.
        weights: Per-list weight multiplier.
        k: RRF constant (default 60, per standard RRF literature).
    """
    scores: dict[str, float] = {}
    best_rank: dict[str, int] = {}

    for li, ranked in enumerate(ranked_lists):
        w = weights[li] if li < len(weights) else 1.0
        for rank, (doc_id, _) in enumerate(ranked):
            contrib = w * (1.0 / (k + rank + 1))
            scores[doc_id] = scores.get(doc_id, 0.0) + contrib
            prev = best_rank.get(doc_id)
            if prev is None or rank < prev:
                best_rank[doc_id] = rank

    for doc_id, br in best_rank.items():
        if br == 0:
            scores[doc_id] += 0.05
        elif br in (1, 2):
            scores[doc_id] += 0.02

    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


def _min_max_normalize(scores: list[float]) -> list[float]:
    """Normalize scores to [0, 1] using min-max scaling."""
    if not scores:
        return []
    lo, hi = min(scores), max(scores)
    if hi - lo < 1e-9:
        return [1.0] * len(scores)
    return [(s - lo) / (hi - lo) for s in scores]


def position_aware_blend(
    rrf_scores: list[tuple[str, float]],
    reranker_scores: dict[str, float],
    top_k: int = 10,
) -> list[tuple[str, float]]:
    """Blend RRF and reranker scores with position-aware weights.
    
    Inspired by qmd: top ranks trust retrieval more, lower ranks trust reranker.
    
    IMPORTANT: RRF scores (~0.001-0.05) and reranker scores (model-dependent)
    are on different scales. Both are min-max normalized to [0,1] before blending.
    """
    # Normalize RRF scores
    rrf_vals = [s for _, s in rrf_scores]
    rrf_norm = _min_max_normalize(rrf_vals)
    
    # Normalize reranker scores
    re_vals = list(reranker_scores.values())
    re_norm_map: dict[str, float] = {}
    if re_vals:
        re_normed = _min_max_normalize(re_vals)
        re_keys = list(reranker_scores.keys())
        re_norm_map = dict(zip(re_keys, re_normed))
    
    blended: list[tuple[str, float]] = []
    for rank, ((doc_id, _), norm_rrf) in enumerate(zip(rrf_scores, rrf_norm)):
        norm_re = re_norm_map.get(doc_id, 0.0)
        if rank < 3:
            final = 0.75 * norm_rrf + 0.25 * norm_re
        elif rank < 10:
            final = 0.60 * norm_rrf + 0.40 * norm_re
        else:
            final = 0.40 * norm_rrf + 0.60 * norm_re
        blended.append((doc_id, final))
    blended.sort(key=lambda x: x[1], reverse=True)
    return blended[:top_k]
```

#### 3.1.2 HybridQueryService 改造

替换 `_fuse_results` 使用 RRF：

```python
# query/hybrid_query.py — 改造后

from search.fusion import rrf_fusion, position_aware_blend

async def search_with_context(self, query_text, k=5, ...):
    # ... (keyword + semantic 并行检索，不变)
    
    # 构造 ranked lists
    kw_ranked = [(self._doc_key(h), i) for i, h in enumerate(keyword_hits)]
    sem_ranked = [(self._doc_key(m), i) for i, m in enumerate(semantic_result.matches)]
    
    # RRF 融合 (keyword ×1.5, semantic ×1.0)
    candidate_k = k * 3 if self._reranker else k
    fused = rrf_fusion([kw_ranked, sem_ranked], [1.5, 1.0])[:candidate_k]
    
    # 还原为 match dict list
    doc_map = {self._doc_key(h): h for h in keyword_hits}
    doc_map.update({self._doc_key(m): m for m in semantic_result.matches})
    merged = [doc_map[doc_id] for doc_id, _ in fused if doc_id in doc_map]
    
    if self._reranker:
        # Rerank 获取 scores
        reranked = await self._reranker.rerank_with_scores(query_text, merged, top_k=k)
        re_scores = {self._doc_key(m): s for m, s in reranked}
        # Position-aware blending
        final_fused = position_aware_blend(fused[:len(merged)], re_scores, top_k=k)
        merged = [doc_map[doc_id] for doc_id, _ in final_fused if doc_id in doc_map]
    else:
        merged = merged[:k]
    
    # ... (graph expansion，不变)
```

**关键改动**：
- `Reranker.rerank` 新增 `rerank_with_scores` 方法，返回 `list[tuple[dict, float]]` 而非仅排序后的 list
- `WikiSearchService.rrf_fusion` 改为调用 `search.fusion.rrf_fusion`
- `_fuse_results` 静态方法标记为 deprecated
- `doc_key` 格式定义为 `f"{name}:{file}:{line}"`，与现有 `_fuse_results` 的 dedup key 一致
- `position_aware_blend` 内部对 RRF score 和 reranker score **分别** 做 min-max normalization 到 [0,1] 后再加权混合，避免不同尺度 score 直接比较的问题

#### 3.1.3 测试清单

- [ ] `tests/search/test_fusion.py` — rrf_fusion 单元测试
  - [ ] 空列表
  - [ ] 单列表
  - [ ] 多列表不同权重
  - [ ] top-rank bonus 验证
  - [ ] 大 k 值边界
- [ ] `tests/search/test_position_aware_blend.py` — blending 单元测试
  - [ ] rank 1-3 权重验证
  - [ ] rank 4-10 权重验证
  - [ ] rank 11+ 权重验证
  - [ ] reranker score 缺失时降级
- [ ] `tests/query/test_hybrid_query_rrf.py` — 集成测试
  - [ ] keyword + semantic RRF 融合
  - [ ] 带 reranker 的 position-aware blending
  - [ ] 不带 reranker 的纯 RRF 排序
  - [ ] 与旧 `_fuse_results` 结果对比（回归验证）
- [ ] `tests/wiki/test_search_rrf_shared.py` — Wiki search 改用公共 RRF 后无回归
  - [ ] hybrid mode 结果不变
  - [ ] graph/semantic/keyword 单模式结果不变

---

### 3.2 P2 — Deep Research UX 升级

#### 3.2.1 后端 SSE 流式化

新增 `POST /api/v1/deep-search/stream` 端点：

```python
# api/routes/search_routes.py (新建或追加到 main.py)

@viewer_router.post("/deep-search/stream")
async def deep_search_stream(req: DeepSearchRequest, ...):
    async def event_generator():
        async for event in engine.search_stream(req.query, ...):
            yield f"event: {event['type']}\ndata: {json.dumps(event['data'])}\n\n"
    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

`DeepSearchEngine.search_stream` 改造：

```python
async def search_stream(self, query, *, max_iterations=3, ...):
    try:
        plan = await self._plan_search(query, ...)
        yield {"type": "plan", "data": plan}
    except Exception as exc:
        yield {"type": "error", "data": {"phase": "plan", "message": str(exc)}}
        return  # 致命错误，终止流
    
    all_results = []
    for iteration in range(max_iterations):
        sub_queries = ...
        for sq in sub_queries:
            yield {"type": "progress", "data": {"iteration": iteration, "query": sq}}
        
        try:
            results = await self._execute_sub_queries(sub_queries)
            all_results.extend(results)
            yield {"type": "search_done", "data": {"iteration": iteration, "count": len(results)}}
        except Exception as exc:
            yield {"type": "error", "data": {"phase": "search", "iteration": iteration, "message": str(exc)}}
            continue  # 非致命：跳过本轮检索，尝试合成已有结果
        
        try:
            synthesis = await self._synthesize(query, all_results, ...)
            yield {"type": "synthesis", "data": {
                "iteration": iteration,
                "sufficient": synthesis.get("sufficient"),
                "partial_analysis": synthesis.get("analysis", "")[:500],
            }}
        except Exception as exc:
            yield {"type": "error", "data": {"phase": "synthesis", "iteration": iteration, "message": str(exc)}}
            break  # LLM 合成失败，终止
        
        if synthesis.get("sufficient"):
            break
    
    yield {"type": "conclusion", "data": synthesis}
```

**SSE 异常处理策略**：
- `plan` 阶段失败 → yield error event + **终止流**（无法继续）
- `search` 阶段失败 → yield error event + **跳过本轮**（尝试合成已有结果）
- `synthesis` 阶段失败 → yield error event + **终止流**（LLM 不可用）

#### 3.2.2 前端阶段可视化

新建 `dashboard/src/components/DeepResearchTimeline.tsx`：

```typescript
type Stage = {
  type: "plan" | "progress" | "search_done" | "synthesis" | "conclusion";
  data: Record<string, unknown>;
  status: "done" | "active" | "pending";
};

function DeepResearchTimeline({ stages }: { stages: Stage[] }) {
  return (
    <ol className="space-y-3">
      {stages.map((s, i) => (
        <li key={i} className={`flex items-start gap-3 rounded-lg border p-3 ${
          s.status === "done" ? "border-green-200 bg-green-50/40" :
          s.status === "active" ? "border-amber-200 bg-amber-50/40 animate-pulse" :
          "border-gray-100 bg-gray-50/40 opacity-50"
        }`}>
          <StatusIcon status={s.status} />
          <StageContent stage={s} />
        </li>
      ))}
    </ol>
  );
}
```

#### 3.2.3 Wiki AskPanel Deep Research Toggle

在 `AskPanel` 中添加模式切换：

```typescript
const [mode, setMode] = useState<"ask" | "deep">("ask");
// ...
<div className="flex gap-2">
  <button onClick={() => setMode("ask")} className={...}>
    Quick Ask
  </button>
  <button onClick={() => setMode("deep")} className={...}>
    Deep Research
  </button>
</div>
```

Deep Research 模式下，调用 `/deep-search/stream` 并通过 `DeepResearchTimeline` 展示阶段。

**Scope 说明**：Deep Research 模式的检索范围为**全 KB 实体**（不限于 Wiki 页面），因为用户在 Wiki 内提出复杂问题时往往需要更广泛的代码知识。UI 上明确标注"Deep Research 搜索范围为全仓库"以避免用户困惑。

#### 3.2.4 测试清单

- [ ] `tests/api/test_deep_search_stream.py` — SSE 端点测试
  - [ ] 正常流式返回所有事件类型
  - [ ] plan 事件先于 progress
  - [ ] conclusion 事件为最后一个
  - [ ] 异常处理（LLM 失败时返回 error 事件）
- [ ] `tests/query/test_deep_search_stream.py` — search_stream 单元测试
  - [ ] 迭代次数控制
  - [ ] sufficient=true 时提前终止
  - [ ] yield 事件顺序正确
- [ ] `dashboard/src/components/__tests__/DeepResearchTimeline.test.tsx`
  - [ ] 各阶段渲染正确
  - [ ] active 状态动画
  - [ ] conclusion 展示完整分析

---

### 3.3 P3 — 嵌入质量优化

#### 3.3.1 智能截断

修改 `indexer/incremental_indexer.py` 和 `embedding/embedding_generator.py`：

```python
# embedding/embedding_generator.py

MAX_CODE_SNIPPET_CHARS = 3000  # 从 1000 提升到 3000

def _smart_truncate(code: str, max_chars: int = MAX_CODE_SNIPPET_CHARS) -> str:
    """Truncate at the nearest statement boundary instead of hard cut."""
    if len(code) <= max_chars:
        return code
    # 在 max_chars 前 200 chars 的窗口内找最佳断点
    window_start = max(0, max_chars - 200)
    window = code[window_start:max_chars]
    # 优先级: 空行 > 语句结尾 (;/\n) > 任意换行
    for pattern in ["\n\n", ";\n", "\n"]:
        idx = window.rfind(pattern)
        if idx >= 0:
            return code[:window_start + idx + len(pattern)]
    return code[:max_chars]
```

#### 3.3.2 Document Smart Chunking

借鉴 qmd 的 break-point scoring：

```python
# embedding/smart_chunker.py

BREAK_SCORES = {
    "h1": 100, "h2": 90, "h3": 80, "h4": 70,
    "code_fence": 80, "hr": 60, "blank_line": 20,
    "list_item": 5, "line_break": 1,
}

TARGET_TOKENS = 900
OVERLAP_RATIO = 0.15

def smart_chunk_markdown(text: str) -> list[str]:
    """Chunk markdown with smart break-point scoring and overlap."""
    ...
```

**重要**：多 chunk 去重策略 — Document smart chunking 会为同一文档产生多个 chunk embedding。搜索时需要对同一文档的多个 chunk **按 doc_id 去重，取最高 score**，避免同一文档占据过多 top-k 位置。实现方式：在 `SemanticQueryService.search_all` 返回结果中增加 `doc_id` 字段，并在 `_fuse_results` / `rrf_fusion` 前做 per-doc max-score dedup。

#### 3.3.3 图扩展 Query Expansion

将 `WikiSearchService.expand_query_with_graph` 上提到 `HybridQueryService`：

```python
# query/hybrid_query.py

async def search_with_context(self, query_text, k=5, ...):
    # 新增: query expansion via graph neighbors
    expansion_list = await self._expand_query_with_graph(query_text)
    
    # 对每个扩展查询并行执行 keyword + semantic
    all_kw_ranked = []
    all_sem_ranked = []
    for i, expanded_query in enumerate(expansion_list):
        kw, sem = await asyncio.gather(
            self._keyword_search_multi(identifiers, k),
            self._semantic.search_all(expanded_query, k)
        )
        weight = 2.0 if i == 0 else 1.0  # 原始查询权重 ×2
        all_kw_ranked.append((kw, weight))
        all_sem_ranked.append((sem, weight))
    
    # 多路 RRF 融合
    ...
```

**配置项**：Query Expansion 通过配置项 `hybrid.query_expansion_enabled` (默认 `True`) 控制，允许用户关闭以减少延迟。关闭时退化为当前的单查询行为。
```

#### 3.3.4 测试清单

- [ ] `tests/embedding/test_smart_truncate.py`
  - [ ] 短代码不截断
  - [ ] 长代码在语句边界截断
  - [ ] 无合适断点时硬截
- [ ] `tests/embedding/test_smart_chunker.py`
  - [ ] Markdown 按 heading 分块
  - [ ] chunk 大小约 900 tokens
  - [ ] 重叠 15%
  - [ ] 代码块不拆分
- [ ] `tests/query/test_hybrid_query_expansion.py`
  - [ ] 图扩展生成 expanded queries
  - [ ] 原始查询权重 ×2
  - [ ] 多路 RRF 融合结果正确

---

## 4. 实施计划

### 4.1 执行方法论

每个 Phase 采用 **TDD + Subagent 并行执行**。TDD 流程：先由 subagent 编写测试（Red），然后实现代码使测试通过（Green），最后 Code Review。

### 4.2 Phase 分解与 Subagent 编排

#### P1 — 搜索质量核心升级

```
Step 1: Subagent P1-A (可先行启动，无依赖)
  责任: search/fusion.py + tests/search/test_fusion.py
  内容: rrf_fusion + _min_max_normalize + position_aware_blend
  特点: 纯工具函数，无外部依赖

Step 2: Subagent P1-B + P1-C (并行，依赖 P1-A)
  P1-B: Reranker 改造
    - Reranker.rerank_with_scores 方法
    - 集成 position_aware_blend
    - tests/query/test_reranker_blend.py
  P1-C: HybridQueryService + WikiSearchService 迁移
    - _fuse_results → rrf_fusion
    - WikiSearchService.rrf_fusion → search.fusion.rrf_fusion
    - tests/query/test_hybrid_query_rrf.py
    - tests/wiki/test_search_rrf_shared.py (回归)

Step 3: Code Review Subagent
```

#### P2 — Deep Research UX 升级

```
Step 1: Subagent P2-A + P2-B (并行启动)
  P2-A: 后端 SSE
    - DeepSearchEngine.search_stream
    - POST /deep-search/stream 端点
    - SSE 异常处理
    - tests/api/test_deep_search_stream.py
  P2-B: 前端组件 (用 mock SSE 数据先行)
    - DeepResearchTimeline.tsx
    - DeepSearchSection.tsx 改造
    - AskPanel.tsx Deep Research toggle

Step 2: P2-B 集成真实 SSE (依赖 P2-A)

Step 3: Code Review Subagent
```

#### P3 — 嵌入质量优化

```
Step 1: Subagent P3-A + P3-B + P3-C (三者独立，并行启动)
  P3-A: 智能截断
    - _smart_truncate in embedding_generator.py
    - MAX_CODE_SNIPPET_CHARS → 3000
    - tests/embedding/test_smart_truncate.py
  P3-B: Document smart chunking
    - embedding/smart_chunker.py
    - per-doc max-score dedup 逻辑
    - tests/embedding/test_smart_chunker.py
  P3-C: 图扩展 Query Expansion
    - HybridQueryService._expand_query_with_graph
    - 配置项 hybrid.query_expansion_enabled
    - tests/query/test_hybrid_query_expansion.py

Step 2: Code Review Subagent
```

| Phase | 内容 | Subagent 数量 | 依赖 |
|-------|------|:------------:|------|
| **P1** | RRF + blending | 3 (P1-A → P1-B ∥ P1-C) | 无 |
| **P2** | Deep Research UX | 2 (P2-A ∥ P2-B → 集成) | P1 (可选) |
| **P3** | 嵌入 + 扩展 | 3 (P3-A ∥ P3-B ∥ P3-C) | P1 |

### 4.3 文件变更预估

| Phase | 新增文件 | 修改文件 |
|-------|---------|---------|
| P1 | `search/fusion.py`, `tests/search/test_fusion.py`, `tests/search/test_position_aware_blend.py`, `tests/query/test_hybrid_query_rrf.py` | `query/hybrid_query.py`, `query/reranker.py`, `wiki/search.py` |
| P2 | `dashboard/src/components/DeepResearchTimeline.tsx`, `tests/api/test_deep_search_stream.py` | `query/deep_search.py`, `main.py`, `dashboard/src/components/DeepSearchSection.tsx`, `dashboard/src/components/wiki/AskPanel.tsx`, `dashboard/src/api/hooks.ts` |
| P3 | `embedding/smart_chunker.py`, `tests/embedding/test_smart_chunker.py`, `tests/embedding/test_smart_truncate.py` | `embedding/embedding_generator.py`, `indexer/incremental_indexer.py`, `query/hybrid_query.py` |

---

## 5. 风险评估

| 风险 | 等级 | 缓解 |
|------|------|------|
| RRF 替换可能导致搜索结果排序变化 | 中 | 增加回归测试，对比新旧算法在相同查询下的 top-10 |
| Deep Search SSE 需要改造 engine 为异步生成器 | 低 | 保留原同步 API 不变，新增 stream 端点 |
| 智能截断可能改变已有 embedding | 中 | 仅对新索引生效，提供 `--reindex` 选项 |
| position-aware blending 需要 reranker 返回 scores | 低 | `Reranker` 已有 `_compute_scores`，仅需暴露接口 |

---

## 6. 验收标准

- [ ] **P1**: `/hybrid` 使用 RRF 融合，reranker 使用 position-aware blending，所有新旧测试通过
- [ ] **P2**: `/deep-search/stream` SSE 正常工作，前端展示研究阶段，AskPanel 支持 Deep Research toggle
- [ ] **P3**: 长函数 embedding 信息更完整，Document 智能分块，Query Expansion 默认启用

---

---

## 7. Sequential-Thinking 审阅记录

审阅共发现 **6 个需要修正的问题**，均已在本提案中修正：

| # | 严重度 | 问题 | 修正 |
|---|:------:|------|------|
| 1 | **重要** | `position_aware_blend` 中 RRF score (~0.001-0.05) 与 reranker score (model-dependent) 尺度不同，直接加权不合理 | 新增 `_min_max_normalize`，两个 score 分别归一化到 [0,1] 后再混合 |
| 2 | **重要** | Document smart chunking 产生多个 chunk，同一文档可能占据多个 top-k 位 | 增加 per-doc max-score dedup 策略说明 |
| 3 | 中 | `doc_key` 格式未明确定义 | 明确为 `name:file:line`，与现有逻辑一致 |
| 4 | 中 | SSE 异常处理策略未明确 | 新增三阶段异常处理说明 (plan/search/synthesis) |
| 5 | 中 | AskPanel Deep Research 的 scope 未明确 | 明确采用全 KB scope + UI 标注 |
| 6 | 低 | Query Expansion 增加延迟 | 新增配置项 `hybrid.query_expansion_enabled` |

---

*提案由竞品分析驱动生成。核心思路：将 qmd 的精准融合 + DeepWiki 的研究 UX + KBS 自身的图智能三者融合，构建差异化竞争优势。*
