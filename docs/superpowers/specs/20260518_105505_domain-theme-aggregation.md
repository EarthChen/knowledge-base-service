# 域主题聚合设计

> Status: `[Approved]`
> Date: 2026-05-18

## 1. 背景与问题

Wiki 域生成管线产出扁平的多根域结构，语义相关的域（如"家族核心管理"、"家族任务系统"、"家族战力与成长"）没有被聚合到统一父域（如"家族"）下。

### 1.1 根因

| 阶段 | 问题 | 位置 |
|------|------|------|
| classify | LLM 产出扁平 slug→pairs，无父子约束 | `cross_repo_domain_planner.py` |
| decompose | 提示词 "Prefer flatter trees" 阻止聚合 | `dependency_graph.py:328-331` |
| 批处理 | 超 token 分片后 `trees.extend(tree)` 直接拼接为并列根 | `dependency_graph.py:269-293` |
| 后处理 | `merge_small_domains` 仅合并极小域，靠字符 trigram 无语义理解 | `domain_merger.py:35-52` |

### 1.2 附带问题（已修复）

| 问题 | 文件 | 状态 |
|------|------|------|
| 前端域编辑后不刷新（invalidate queryKey 不一致）| `useDomainHierarchy.ts` | ✅ 已修复 |
| Redis NoScriptError（EVALSHA 未 fallback） | `rate_limiter.py` | ✅ 已修复 |
| decompose max_depth=3 太低 | `nodes/classify.py` | ✅ 已提升到 5 |

## 2. 方案选择

评估了三种方案：

| 方案 | 核心思路 | 优点 | 缺点 |
|------|----------|------|------|
| A. 纯 LLM 语义聚合 | decompose 后 LLM 分组 | 简单、理解语义 | 不可控 |
| B. 域锚点 + LLM 辅助 | 用户预定义结构骨架 | 用户可控 | 实现量大、冷启动 |
| **C. 混合方案（选定）** | Phase 1 LLM 聚合 + Phase 2 锚点 | 渐进交付、低风险 | 两阶段 |

## 3. Phase 1：LLM 自底向上递归域聚合

### 3.1 数据流变更

```
Before: classify → decompose → assign_slugs → oversized_rebalance → tree_linker
After:  classify → decompose → assign_slugs → 【aggregate_recursive】→ oversized_rebalance → tree_linker
                                                ↑ NEW
```

### 3.2 核心算法

**自底向上递归聚合**：

```
aggregate_domains_recursive(nodes, llm, depth=0, max_depth=5)
  1. 对每个节点：递归处理其 children
  2. 当前层兄弟节点 >= 3 个时：
     a. 过滤掉 user_edited=true 的域
     b. 当可聚合域 > 30 个时，分批处理（每批 ~25 个）
     c. 将可聚合域信息传给 LLM（仅域名+描述，~2000 tokens/批）
     d. LLM 返回语义分组结果
     e. 构建父域节点，被聚合域变为 children
     f. 检查新树深度：超过 max_depth 则撤销本层聚合
  3. 返回新的节点列表
```

**自适应深度**：贪心聚合，但每次聚合后检查树深度。超过 `max_depth` 则回退该层聚合结果。

**大批量域处理**：当同层兄弟域超过 30 个时，分批传入 LLM 避免噪声干扰分组准确性。提示词中强调"如果不确定是否相关，标记为 standalone"。

**跨批聚合 (consolidation)**：分批处理后，将所有批次产生的新父域 + 所有 standalone 域做一次最终 LLM 调用。确保第 1 批中被标记为 standalone 的域在第 2 批中发现了相关组后能被正确归入。

```
分批处理流程：
  批次1: 域 A1-A25 → {家族: [A3,A7,A12]}, standalone: [A1,A2,...]
  批次2: 域 A26-A50 → {直播: [A30,A35]}, standalone: [A26,A28,...]
  
  Consolidation: 输入 = [家族(group), 直播(group), A1, A2, A26, A28, ...]
    → LLM 发现 A28 应归入"家族"
    → assign_to_existing: {"family": ["A28"]}
```

### 3.3 组件清单

#### `wiki/domain_merger.py` — 新增函数

| 函数 | 职责 |
|------|------|
| `aggregate_domains_recursive()` | 入口：自底向上递归聚合 |
| `_aggregate_siblings_by_theme()` | 单层聚合：调 LLM + 应用结果 |
| `_build_aggregation_prompt()` | 构建 LLM 提示词 |
| `_parse_aggregation_result()` | 解析 LLM 返回的分组 JSON |
| `_apply_aggregation()` | 根据分组结果构建父域节点 |
| `_tree_depth()` | 计算树深度（用于自适应检查） |

#### `wiki/dependency_graph.py` — 修改提示词

- L328-331: 去掉 "Prefer flatter trees when modules are loosely related"
- 替换为鼓励主题聚合的指令

#### `wiki/nodes/classify.py` — 集成

- `decompose_hierarchy_node()` 中 `_assign_slugs_to_tree` 之后、`_detect_oversized_leaves` 之前调用

#### `wiki/domain_management_service.py` — user_edited 标记

- move/merge/create/rename 操作成功时，给 WikiSection 设置 `user_edited=true`

#### `api/routes/wiki_domain_routes.py` — 手动触发 API

- `POST /api/v1/wiki/domains/reorganize`
- 参数：`business_id`, `reset_user_edits: bool = false`

### 3.4 LLM 提示词

