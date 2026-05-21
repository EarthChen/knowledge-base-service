# 语义嵌入驱动的域分类设计

> 状态: 已审阅  
> 创建: 2026-05-21  
> 替代: `2026-05-21-domain-classification-accuracy-improvement.md`

---

## 1. 问题陈述

### 1.1 当前现象

```
域树示例:
- 好友关系 (0 modules, 7 children)
  - 亲密关系赠礼体系 (10)、私密圈运营 (12)、亲密等级生态 (7)
  - 私密圈商业运营 (13)、亲密度任务调度 (7)、亲密实时互动 (3)
  - 私密圈关系管理 (9)
- 家族核心运营 (0, 5 children)
- 用户资料整合 (0, 3 children)
- 私密好友圈 (12)          ← 与"好友关系/私密圈*"重叠
- 用户亲密度生态 (0, 5 children)  ← 与"好友关系/亲密*"重叠
  - 经销商生态集成     ← 与亲密度无关，错放
- 数据持久层 (1)           ← 技术名而非业务名
```

| 问题 | 表现 |
|------|------|
| 同义域分散 | "亲密"概念在 3 个顶级位置、"私密"在 2 个位置 |
| 错放 | "经销商生态集成"在"用户亲密度生态"下 |
| 域名不业务化 | "数据持久层"、"用户核心基础设施" |
| 子域碎片化 | "好友关系"拆出 7 个子域 |

### 1.2 根因链

| 优先级 | 根因 | 影响 |
|--------|------|------|
| **P0** | Louvain 按调用拓扑分组，非按业务语义 | 同一业务概念的模块因调用路径不同被拆到不同社区 |
| **P1** | LLM 命名只看类名，无路径/摘要/业务上下文 | 域名与真实业务不匹配 |
| **P2** | 每个社区独立命名，无全局一致性视角 | 同义域名重复 |
| **P3** | 子域拆分后独立命名，无父域约束 | 子域间语义重叠 |

### 1.3 关键发现

`compose_leaf_modules` 已为每个模块生成 200-500 字的业务摘要（`module_summaries`）：
- `summary_text`: 模块职责和核心业务逻辑描述
- `key_methods`: 最重要的 5 个方法
- `dependencies` / `callers`: 依赖和被调用关系

且 `compose_leaf_modules` 完全不依赖 `domain_mapping`。

项目已有成熟的 embedding 基础设施（`EmbeddingGenerator`），支持 ONNX、torch、HTTP 外部模型多种后端。

---

## 2. 方案比选

### 方案 A: 摘要增强的 Louvain（增量改进）

保持 Louvain 社区检测为主要分组机制，用模块摘要增强 LLM 命名。

| 维度 | 评价 |
|------|------|
| 准确性 | 中 — 命名改善但 P0 (拓扑≠语义) 未解决 |
| 稳定性 | 高 — Louvain 确定性 |
| 改动量 | 小 |

### 方案 B: LLM 驱动的全量域分类（激进方案）

取消 Louvain，所有模块分批送给 LLM 做域分配。

| 维度 | 评价 |
|------|------|
| 准确性 | 高 — 最接近人类专家 |
| 稳定性 | **低** — LLM 输出不确定性高 |
| 改动量 | 大 |

### 方案 C: 语义嵌入聚类 + LLM 精炼（选定方案）

对模块摘要做 embedding → 语义聚类 → LLM 命名和精细调整。

| 维度 | 评价 |
|------|------|
| 准确性 | **高** — 语义嵌入基于业务含义聚类 |
| 稳定性 | **高** — embedding 确定性，聚类算法确定性 |
| 改动量 | 中 |
| 根因解决 | **完全** — P0~P3 全部解决 |

**选择理由**: 方案 C 兼顾准确性和稳定性。嵌入确定性消除 LLM 分类的随机性；LLM 只负责命名和微调（它最擅长的事），而非全量分类。调用图信号保留作为聚类距离的辅助权重。

---

## 3. 设计详情

### 3.1 流水线变更

```
当前:
  classify_entities → detect_reorg → graph_decompose → assign_keys
    → classify_domains → persist_classification → generate_titles
    → set_review_status → compose_leaf_modules → compose_domain_agents → ...

改进后:
  classify_entities → detect_reorg → graph_decompose → assign_keys
    → generate_titles → compose_leaf_modules
    → classify_domains (嵌入聚类!) → persist_classification
    → set_review_status → compose_domain_agents → ...
```

