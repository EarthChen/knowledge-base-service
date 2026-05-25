# P1+P2 综合修复设计：Heal 重设计 + 域分类增量 + 前端质量

**Created:** 2026-05-24
**Status:** Draft → Pending Review

---

## 概述

基于全仓库代码审计（域分类、Heal/Quality Gate、前端仪表盘）+ Understand-Anything 竞品对比，本 spec 覆盖 11 项改进，分 3 批实施。

## 实施计划

| 批次 | 包含项 | 预估工时 | 备注 |
|------|--------|---------|------|
| **Batch E** | E-1~E-4（正确性修复） | 2 天 | 无外部依赖 |
| **Batch F** | F-1~F-5（图路径+性能） | 3-4 天 | F-1 最大；F-3 依赖 F-1 |
| **Batch G** | G-1、G-3（前端） | 2 天 | 独立于后端 |

---

## Batch E：正确性修复

**实施顺序**: E-2 → E-1 → E-3 → E-4（E-2 最简单；E-1+E-3 共同修改 quality_gate.py；E-4 独立）

### E-1: Heal 计数器分离

**问题**: `heal_attempts` 在内部轮次和外层循环间共用。`_bounded_heal` 每次调用递增（`heal.py:239`），`quality_gate` 用相同计数器决定是否允许外层重入（`quality_gate.py:160-166`）。CORE 页面内部跑 3 轮后 `attempts=3 >= max_retries=2`，外层 graph 循环永远不触发。

**修改**:

1. **新增 `heal_cycles` 状态字段** — 记录外层循环次数
2. **`wiki/nodes/quality_gate.py:162-165`** — 改用 `heal_cycles` 判断重入:
   ```python
   cycles = heal_cycles.get(page.path, 0)
   if structural_score < threshold and cycles < max_retries:
       pages_to_heal.append(page.path)
   ```
3. **`wiki/nodes/heal.py`** — `heal_pages_node` 返回新增 `heal_cycles` 字段:
   ```python
   heal_cycles: dict[str, int] = dict(state.get("heal_cycles", {}))
   # ... 在函数末尾:
   for p in initial_paths:
       heal_cycles[p] = heal_cycles.get(p, 0) + 1
   return {
       ...,
       "heal_cycles": heal_cycles,
   }
   ```
4. **`wiki/pipeline_state.py`** — 添加 `heal_cycles: Annotated[dict[str, int], ...]` 类型

**文件**: `wiki/nodes/heal.py`, `wiki/nodes/quality_gate.py`, `wiki/pipeline_state.py`
**代码量**: ~20 行

### E-2: 错误占位页排除治愈

**问题**: `domain_compose.py:292` 产生的 `generation_mode: agent_error` 占位页必然 L1 < 0.7，触发昂贵的 heal 策略链。

**修改**:

在 `wiki/nodes/quality_gate.py` 的 page 循环中（约 L92-107），添加:
```python
gen_mode = page_dict.get("metadata", {}).get("generation_mode", "")
if gen_mode == "agent_error":
    quality_scores[page.path] = {
        "l1_structural": 0.0,
        "overall": 0.0,
        "skipped_reason": "agent_error",
    }
    continue
```

**文件**: `wiki/nodes/quality_gate.py`
**代码量**: ~5 行

### E-3: L2 纳入治愈决策

**问题**: `quality_gate.py:164-166` 仅用 L1 structural 判断是否治愈。

**修改**:

1. **`core/config.py`** — `AppWikiFlags` 新增:
   ```python
   heal_l2_threshold: float = Field(default=0.0, ge=0.0, le=1.0)
   ```
   默认 0.0 保持现有行为；设为 0.55 启用 L2 驱动治愈。

2. **`wiki/nodes/quality_gate.py:164-166`** — 扩展条件:
   ```python
   l2_val = score_dict.get("l2_bench", 1.0)
   l2_below = (l2_val < wiki_cfg.heal_l2_threshold) if wiki_cfg.heal_l2_threshold > 0 and "L2" in levels else False
   if (structural_score < threshold or l2_below) and cycles < max_retries:
       pages_to_heal.append(page.path)
   ```

**文件**: `core/config.py`, `wiki/nodes/quality_gate.py`
**代码量**: ~10 行

### E-4: SUPPORTING 角色收窄

**问题**: `DOMAIN_CLASSIFICATION_ENTITY_ROLES` 包含 `SUPPORTING`（score 15-39 的工具类），稀释聚类信号。

**修改**:

1. **`core/config.py`** — `AppWikiFlags` 新增:
   ```python
   classify_include_supporting: bool = Field(default=True)
   ```

2. **`wiki/nodes/graph_domain_decompose.py:456-463`** — biz_modules 过滤:
   ```python
   from core.config import get_settings
   wiki_cfg = get_settings().wiki

   allowed_roles = set(DOMAIN_CLASSIFICATION_ENTITY_ROLES)
   if not wiki_cfg.classify_include_supporting:
       allowed_roles.discard(WikiEntityRole.SUPPORTING)

   # 现有过滤逻辑使用 allowed_roles
   ```