```
以下是一个代码仓库中自动发现的 {N} 个业务域。
请分析这些域之间的语义关系，将属于同一业务主题的域分组到父域下。

规则：
1. 只有真正属于同一业务主题的域才应聚合
   例如："家族核心管理"、"家族任务系统"、"家族战力" → 父域 "家族"
2. 不相关的域保持独立（标记为 standalone）
3. 每个父域至少包含 2 个子域
4. 父域名为简短的中文业务主题名（不限字数，取最能概括子域的名称）
5. 每个域只能属于一个组
6. 不要过度聚合——只聚合明确相关的域
7. 如果不确定某个域是否属于某组，标记为 standalone

已有父域结构（请优先将相关域归入已有父域，而非创建同名新组）：
{existing_parents_json}

待分组的域列表：
{domain_info_json}

返回 JSON：
{
  "new_groups": [
    {
      "parent_display_name": "家族",
      "parent_slug": "family",
      "children_slugs": ["family-core-management", "family-task-system", ...]
    }
  ],
  "assign_to_existing": {
    "family": ["family-task-system", "family-combat-growth"]
  },
  "standalone_slugs": ["gift-order-processing", ...]
}
其中 assign_to_existing 将域归入已有父域（key 为已有父域的 slug）。
```

### 3.5 "尊重用户编辑"机制

| 场景 | 行为 |
|------|------|
| 用户 move/merge/create/rename 域 | 目标 WikiSection 标记 `user_edited=true` |
| 自动聚合 | 跳过 `user_edited=true` 的域，保持其位置 |
| 用户手动"重新组织" | 可选 `reset_user_edits=true` 清除标记后重新聚合 |

#### 防止父域冲突（用户创建 vs LLM 生成）

**问题**：用户手动创建父域"家族"并移入部分子域后，LLM 可能为剩余相关域再创建一个同名"家族"父域，导致重复。

**解决**：

1. **提示词注入已有父域上下文**：构建聚合提示词时，扫描当前层已存在的父域（含 `user_edited`），作为"已有分组"传给 LLM。LLM 可将孤立域**归入已有父域**，而非创建新同名父域。

2. **提示词增加约束**：
   ```
   以下是已有的父域结构（请优先将相关域归入已有父域，而非创建同名新组）：
   - "家族" 已包含: ["家族核心管理"]
   ```

3. **去重兜底**：后处理中，若 LLM 仍创建了与已有父域同名/同 slug 的新组，自动将其 children 合并到已有父域下，而非创建重复节点。

### 3.6 成本分析

| 项目 | 值 |
|------|---|
| 每层输入 | ~20-50 个域名+描述 ≈ ~2000 tokens |
| 每层输出 | 分组 JSON ≈ ~500 tokens |
| 最大层数 | 2-3 层（自适应） |
| 总成本 | ~5000-7500 tokens |
| 延迟增加 | ~5-15 秒 |

## 4. Phase 2：域锚点机制（后续迭代，本次不实施）

### 4.1 概念

域锚点是用户预定义的"期望域结构骨架"。设定锚点后，分类阶段 LLM 会优先将模块归入对应域。

### 4.2 要点

- 存储：`WikiSection` 节点 `is_anchor=true`
- 管理 UI：Dashboard 域管理面板"设为锚点"
- 分类注入：扩展 `anchor_context`（`classify.py:176-183` 已有基础）
- 聚合协同：锚点域在自动聚合时作为优先父域候选

## 5. 错误处理

| 故障场景 | 处理方式 |
|----------|----------|
| LLM 调用失败 | 跳过当前层聚合，保持原结构，warning 日志 |
| LLM 返回非法 JSON | 同上 |
| LLM 返回的域名不存在 | 忽略该分组，warning 日志 |
| 聚合后树深超过 max_depth | 撤销本层聚合 |
| 所有域 user_edited | 不调 LLM，直接返回 |

## 6. 日志与可观测性

| 事件 | 用途 |
|------|------|
| `aggregate_recursive_start` | 节点数、层数 |
| `aggregate_theme_group_found` | 发现的分组 |
| `aggregate_theme_applied` | 聚合结果 |
| `aggregate_theme_skipped_depth` | 深度限制跳过 |
| `aggregate_theme_failed` | LLM 失败回退 |

## 7. 测试计划

1. 单元测试：`_parse_aggregation_result` 解析各种 LLM 输出
2. 集成测试：mock LLM，验证多层树聚合行为
3. 容错测试：LLM 失败安全回退
4. 深度限制测试：聚合后树深不超过 max_depth
5. user_edited 测试：标记域被正确跳过
6. 分批跨批聚合测试：验证 consolidation 能发现跨批的相关域
7. 父域冲突去重测试：验证已有父域 + LLM 同名新组的合并
8. 端到端：开发机运行完整 wiki 生成，对比聚合前后域结构

### 增量更新兼容性

根据 `pipeline_graph.py` 的路由逻辑：
- `reorg_type` 为 `full`、`heavy`、`light` 时，都会经过 `decompose_hierarchy` 节点
- 仅 `reorg_type=none` 跳过（无变更时直接 finalize）

因此聚合步骤集成在 `decompose_hierarchy_node` 中后，在所有有变更的场景下都会自动执行，无需额外处理。

## 8. 修改清单

### Phase 1 Task 列表

- [ ] **T1**: 修改 decompose 提示词 — `wiki/dependency_graph.py:328-331`
- [ ] **T2**: 新增 `aggregate_domains_recursive` + 辅助函数 — `wiki/domain_merger.py`
- [ ] **T3**: 集成到 `decompose_hierarchy_node` — `wiki/nodes/classify.py`
- [ ] **T4**: DomainManagementService 添加 `user_edited` 标记 — `wiki/domain_management_service.py`
- [ ] **T5**: 新增手动触发 API — `api/routes/wiki_domain_routes.py`
- [ ] **T6**: 单元测试 + 集成测试