| 变更点 | 当前 | 改进后 |
|--------|------|--------|
| classify_domains 位置 | compose_leaf_modules **前** | compose_leaf_modules **后** |
| 分组机制 | Louvain 社区检测 | 语义嵌入 HAC 聚类 |
| LLM 角色 | 命名 + 后处理补救 | 命名 + 结构精炼 |
| 调用图信号 | 主要依据 | 辅助权重 |
| generate_titles | classify_domains 后 | classify_domains 前（不依赖 domain）|
| set_review_status | classify_domains 前 | classify_domains 后（依赖 domain_tree）|

**I/O 契约不变**: `classify_domains` 节点输出仍为 `domain_mapping`, `domain_display_names`, `domain_tree`, `affected_domains`, `module_call_edges`。

**依赖验证**:

| 节点 | 依赖 | 可提前? |
|------|------|---------|
| generate_titles | module_tree, llm | ✅ 不依赖 domain |
| compose_leaf_modules | modules, entity_roles, graph_store | ✅ 不依赖 domain |
| classify_domains | modules, entity_roles, graph_store, llm, **module_summaries** | ✅ 新增摘要输入 |
| set_review_status | **domain_tree** | ❌ 必须在 classify_domains 后 |
| persist_classification | **domain_mapping**, wiki_store | ❌ 必须在 classify_domains 后 |

### 3.2 语义嵌入聚类算法

**新增类**: `DomainSemanticClusterer` (`wiki/domain_semantic_clusterer.py`)

**输入**:
- `biz_modules`: 过滤后的业务模块列表 `[(repo_id, name)]`
- `module_summaries`: `{name: {summary_text, ...}}`
- `call_edges`: 模块间调用边 `[(src, dst, weight)]`

**EmbeddingGenerator 获取**: 通过 `get_settings().embedding` 获取配置，再调用 `EmbeddingGenerator.shared(config)` 获取单例（复用索引阶段已加载的模型，无额外初始化开销）。

**处理流程**:

```
Step 1: 构建嵌入文本
  对每个 BIZ 模块:
    if module in module_summaries:
      text = f"{name} [{path}] — {summary_text}"
    else:
      text = f"{name} [{path}]"  (fallback)

Step 2: 批量生成 embedding
  embeddings = await embedding_gen.generate(texts)
  → 每个模块得到一个向量

Step 3: 计算距离矩阵
  cosine_dist = 1 - cosine_similarity(embeddings)
  调用图辅助 (双向):
    if (mod_i, mod_j) 或 (mod_j, mod_i) 存在调用边:
      dist[i][j] *= 0.85
      dist[j][i] *= 0.85

Step 4: 层次聚类 (HAC)
  k_min = max(3, N // 20)
  k_max = min(max(k_min + 1, N // 3), 15)
  if N < 10: 单一簇处理

  best_k = argmax silhouette_score(dist, labels)
    for k in range(k_min, k_max + 1)

  clustering = AgglomerativeClustering(
    metric='precomputed', linkage='average', n_clusters=best_k
  )
```

**设计决策**:

| 决策 | 选择 | 理由 |
|------|------|------|
| 聚类算法 | HAC (average linkage) | 不需预设 K；层次结构天然支持子域 |
| 距离度量 | 余弦距离 + 调用图折扣 (双向 ×0.85) | 语义为主，拓扑为辅 |
| 聚类数 | Silhouette Score 自动搜索 | 不同项目模块数差异大 |
| 最小/最大簇 | min=3, max=40 | 太小无意义，太大需要子域拆分 |

### 3.3 LLM 命名增强

**修改类**: `GraphDomainNamer` (`wiki/graph_domain_namer.py`)

接口变更: `name_community(module_names)` → `name_community(module_infos)` 其中 `module_infos` 为 `list[dict]`，每项含 `name`, `path`, `summary`。

**命名 Prompt (改进后)**:

```
You are naming a group of code modules for a business documentation wiki.
These modules were grouped by their semantic similarity (business function).

Business context: {business_id}

Module details:
{module_details}

Rules:
- Name the BUSINESS capability these modules provide, not code structure
- Use concise Chinese business terminology (2-6 chars) for display_name
- The slug should be kebab-case ASCII describing the business capability
- Do NOT name based on technical patterns (Handler, Service, Dao, etc.)
{used_names_block}

Return ONLY valid JSON: {"slug": "...", "display_name": "...", "description": "..."}
```