3. **SUPPORTING 模块路由**: 被排除的 SUPPORTING 模块在聚类完成后路由回域:
   - 有 call edge 指向 biz 模块: 归入该 biz 模块所在域
   - 无 call edge: 计算嵌入距离，归入最近域
   - 此路由在主聚类完成后执行，不影响聚类质量

**文件**: `core/config.py`, `wiki/nodes/graph_domain_decompose.py`
**代码量**: ~25 行

---

## Batch F：图路径 + 性能

**实施顺序**: F-3 → F-1 → F-2 → F-4 → F-5（F-1 依赖 F-3 的复合键基础；F-2 依赖 F-1 的增量框架；F-4/F-5 独立）

### F-1: 图路径增量语义支持

**问题**: `graph_driven_domain_decompose_node` 每次全量重聚类，覆盖 `affected_domains`（L726-727）。增量运行重建所有域。

**修改**（3 子步骤）:

**F-1a: 保留已有域映射**

从 state 读取 `existing_domain_mapping`（`dict[str, list[tuple[str,str]]]`，由 WikiService 注入上次运行结果）。

当 `is_incremental=True` 且存在 `existing_domain_mapping`:
- 计算 `changed_module_names`: 来自 state 的 `affected_modules` 集合
- `unchanged_modules`: `existing_domain_mapping` 中不在 `changed_module_names` 中的模块
- 仅对 `changed_modules`（新增+修改）执行嵌入+聚类

**F-1b: 变更模块分类策略**

- 新增/修改模块: 计算嵌入，与现有域质心比较余弦相似度
  - 如果最近域距离 < 阈值（默认 0.3）: 归入该域
  - 否则: 收集为"待聚类"集合，如果 ≥ 3 个则组成新域，否则归入最近域
- 删除模块: 从域移除，空域删除
- domain_stabilizer 保留名称对齐

**F-1c: 保留输入 affected_domains**

```python
if is_incremental:
    affected_domains = list({
        slug for slug, pairs in domain_mapping.items()
        if any(name in changed_module_names for _, name in pairs)
    })
else:
    affected_domains = list(domain_mapping.keys())
```

**约束**:
- 增量运行后首次全量重分类将自动校准偏移
- `existing_domain_mapping` 通过 state 而非 configurable 传递（保持与 pipeline_state 一致）

**文件**: `wiki/nodes/graph_domain_decompose.py`, `wiki/service.py`
**代码量**: ~80 行

### F-2: 图路径 anchor/pinned 支持

**问题**: 仅回退路径支持 anchor/pinned 模块。

**修改**:

1. 从 state 读取 `pinned_modules: dict[str, str]`（key=module_name, value=target_domain_slug）
2. 在 Step 0 过滤后、Step 1 聚类前: 将 pinned 模块从 `biz_modules` 移除
3. 在 Step 7（后处理）后: 将 pinned 模块归入指定域
   ```python
   for mod_name, target_slug in pinned_modules.items():
       # 查找 mod_name 对应的 (repo, name)
       for repo, mod_list in modules.items():
           for m in mod_list:
               if m.get("properties", {}).get("name") == mod_name:
                   # 确保 target_slug 存在于 domain_mapping
                   if target_slug in domain_mapping:
                       domain_mapping[target_slug].append((repo, mod_name))
                   break
   ```
4. 如果目标域不存在，用 domain_stabilizer 的名称映射查找替代

**文件**: `wiki/nodes/graph_domain_decompose.py`
**代码量**: ~30 行

### F-3: 模块复合键索引

**问题**: `module_summaries`/`module_paths`/`module_docstrings` 以 name 为键，多仓同名覆盖。

**修改**:

1. `graph_domain_decompose.py:441-454` — 键改为 `f"{repo}|{name}"`:
   ```python
   compound_key = f"{repo}|{name}"
   module_paths[compound_key] = path
   if doc:
       module_docstrings[compound_key] = doc
   ```
2. 所有引用处（embedding text 构建、naming context、summary 查找）使用 compound_key
3. `domain_compose.py:51-67` — `_module_dict_by_name` 改为双重索引:
   ```python
   by_compound: dict[str, dict] = {}
   by_name: dict[str, dict] = {}  # fallback
   for repo, mods in modules.items():
       for m in mods:
           name = m.get("properties", {}).get("name", "")
           if name:
               by_compound[f"{repo}|{name}"] = m
               by_name.setdefault(name, m)
   ```

**文件**: `wiki/nodes/graph_domain_decompose.py`, `wiki/nodes/domain_compose.py`
**代码量**: ~25 行

### F-4: Parent pages 并行化

**问题**: `compose_parent_pages_node` 串行生成。

