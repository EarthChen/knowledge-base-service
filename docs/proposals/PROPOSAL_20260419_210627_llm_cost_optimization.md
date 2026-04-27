# 提案：LLM 成本优化 — 分层延迟 Enrichment 策略

> **状态**: Approved  
> **创建时间**: 2026-04-19  
> **影响范围**: indexer/, wiki/, config.py

---

## 1. 背景与问题

### 1.1 当前 LLM 调用分布

系统在**索引阶段**存在三个 LLM 调用点：

| # | 调用点 | 触发时机 | 调用量（5000 实体仓库） | 用途 |
|---|--------|----------|------------------------|------|
| 1 | `CodeSummaryEnricher.enrich_batch` | 每次索引 | ~3000 次（trivial 过滤后） | 为 Function/Class 生成 `business_summary` |
| 2 | `BusinessFlowInferencer.infer_from_chain` | 每次索引（若启用） | ~50-200 次（入口函数数量） | 从调用链推理 BusinessFlow 节点 |
| 3 | BusinessConcept 提取 | — | 0（尚未实现） | Schema 已定义，提取器未实现 |

### 1.2 成本估算

以中等仓库（5000 实体，~3000 需 enrichment）为例：

| 模型 | 索引阶段 enrichment 成本 | BusinessFlow 成本 | 总计 |
|------|--------------------------|-------------------|------|
| GPT-4o-mini | ~$0.15 - $0.45 | ~$0.02 - $0.05 | ~$0.17 - $0.50 |
| GPT-4o | ~$2.50 - $7.50 | ~$0.25 - $1.00 | ~$2.75 - $8.50 |
| Claude Sonnet | ~$3.00 - $9.00 | ~$0.30 - $1.50 | ~$3.30 - $10.50 |

### 1.3 核心问题

**成本不在于单次金额，而在于触发频率与无效调用。**

1. **每次全量索引都会触发全部 enrichment**，开发/调试环境下可能频繁重建索引
2. **大量普通函数的 business_summary 价值有限**：getter/setter 已过滤，但仍有许多工具函数、内部辅助函数不需要精细的业务语义描述
3. **BusinessFlow 依赖 business_summary**，如果延迟 summary，BusinessFlow 推理质量会受影响
4. **Wiki 只生成一次（或很少重生）**，而索引可能多次触发

---

## 2. 设计目标

1. **索引阶段 LLM 调用量降低 80%+**，仅保留核心实体的即时 enrichment
2. **搜索质量不显著下降**：核心实体（入口点、控制器、服务类）保持高质量 embedding
3. **Wiki 生成时完成剩余 enrichment**，实现"按需触发"而非"预计算全量"
4. **向后兼容**：通过配置项支持回退到当前行为

---

## 3. 方案设计

### 3.1 架构总览

```
┌─────────────────────────────────────────────────────────────┐
│                        索引阶段                              │
│                                                             │
│  代码解析 → AST 建图 → 核心实体识别 → [仅核心实体] LLM enrich │
│                         │                                    │
│              普通实体 → docstring+code 直接 embedding         │
│                         ↓                                    │
│              图存储 (含 CALLS 边、结构信息)                    │
└────────────────────────┬────────────────────────────────────┘
                         │
                    用户触发 Wiki 生成
                         │
┌────────────────────────▼────────────────────────────────────┐
│                      Wiki 阶段                               │
│                                                             │
│  1. 批量 enrich 未处理实体 → 回填 business_summary            │
│  2. 入口点发现 → 调用链推理 → 创建 BusinessFlow 节点          │
│  3. Wiki 页面生成 (Tier 1/2/3)                               │
│  4. 增量 embedding 刷新 (仅新获得 summary 的实体)             │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 核心实体识别规则

新增 `EnrichmentPriorityClassifier`，判断实体是否为"核心实体"（索引时立即 enrich）：

```python
class EnrichmentPriorityClassifier:
    """判定哪些代码实体值得在索引阶段消耗 LLM 资源。"""

    CORE_CLASS_SUFFIXES = (
        "Controller", "Service", "Handler", "Manager",
        "Repository", "Dao", "Gateway", "Facade",
        "Processor", "Listener", "Consumer", "Producer",
    )

    def is_core_entity(self, item: dict) -> bool:
        """核心实体 = 入口点 / 业务类 / 复杂函数。"""
        # 1. 有语义角色标注（http_endpoint, rpc_consumer 等）
        if item.get("semantic_roles"):
            return True
        # 2. 类名匹配业务模式
        name = item.get("name", "")
        if any(name.endswith(s) for s in self.CORE_CLASS_SUFFIXES):
            return True
        # 3. 代码行数超过阈值（复杂函数）
        code = item.get("code_snippet", "")
        if len(code.splitlines()) > 30:
            return True
        return False
