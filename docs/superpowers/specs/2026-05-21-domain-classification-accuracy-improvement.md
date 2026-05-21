# 域分类精准度提升方案

> 状态: 待审阅  
> 创建: 2026-05-21  
> 依赖: `2026-05-21-semantic-coherence-correction-design.md`

---

## 1. 当前问题

### 1.1 现象

```
当前域树:
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
| **P0** | Louvain 按调用拓扑分组，非按业务语义 | 同一业务概念的模块分散 |
| **P1** | LLM 命名只看类名，无路径/摘要/业务上下文 | 域名与真实业务不匹配 |
| **P2** | 每个社区独立命名，无全局一致性视角 | 同义域名重复 |
| **P3** | 子域拆分后独立命名，无父域约束 | 子域间语义重叠 |

### 1.3 关键发现

`compose_leaf_modules` 已为每个模块生成 200-500 字的业务摘要（`module_summaries`），包含：
- `summary_text`: 模块职责和核心业务逻辑描述
- `key_methods`: 最重要的 5 个方法
- `dependencies`: 依赖的其他模块
- `callers`: 调用该模块的外部模块

**且 `compose_leaf_modules` 完全不依赖 `domain_mapping`**。

---

## 2. 设计方案

### 2.1 核心策略: 摘要驱动域分类 + 增强命名 + 全局一致性审查

将域分类移到 `compose_leaf_modules` 之后，利用模块摘要做分类，同时增强 LLM 的命名上下文和全局审查能力。

### 2.2 流水线变更

```
当前:
  classify_entities → detect_reorg → graph_decompose → assign_keys
    → classify_domains → persist_classification → generate_titles
    → set_review_status → compose_leaf_modules → compose_domain_agents → ...

改进后:
  classify_entities → detect_reorg → graph_decompose → assign_keys
    → generate_titles → compose_leaf_modules
    → classify_domains (用摘要!) → persist_classification → set_review_status
    → compose_domain_agents → ...
```

**关键变更**:
- `classify_domains` 从 Step 4 移到 `compose_leaf_modules` 之后（可用摘要）
- `generate_titles` 不依赖 domain，提前到 `classify_domains` 前
- `set_review_status` 依赖 `domain_tree`，必须在 `classify_domains` 之后

**依赖验证**:
| 节点 | 依赖 | 可提前? |
|------|------|---------|
| generate_titles | module_tree, llm | ✅ 不依赖 domain |
| compose_leaf_modules | modules, entity_roles, graph_store | ✅ 不依赖 domain |
| classify_domains | modules, entity_roles, graph_store, llm, **module_summaries** | ✅ 新增摘要输入 |
| set_review_status | **domain_tree** | ❌ 必须在 classify_domains 后 |
| persist_classification | **domain_mapping**, wiki_store | ❌ 必须在 classify_domains 后 |

### 2.3 时序影响

| 阶段 | 当前时间 | 改进后 | 说明 |
|------|----------|--------|------|
| compose_leaf_modules | ~15-25min | 不变 | 不依赖 domain |
| classify_domains | ~2min (在前) | ~2min (在后) | 输入更丰富 |
| 域树可见时间 | ~2min 后 | ~20min 后 | 延迟但更准确 |
| compose_domain_agents | 不变 | 不变 | 依赖 domain_tree |

---

## 3. 详细设计

### 3.1 改进 1: 摘要驱动的域分类

`graph_driven_domain_decompose_node` 现在可以从 `state["module_summaries"]` 获取每个模块的业务描述。

**Louvain 社区检测保留**（调用图拓扑仍是有价值的信号），但 LLM 命名时传入摘要。

#### 命名 Prompt (改进后)

```
You are naming a group of code modules for a business documentation wiki.
These modules were grouped by their call-graph relationships.

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

`{module_details}` 格式（每个模块 1 行）:
```
- IntimacyService [intimacy/service/] — 亲密关系核心服务，管理好友亲密度等级
- ClosedFriendHandler [closedfriend/handler/] — 私密好友圈入口与成员管理
- IntimacyTaskManager [intimacy/task/] — 亲密度任务调度与执行
```

**数据来源**:
| 字段 | 来源 | 可用性 |
|------|------|--------|
| 模块名 | `state.modules` → `properties.name` | 100% |
| 路径(后2级) | `state.modules` → `properties.path` | ~95% |
| 业务摘要 | `state.module_summaries` → `summary_text` | ~90% (compose_leaf 后) |
| fallback | `properties.business_summary` 或 `properties.docstring` | ~60% |

