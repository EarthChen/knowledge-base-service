# 提案: Dashboard 业务强制选择 + 索引关联 + 任务进度增强

**状态**: Closed (大部分已实现, 剩余 gap 合并至 wiki 质量统一提案)  
**创建时间**: 2026-05-08 13:58:07  
**关联文件**: Indexing.tsx, Repositories.tsx, Businesses.tsx, WikiActiveTasks.tsx, wiki_task_routes.py, service.py

---

## 背景

### 问题 1: 索引与业务脱钩
当前 `Indexing.tsx` 页面允许用户在不选择业务的情况下直接索引仓库。索引后仓库存入 `kb_default` 图但未与任何业务关联，导致：
- Wiki 生成时需要手动指定 `business_id`
- 仓库与业务的归属关系不明确
- 新索引的仓库无法自动出现在对应业务的 Wiki 范围内

### 问题 2: 任务进度展示不足
当前 `WikiActiveTasks.tsx` 的限制：
- `progress_pct` 在整个 LangGraph 管道期间为 0（只基于仓库级完成度计算）
- 前端只识别 5 个 phase（leaf_compose, parent_aggregate, business_flow, navigation, quality_eval）
- 后端实际有更多 phase（classifying_domains, compose_leaf_modules 等）未上报
- 无法看到管道内部进度（如"正在合成第 400/847 个模块"）

---

## 目标

1. 用户必须创建并选择业务后才能进行索引
2. 索引完成后仓库自动绑定到当前业务
3. Wiki 生成时自动使用当前业务 ID
4. 管道内部进度实时可见（阶段 + 百分比 + 详情文字）

---

## Part 1: 业务强制选择 + 索引关联

### 设计方案

#### 前端变更

**Indexing.tsx:**
1. 引入 `useBusiness()` 获取 `currentBusiness` 和 `businesses` 列表
2. 在表单顶部添加业务选择器（下拉框）
3. 当 `businesses.length === 0` 或未选择业务时，禁用索引按钮并提示"请先创建业务"
4. 索引请求中增加 `business_id` 参数
5. 索引成功后自动调用 `bind_repositories` API 将仓库绑定到当前业务

**Repositories.tsx:**
1. 显示当前业务上下文（顶部显示当前选中的业务名称）
2. 仓库列表按当前业务过滤（只显示绑定到当前业务的仓库）

#### 后端变更

**api/routes/index_routes.py:**
1. `IndexBody` 增加可选字段 `business_id: str | None = None`
2. 索引完成后，若 `business_id` 非空，自动调用 `BusinessManager.bind_repositories` 绑定

**无需额外变更的:**
- `BusinessManager` 已有 `bind_repositories` 方法
- `ServiceRegistry` 已支持 `kb_{business_id}` 图隔离
- `Businesses.tsx` 已有创建业务和管理仓库绑定的完整 UI

### 修改文件清单

| 文件 | 变更内容 |
|------|---------|
| `dashboard/src/pages/Indexing.tsx` | 添加业务选择器、禁用逻辑、索引后自动绑定 |
| `dashboard/src/pages/Repositories.tsx` | 按当前业务过滤仓库列表 |
| `api/routes/index_routes.py` | IndexBody 增加 business_id，索引后自动绑定 |
| `api/models/index_models.py` | IndexBody schema 增加 business_id 字段 |

---

## Part 2: 任务进度增强

### 设计方案

#### 后端变更

**进度回调增强 (wiki/service.py + pipeline_orchestrator.py):**

1. `run_langgraph_pipeline` 接受 `progress_callback` 参数
2. 通过 LangGraph `configurable` 传递给各管道节点
3. 关键节点内部报告进度：
   - `classify_entities`: phase="classify_entities", detail="实体分类中"
   - `classify_domains`: phase="classify_domains", detail="域分类中"
   - `compose_leaf_modules`: phase="compose_leaf", detail="模块内容合成 {done}/{total}", progress_pct=加权值
   - `compose_parent_pages`: phase="parent_aggregate", detail="父域聚合中"
   - `synthesize_overviews`: phase="overview", detail="生成系统概览"
   - `heal_pages`: phase="quality_eval", detail="质量修复"
   - `create_links`: phase="linking", detail="交叉引用解析"

**进度百分比加权算法:**

```
classify_entities:  5%
classify_domains:   5%
compose_leaf:      55% (按 completed/total 模块线性插值)
parent_aggregate:  15%
overview:           5%
quality_eval:       5%
linking:            5%
persisting:         5%
```

进度值 = `stage_base + stage_weight * (completed_in_stage / total_in_stage)`

**task_store 变更:**
- `update_status` 已支持 `**extra` kwargs，新增 `detail` 字段即可无代码改动
- 前端轮询 `/api/v1/wiki/business/tasks/{task_id}` 已能获取所有字段

#### 前端变更

**WikiActiveTasks.tsx:**
1. 扩展 `phaseI18nKeys` 映射覆盖所有后端 phase
2. 显示 `task.detail` 信息（如"模块内容合成 400/847"）
3. 进度条始终显示（即使 pct=0 时也显示 indeterminate 状态）
4. 添加阶段流程指示器（当前阶段高亮，已完成阶段打勾）

### 修改文件清单

| 文件 | 变更内容 |
|------|---------|
| `wiki/pipeline_orchestrator.py` | 接受并分发 progress_callback |
| `wiki/nodes/classify.py` | classify_entities / classify_domains 报告进度 |
| `wiki/nodes/compose.py` | compose_leaf_modules_node 批次内报告进度 |
| `wiki/nodes/aggregate.py` | parent_aggregate / overview 报告进度 |
| `wiki/nodes/heal.py` | heal_pages 报告进度 |
| `wiki/nodes/links.py` | create_links 报告进度 |
| `wiki/service.py` | 传递 progress_callback 到 pipeline |
| `api/routes/wiki_task_routes.py` | _progress 回调增强（detail 字段） |
| `dashboard/src/components/wiki/WikiActiveTasks.tsx` | 扩展 phase 映射、显示 detail、阶段指示器 |
| `dashboard/src/i18n/zh.ts` | 新 phase 翻译 |
| `dashboard/src/i18n/en.ts` | 新 phase 翻译 |

---

## 执行顺序

1. **Batch 1** (后端进度增强): pipeline_orchestrator → 各 nodes → service → task_routes
2. **Batch 2** (前端进度展示): WikiActiveTasks + i18n
3. **Batch 3** (业务强制选择): Indexing.tsx + Repositories.tsx + index_routes

---

## 风险与缓解

| 风险 | 缓解措施 |
|------|---------|
| 当前有 wiki 任务在运行 | 进度增强是新增代码，不影响已运行任务 |
| 已索引但未绑定的仓库 | 保持兼容：business_id 可选，不传则走 default |
| 前端 build 后需部署 | 改完一起 deploy |
| progress_callback 异步开销 | 批量模块合成中每 10 个报告一次，非每个 |

---

## 成功标准

- [ ] Dashboard 创建业务后，索引页面自动显示业务选择器
- [ ] 未选业务时索引按钮 disabled + 提示文案
- [ ] 索引完成后仓库自动出现在对应业务的绑定列表
- [ ] Wiki 生成时进度条从 0% 开始递增，全程有意义的数字变化
- [ ] 能看到"域分类中"→"模块合成 40/847"→"父域聚合"→... 的阶段切换
- [ ] 生成完成后 dashboard 能直接查看 wiki 内容