```

**估算**：典型仓库 5000 实体 → trivial 过滤后 3000 → 核心实体约 300-500（约 10-15%）

### 3.3 索引阶段改造

修改 `incremental_indexer.py` 的 `_embed_and_store_nodes`：

```python
# 当前逻辑（全量 enrich）
if not skip_enrich and self._enricher:
    code_nodes = [n for n in embeddable if n.label in (FUNCTION, CLASS)]
    items = [build_enrich_item(n) for n in code_nodes]
    summaries = await self._enricher.enrich_batch(items)
    ...

# 优化后（分层 enrich）
if not skip_enrich and self._enricher:
    strategy = get_settings().llm.enrichment_strategy

    if strategy == "disabled":
        pass  # 跳过索引阶段 enrichment，全部延迟到 Wiki 阶段
    elif strategy == "core_only":
        code_nodes = [n for n in embeddable if n.label in (FUNCTION, CLASS)]
        items = [build_enrich_item(n) for n in code_nodes]
        core_mask = [classifier.is_core_entity(it) for it in items]
        core_items = [it for it, m in zip(items, core_mask) if m]
        summaries = await self._enricher.enrich_batch(core_items)
        # 仅回填核心实体的 summary
        core_idx = 0
        for node, is_core in zip(code_nodes, core_mask):
            if is_core and core_idx < len(summaries) and summaries[core_idx]:
                node.properties["business_summary"] = summaries[core_idx]
                ...
            core_idx += int(is_core)
```

### 3.4 配置项

```yaml
llm:
  # enrichment 策略:
  #   "disabled"  — 完全禁用索引阶段 enrichment（默认值，所有 enrichment 延迟到 Wiki 阶段）
  #   "core_only" — 仅核心实体在索引时 enrich（生产环境备选，节省 ~85% LLM 调用）
  enrichment_strategy: "disabled"  # 默认值

  # business_flow_enabled 保持不变，但执行时机从索引移到 Wiki
  business_flow_enabled: true
```

> **审阅决策**：移除 `all` 策略。原全量 enrich 行为可通过 Wiki 阶段的 DeferredEnrichmentService 完整覆盖，保留 `all` 增加配置复杂度且无独特价值。

### 3.5 Wiki 阶段事后 Enrichment

#### 3.5.1 批量 Enrich 未处理实体

Wiki 生成前，对缺少 `business_summary` 的实体批量补全：

```python
# wiki/deferred_enrichment.py
class DeferredEnrichmentService:
    """Wiki 生成时批量补全未 enrich 的实体。"""

    async def enrich_remaining(self, repository: str) -> int:
        """找到所有缺少 business_summary 的 Function/Class，批量 enrich。"""
        # 1. 查询图：WHERE n.business_summary IS NULL
        unenriched = await self._store.find_unenriched_entities(repository)
        # 2. 过滤 trivial
        items = [it for it in unenriched if not is_trivial_enrichment_entity(it)]
        # 3. 批量 LLM enrich
        summaries = await self._enricher.enrich_batch(items)
        # 4. 回填图节点
        for item, summary in zip(items, summaries):
            if summary:
                await self._store.update_node_property(
                    item["label"], item["uid"], "business_summary", summary
                )
        return len([s for s in summaries if s])