### 3.2 改进 2: 全局域名一致性审查

在所有社区命名完成后，新增一步全局审查。

**时机**: Step 4 之后（构建 domain_mapping 后，后处理前）

**Prompt**:
```
You are reviewing domain assignments for a code documentation wiki.
Business: {business_id}

All domains with their modules and summaries:
{domain_listing}

Tasks:
1. MERGE domains with overlapping business scope into one
2. MOVE misplaced modules to the correct domain
3. RENAME domains that use technical terms instead of business terms

Rules:
- "亲密关系" and "私密好友" are the SAME business area → merge
- Only merge when business meaning clearly overlaps
- Infrastructure/utility modules: keep together, rename to business purpose
- Max 30% of modules can be moved

Return JSON:
{
  "merges": [{"sources": ["slug1", "slug2"], "target": "slug1",
              "new_display_name": "...", "reason": "..."}],
  "renames": [{"slug": "...", "new_display_name": "...", "reason": "..."}],
  "moves": [{"module": "...", "from": "...", "to": "...", "reason": "..."}]
}
```

`{domain_listing}` 格式（每域前 5 个代表性模块名，不含摘要，控制 token）:
```
- friendship-relations (好友关系) — 61 modules
  IntimacyService, ClosedFriendHandler, IntimacyTaskManager, IntimacyGiftService, PrivateRoomManager

- user-intimacy-ecosystem (用户亲密度生态) — 24 modules
  IntimacyPointService, GiftHandler, UserLevelService, QuickInteractionHandler, DealerIntegration
```

**与现有 GraphSemanticCorrector 的分工**:
| 步骤 | 职责 | 范围 |
|------|------|------|
| 全局域名一致性审查 (新增) | 顶层域合并 + 重命名 | 所有域 |
| GraphSemanticCorrector.correct (Step 5.5) | 模块级错放纠正 | 模块 → 域 |
| GraphSemanticCorrector.merge (Step 7.5) | 子域合并 | 子域 → 子域 |

### 3.3 改进 3: 子域命名注入父域上下文

子域命名时注入父域名称，避免子域名重复父域语义。

```
You are naming a SUB-DOMAIN within parent domain "{parent_display_name}".
This sub-domain should describe a SPECIFIC aspect within "{parent_display_name}".
Do NOT repeat the parent domain concept.

Module details:
{module_details}

Return ONLY valid JSON: {"slug": "...", "display_name": "...", "description": "..."}
```


---

## 4. 实施计划

| 步骤 | 文件 | 改动 | 优先级 |
|------|------|------|--------|
| 1 | `pipeline_graph.py` | 调整节点顺序：`compose_leaf_modules` 在 `classify_domains` 前 | P0 |
| 2 | `graph_domain_namer.py` | 接收 module_info (名+路径+摘要) 替代 module_names | P0 |
| 3 | `nodes/graph_domain_decompose.py` | 从 state.module_summaries 构建 module_info；传给 namer | P0 |
| 4 | `nodes/graph_domain_decompose.py` | 新增全局域名一致性审查步骤 | P0 |
| 5 | `graph_domain_namer.py` | 子域命名注入父域上下文 | P1 |
| 6 | `nodes/classify.py` | 扩展 `_RELATED_KEYWORDS` | P1 |
| 7 | `pipeline_state.py` | 确保 `module_summaries` 在新位置可用 | P0 |
| 8 | `tests/` | 更新测试 | P0 |

---

## 5. 预期效果

| 指标 | 当前 | 预期 |
|------|------|------|
| 顶级域数 | 6 | 4-6 |
| "亲密/私密"跨域 | 3+2 | 1 (合并) |
| 错放模块 | 多 | 接近 0 |
| 技术名域 | 2+ | 0 |
| 子域碎片化 | 7子域/域 | 3-5子域/域 |
| 域名业务准确度 | 低 | 高（基于摘要） |
| 域树可见延迟 | ~2min | ~20min |

---

## 6. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 域树可见延迟增加 | 可接受（用户确认准确性优先）|
| LLM 全局审查成本 | 1 次额外调用，~2-4 秒 |
| module_summaries 质量不均 | 有 fallback 到 docstring/path |
| 流水线重排可能引入 bug | 充分测试 + 增量部署 |

---

## 7. 未来演进

1. **Post-compose 域精修**: compose_domain_agents 后根据页面内容微调域分配
2. **Embedding-based 域相似度**: 用模块 embedding 替代关键词匹配做合并
3. **用户反馈循环**: Dashboard 手动调整域/模块作为 LLM fine-tuning 数据