`{module_details}` 格式 (每行):
```
- IntimacyService [intimacy/service/] — 亲密关系核心服务，管理好友亲密度等级
```

### 3.4 全局一致性审查

**修改类**: `GraphSemanticCorrector` (`wiki/graph_semantic_corrector.py`)

新增方法: `review_global_consistency()`，在所有域命名完成后执行一次 LLM 调用。

**Prompt**:
```
You are reviewing domain assignments for a code documentation wiki.
Business: {business_id}

All domains with their top representative modules:
{domain_listing}

Tasks:
1. MERGE domains with overlapping business scope into one
2. RENAME domains that use technical terms instead of business terms
3. Flag obvious module misplacements (max 3 moves)

Rules:
- Only merge when business meaning clearly overlaps
- Keep the domain with more modules as the merge target
- Max 30% of modules can be moved

Return JSON:
{
  "merges": [{"sources": ["slug1", "slug2"], "target": "slug1",
              "new_display_name": "...", "reason": "..."}],
  "renames": [{"slug": "...", "new_display_name": "...", "reason": "..."}],
  "moves": [{"module": "...", "from": "...", "to": "...", "reason": "..."}]
}
```

`{domain_listing}` 格式 (每域前 5 个模块名，控制 token):
```
- intimacy-relations (亲密关系) — 42 modules
  IntimacyService, ClosedFriendHandler, IntimacyTaskManager, IntimacyGiftService, PrivateRoomManager
```

### 3.5 子域拆分

大域 (>15 模块) 递归使用同样的嵌入聚类拆分子域，替代当前的 `detector.detect_sub_communities` (Louvain)。

子域命名注入父域上下文:
```
You are naming a SUB-DOMAIN within parent domain "{parent_display_name}".
This sub-domain should describe a SPECIFIC aspect within "{parent_display_name}".
Do NOT repeat the parent domain concept.
```

### 3.6 下游影响分析

| 下游组件 | 依赖 | 影响 |
|----------|------|------|
| `compose_domain_agents_node` | `domain_tree` (分组) + `module_tree` (结构上下文) | 域分组更准确 → 域页面质量更高 |
| `persist_classification_node` | `domain_mapping`, `domain_display_names` | I/O 不变，无影响 |
| `set_review_status_node` | `domain_tree` | I/O 不变，无影响 |
| `summarize_leaves_node` | `pages` | 间接受益 |
| Dashboard 域树展示 | `WikiSection` 节点 | 域结构更清晰 |

**增量更新**: 增量运行时仍重新执行完整聚类（`detect_reorg_node` 判断 `reorg_type != "none"` 时进入完整流程）。嵌入确定性 + `DomainStabilizer` 保证大部分域分配在增量更新中保持稳定，只有新增/变更模块的域归属可能调整。

`module_tree` 与 `domain_tree` 不存在挂载冲突：
- `domain_tree` 决定"谁和谁是一组"（业务域分组）
- `module_tree` 提供"组内成员之间的调用关系"（结构上下文）
- `_build_baseline()` 使用 `domain_modules = set(modules)` 过滤 `module_tree` 中的边，只取当前域内的依赖拓扑

---

## 4. 代码架构

### 4.1 节点内部流程

```
graph_driven_domain_decompose_node (重构)
│
├── Step 0: 过滤 BIZ 模块 (不变)
├── Step 1: 构建嵌入文本 (新增) — 从 state.module_summaries 获取 summary_text
├── Step 2: 生成 embedding (新增) — EmbeddingGenerator.shared(get_settings().embedding).generate()
├── Step 3: 获取调用图边 (保留) — fetch_module_call_edges()
├── Step 4: 语义聚类 (新增，替代 Louvain) — DomainSemanticClusterer.cluster()
├── Step 5: LLM 命名 (增强) — GraphDomainNamer.name_community(module_infos)
├── Step 6: 后处理 (简化) — _ensure_ascii_keys + _consolidate_split_entities
├── Step 7: 全局一致性审查 (替代现有 Step 5.5 + 7.5) — review_global_consistency()
├── Step 8: 子域拆分 (方法改变) — 嵌入聚类替代 detect_sub_communities
├── Step 9: Domain Stabilizer (保留)
└── Step 10: 构建 domain_tree (不变)
```