```

#### 3.5.2 Wiki Composer 事后回填

现有 `compose_page` 中的 Tier 2 LLM 生成已经在调用 LLM。优化点：从 Tier 2 的 LLM 响应中提取简短 summary 并回填：

```python
# 在 WikiComposer.compose_page 中
elif self._llm is not None:
    tier = 2
    description = await self._tier2_llm(...)
    # 新增：从 LLM 生成的描述中提取第一段作为 business_summary 回填
    if not page_data.business_summary:
        short_summary = _extract_short_summary(description, max_chars=100)
        if short_summary:
            await self._wiki_store.update_node_property(
                node.label, node.uid, "business_summary", short_summary
            )
```

#### 3.5.3 BusinessFlow 移入 Wiki 阶段

```python
# wiki/wiki_service.py 中新增
async def _generate_business_flows(self, repository: str) -> int:
    """Wiki 生成完成后，推理 BusinessFlow 节点。"""
    if not self._flow_inferencer or not self._flow_inferencer._business_flow_enabled:
        return 0
    # 此时图中已有完整的 CALLS 边 + 大部分 business_summary
    entry_points = await self._flow_inferencer.find_entry_points()
    created = 0
    for ep in entry_points:
        chain = await self._build_call_chain(ep)
        flow = await self._flow_inferencer.infer_from_chain(chain)
        if flow:
            await self._persist_flow(flow, repository)
            created += 1
    return created
```

#### 3.5.4 增量 Embedding 刷新

Wiki 完成后，对新获得 `business_summary` 的实体重新生成 embedding：

```python
async def refresh_embeddings_for_enriched(self, repository: str) -> int:
    """对新回填了 business_summary 的实体重新计算 embedding。"""
    # 查询: business_summary IS NOT NULL AND embedding_stale = true
    stale_nodes = await self._store.find_stale_embeddings(repository)
    items = [build_embedding_item(n) for n in stale_nodes]
    embeddings = await self._embedding.generate_for_code(items)
    for node, emb in zip(stale_nodes, embeddings):
        await self._store.set_node_embedding(node["uid"], node["label"], emb)
    return len(stale_nodes)
```

### 3.6 数据流对比

#### 当前流程

```
索引开始
  ├─ 解析代码 → AST 节点
  ├─ 全量 LLM enrich → business_summary (3000 次 LLM)
  ├─ 生成 embedding (含 business_summary)
  ├─ BusinessFlow 推理 (50-200 次 LLM)
  └─ 存储

Wiki 生成
  ├─ 读取 business_summary (Tier 1)
  ├─ 或 LLM 生成页面 (Tier 2)
  └─ 输出 WikiPage
```

#### 优化后流程

```
索引开始
  ├─ 解析代码 → AST 节点
  ├─ 核心实体 LLM enrich → business_summary (300-500 次 LLM)
  ├─ 普通实体 → docstring+code 直接 embedding
  └─ 存储（无 BusinessFlow）

Wiki 生成
  ├─ 批量 enrich 剩余实体 (2500 次 LLM，一次性)
  ├─ Tier 1/2/3 页面生成
  ├─ WikiComposer Tier 2 回填 short_summary
  ├─ BusinessFlow 推理 (50-200 次 LLM)
  ├─ 增量 embedding 刷新
  └─ 输出 WikiPage