**修改**:

在 `aggregate.py:163` 的层级循环中，每层内部改为并行:
```python
sem = PipelineConcurrency.semaphore("compose")

async def _bounded_compose_parent(parent_domain: dict) -> list[dict[str, Any]]:
    async with sem:
        return await _compose_one_parent(parent_domain, ...)

for level_idx, level_parents in enumerate(parent_levels):
    results = await asyncio.gather(
        *[_bounded_compose_parent(p) for p in level_parents],
        return_exceptions=True,
    )
    for r in results:
        if isinstance(r, list):
            all_parent_pages.extend(r)
        elif isinstance(r, BaseException):
            log.warning("compose_parent_failed", error=str(r))
```

现有串行逻辑（L164-313）提取为 `_compose_one_parent()` 辅助函数。

**文件**: `wiki/nodes/aggregate.py`
**代码量**: ~30 行

### F-5: DomainDocAgent 迭代缩减

**问题**: Agent 内部最多 20 轮质量评估 + 管线 heal 阶段再次评估 = 双重循环。

**修改**:

1. **`core/config.py`** — `AppWikiFlags` 新增:
   ```python
   domain_agent_early_exit_quality: float = Field(default=0.6, ge=0.0, le=1.0)
   ```

2. **`wiki/domain_doc_agent.py:560`** — 在 `evaluate_quality` 后添加:
   ```python
   from core.config import get_settings
   early_exit = get_settings().wiki.domain_agent_early_exit_quality
   if quality.coverage >= early_exit and quality.citation_density >= 0.3:
       log.info("agent_early_exit", domain=self.domain_name, coverage=quality.coverage)
       break
   ```

**预期收益**: 平均减少 1-2 轮迭代/域；30 域可节省 30-60 次 LLM 调用。

**文件**: `core/config.py`, `wiki/domain_doc_agent.py`
**代码量**: ~10 行

---

## Batch G：前端

### G-1: Toast a11y 修复

**问题**: Toast 容器无 `aria-live`，屏幕阅读器无感知；dismiss 标签硬编码英文。

**修改**:

1. **`dashboard/src/components/ui/Toast.tsx`** — 容器添加:
   ```tsx
   <div role="status" aria-live="polite" className="...">
   ```
2. **dismiss 按钮** — i18n 化:
   ```tsx
   aria-label={t.common.dismiss}
   ```
3. **`dashboard/src/i18n/en.ts`** — `common.dismiss: "Dismiss notification"`
4. **`dashboard/src/i18n/zh.ts`** — `common.dismiss: "关闭通知"`

**文件**: `dashboard/src/components/ui/Toast.tsx`, `dashboard/src/i18n/en.ts`, `dashboard/src/i18n/zh.ts`
**代码量**: ~10 行

### G-3: WikiShell/GraphExplorer 组件拆分

**问题**: `WikiShell.tsx`（727 行）和 `GraphExplorer.tsx`（1087 行）职责过重。

**修改**:

**WikiShell 拆分**:
| 新文件 | 职责 | 约行数 |
|--------|------|--------|
| `WikiShell.tsx` | 布局壳（sidebar + content + tool panel） | ~200 |
| `WikiDomainDialogs.tsx` | 域管理对话框状态机 | ~150 |
| `useWikiSSE.ts` | SSE 事件处理 hook | ~100 |
| `WikiSidebarLayout.tsx` | 侧边栏树导航布局 | ~150 |

**GraphExplorer 拆分**:
| 新文件 | 职责 | 约行数 |
|--------|------|--------|
| `GraphExplorer.tsx` | 主容器 + ReactFlow | ~400 |
| `useGraphData.ts` | 数据获取 + dagre 布局 | ~200 |
| `useGraphControls.ts` | 搜索/过滤/展开逻辑 | ~200 |
| `GraphNodeDetail.tsx` | 节点详情面板 | ~200 |

**原则**:
- 仅拆分重组织，不改功能
- 所有 state 通过 hook/context 传递
- 保持现有测试通过
- 暗色模式逻辑统一使用 `useIsDarkMode` hook（消除 3 处重复）

**文件**: 新建 ~8 文件，修改 2 文件
**代码量**: 净增 ~0 行

---

## 已排除项

| 项 | 原因 |
|----|------|
| G-2: 非代码文件轻量解析 | 用户指定延后 |

---

## 测试策略

每个 Batch 完成后:
1. 运行该 Batch 涉及文件的单元测试（TDD：先写测试再实现）
2. 运行 `uv run pytest tests/wiki/ --no-cov -q` 全量回归
3. 前端 Batch G: `pnpm test` + `pnpm lint`

## 验收标准

- [ ] 2930+ wiki tests 全部通过
- [ ] 新增测试覆盖每个修改点
- [ ] 无 ruff 和 eslint 错误
- [ ] `docs/superpowers/TODO.md` 更新完成项