### 4.2 模块变更清单

| 类/模块 | 文件 | 操作 | 说明 |
|---------|------|------|------|
| `DomainSemanticClusterer` | `wiki/domain_semantic_clusterer.py` | **新增** | 嵌入聚类核心 |
| `GraphDomainNamer` | `wiki/graph_domain_namer.py` | **修改** | 接受 module_infos；增强 prompt |
| `GraphSemanticCorrector` | `wiki/graph_semantic_corrector.py` | **修改** | 新增 `review_global_consistency()` |
| `graph_driven_domain_decompose_node` | `wiki/nodes/graph_domain_decompose.py` | **重构** | 用嵌入聚类替代 Louvain |
| `pipeline_graph.py` | `wiki/pipeline_graph.py` | **修改** | 节点顺序调整 |
| `pipeline_state.py` | `wiki/pipeline_state.py` | **验证** | 确认 `module_summaries` 在新位置可用 |

**删除/替代的依赖关系**:
- `GraphCommunityDetector` — 不再在 classify_domains 中使用（graph_decompose 仍保留）
- `_merge_domains_by_keyword` — 嵌入聚类已天然处理
- `correct_module_assignments()` — 被 `review_global_consistency()` 的 `moves` 操作替代
- `merge_similar_domains()` — 被 `review_global_consistency()` 的 `merges` 操作替代

**保留的组件**:
- `fetch_module_call_edges` — 辅助聚类距离
- `DomainStabilizer` — 跨运行稳定性
- `_ensure_ascii_keys`, `_consolidate_split_entities` — 基础安全网

**Fallback 策略**:
- 如果 `EmbeddingGenerator` 初始化失败，fallback 到现有 Louvain 路径（保留旧代码为 fallback 分支）
- 如果 `module_summaries` 为空，fallback 到 module_name + path 做 embedding

### 4.3 新增依赖

```toml
scikit-learn = ">=1.4"
```

---

## 5. 时序影响

| 阶段 | 当前时间 | 改进后 | 说明 |
|------|----------|--------|------|
| compose_leaf_modules | ~15-25min | 不变 | 不依赖 domain |
| classify_domains | ~2min (在前) | ~2-3min (在后) | 增加嵌入计算 |
| 域树可见时间 | ~2min | ~20min | 延迟但更准确 |
| compose_domain_agents | 不变 | 不变 | 依赖 domain_tree |

---

## 6. 测试策略

| 层级 | 内容 | 文件 |
|------|------|------|
| 单元 | `DomainSemanticClusterer`: 距离矩阵、调用图折扣、K 搜索 | `tests/wiki/test_domain_semantic_clusterer.py` |
| 单元 | `GraphDomainNamer` prompt 格式化 | `tests/wiki/test_graph_domain_namer.py` |
| 单元 | `GraphSemanticCorrector.review_global_consistency` | `tests/wiki/test_graph_semantic_corrector.py` |
| 集成 | `graph_driven_domain_decompose_node` 完整流程 | `tests/wiki/test_pipeline_domain_integration.py` |
| 端到端 | 完整流水线，验证域树输出 | 手动触发 + 日志 |

---

## 7. 风险与缓解

| 风险 | 概率 | 缓解 |
|------|------|------|
| EmbeddingGenerator 不可用 | 低 | fallback 到现有 Louvain 路径（保留旧代码分支） |
| 嵌入模型对中文业务术语理解不够 | 低 | LLM 全局审查兜底；可换更强模型 |
| scikit-learn 引入 | 低 | 项目已有 scipy/numpy |
| 模块摘要缺失 | 低 | fallback 到 name + path 做 embedding |
| 聚类数不合理（极端 case） | 中 | Silhouette Score + 硬限制 (3≤K≤15) |
| 域树可见延迟增加 (~20min) | 确定 | 用户确认准确性优先 |

---

## 8. 预期效果

| 指标 | 当前 | 预期 |
|------|------|------|
| 同义域分散 | "亲密"3 处 + "私密"2 处 | 合并为 1 个域 |
| 错放模块 | 多 | 接近 0 |
| 技术名域 | 2+ | 0 |
| 子域碎片化 | 7 子域/域 | 3-5 子域/域 |
| 域名业务准确度 | 低 | 高（基于摘要语义） |
| 多次执行稳定性 | 中（LLM 随机性） | 高（嵌入确定性） |