```

---

## 4. 成本对比

### 4.1 重复索引场景（开发/调试，索引 5 次后生成 1 次 Wiki）

| 阶段 | 当前方案 | disabled（默认） | core_only |
|------|---------|-----------------|-----------|
| 索引 × 5 | 3000 × 5 = **15,000** | 0 × 5 = **0** | 500 × 5 = **2,500** |
| Wiki × 1 | ~0 | ~3,000 + 刷新 | ~2,500 + 刷新 |
| **总计** | **~15,000** | **~3,000（↓80%）** | **~5,000（↓67%）** |

### 4.2 正常使用场景（索引 1 次 + Wiki 1 次）

| 阶段 | 当前方案 | disabled（默认） | core_only |
|------|---------|-----------------|-----------|
| 索引 × 1 | 3000 | 0 | 500 |
| Wiki × 1 | ~0 | ~3,000 + 刷新 | ~2,500 + 刷新 |
| **总计** | **~3,000** | **~3,000（≈0%）** | **~3,000（≈0%）** |

### 4.3 多仓库场景（3 个仓库，各索引 3 次 + Wiki 1 次）

| 阶段 | 当前方案 | disabled（默认） | core_only |
|------|---------|-----------------|-----------|
| 索引 × 9 | 3000 × 9 = **27,000** | 0 × 9 = **0** | 500 × 9 = **4,500** |
| Wiki × 3 | ~0 | ~9,000 | ~7,500 |
| **总计** | **~27,000** | **~9,000（↓67%）** | **~12,000（↓56%）** |

---

## 5. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| Wiki 生成前搜索质量下降 | 普通函数的语义搜索精度略低 | 核心实体仍有高质量 embedding；docstring+code 的 embedding 质量也不差 |
| 首次 Wiki 生成变慢 | 需批量 enrich + embedding 刷新 | 可分批进行，显示进度；后续 Wiki 增量更新不受影响 |
| BusinessFlow 延迟可见 | 图谱查询中暂无 BusinessFlow | 用户仍可查看 CALLS 边结构；Wiki 生成后 BusinessFlow 自动出现 |
| 配置复杂度增加 | 新增 `enrichment_strategy` 配置 | 默认 `disabled`，用户无需改动；文档说明两种选项 |

---

## 6. 实施计划

### Sprint 1: 索引阶段 Enrichment 智能分级（P0 核心） ✅
- [x] 新增 `EnrichmentPriorityClassifier` 类
- [x] 修改 `incremental_indexer.py` 支持 `enrichment_strategy` 配置
- [x] `config.py` 新增 `enrichment_strategy` 配置项，默认 `disabled`
- [x] 编写测试：核心实体识别准确性、分级 enrichment 行为（5 tests）
- [x] 编写测试：`disabled` 模式跳过所有索引阶段 enrichment（2 tests）

### Sprint 2: Wiki 阶段事后 Enrichment（P1 补全） ✅
- [x] 新增 `wiki/deferred_enrichment.py`
- [x] 修改 `WikiComposer.compose_page` — Tier 2 回填 short_summary
- [x] `WikiService` 集成延迟 enrichment 流程
- [x] 增量 embedding 刷新逻辑
- [x] 编写测试：延迟 enrichment 流程、embedding 刷新（10 tests）

### Sprint 3: BusinessFlow 移入 Wiki 阶段（P1 补全） ✅
- [x] 将 `BusinessFlowInferencer` 集成到 `WikiService`
- [x] Wiki 生成时自动推理 BusinessFlow（在延迟 enrichment 之后、页面组合之前）
- [x] 编写测试：BusinessFlow 在 Wiki 阶段正确创建（5 tests）
- [x] 更新文档

---

## 7. 验收标准

> **验证说明（2026-04-27）**：以下条目中，与索引/Wiki 管线相关的行为由 `tests/test_indexer_enrichment_strategy.py`、`tests/wiki/test_deferred_enrichment.py`、BusinessFlow 与索引集成测试等覆盖；全量 **`uv run pytest` 通过（1722 passed）**。

- [x] `enrichment_strategy=disabled` 时，索引阶段零 LLM 调用（`test_disabled_strategy_skips_enrichment` 等）
- [x] `enrichment_strategy=core_only` 时，仅对分类为 *core* 的实体调用 `enrich_batch`（**调用比例依仓库与分类器而定**；单元测试验证过滤行为，不替代生产占比统计）
- [x] Wiki 阶段 **`DeferredEnrichmentService.enrich_remaining`** 对缺少 `business_summary` 的实体做批量补全，并**跳过 trivial**（见 `tests/wiki/test_deferred_enrichment.py`；「全量仓库每一个非 trivial 实体」级别的验收需依具体图数据做抽检）
- [x] Wiki 生成后，BusinessFlow 节点正确创建（`tests/wiki/test_wiki_business_flow.py` 等）
- [x] 新获得 business_summary 的实体 embedding 已刷新（延迟 enrichment / 刷新相关测试）
- [x] 所有现有测试通过（2026-04-27：`1722 passed`）
