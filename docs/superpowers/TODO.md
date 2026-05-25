# 待办事项与改进建议

**Created:** 2026-05-24
**Last Updated:** 2026-05-25 (Round 10 — 管线性能+质量优化)

---

## 一、未实现设计提案

### 1. Parent Domain Overview Agent 重构 [P2]

将 `compose_parent_pages_node` 重构为 Agent 模式（`ParentDomainDocAgent`），继承 `DocOrchestrator`。

### 2. Graph Reviewer Agent [P2]

在 `finalize_node` 前加 `graph_review_node`，运行确定性 Cypher 检查（悬空引用、孤立节点）。

### 3. Git Diff 图叠加层 [P2]

Graph Explorer 中叠加当前工作区变更的可视化。

### 4. Post-Commit Hook 安装器 [P3]

一键安装 git hook 保持图新鲜。后端增量索引基建已就绪（`POST /api/v1/index mode=incremental`、webhook、SyncScheduler），仅缺本地 hook 脚本模板 + 安装器 CLI。

### 5. Persona-Adaptive UI [P3]

根据用户角色调整 Wiki 展示深度。

### 6. 多视图 Wiki 结构 [P3]

当前 Wiki 仅有"业务域视图"。构想增加仓库视图 (`/__repos__/`) 和技术文档视图 (`/__tech__/`)。

### 7. Cursor 插件形态 [P3]

薄客户端调用 HTTP/MCP。

---

## 二、域分类精度优化 ✅

**全部已修复。** 详见 `docs/REMAINING-WORK.md`。

---

## 三、管线质量与性能 ✅

**全部已修复。** 详见 `docs/REMAINING-WORK.md`。

性能优化（Batch AH）：
- ✅ `classify_architecture_layers` 移至 `compose_leaf_modules` 之后（解除不必要的阻塞）
- ✅ 批量 Cypher 查询：5600 次 → 3 次（annotation + fan_in + fan_out）

关键修复（Batch AK/AL）：
- ✅ 架构层持久化修复 — `_ALLOWED_PROPERTIES` 白名单缺失导致分类永远无法写入图数据库
- ✅ `persist_classification` compound-key 查找 — 与 classify 复合键对齐
- ✅ LLM rate limiter 释放锁后 sleep — 消除并发串行化瓶颈
- ✅ Pipeline `ainvoke()` 顶层错误边界 — 未处理节点异常不再崩溃整个管线

性能+质量优化（Batch AM/AN）：
- ✅ 探索轮次 tier-aware — SKELETON 8→2, STANDARD 8→5, CORE 保持 8（减少 ~30% explore LLM）
- ✅ `module_compose_concurrency` 默认 3→6（leaf compose 阶段加速 ~2×）
- ✅ FalkorDB `thread_pool_size` 默认 4→8 并暴露配置
- ✅ Mermaid 图基于真实调用关系 — 替换线性链占位符，使用 `module_call_edges`
- ✅ quality_gate → heal hints 传递 — heal 策略直接使用 gate 的 per-dimension hints

---

## 四、前端 Dashboard 质量 ✅

**全部已修复。** 详见 `docs/REMAINING-WORK.md`。

关键修复（Batch AK/AL）：
- ✅ Settings dirty 保护 — 后台 refetch 不再覆盖未保存编辑
- ✅ 数字字段 min/max 校验 — Pipeline 并发配置空值/越界值阻止保存
- ✅ `useWikiEditSession` pageUid 重置 — 切换页面不再泄露上一页的流式状态

非阻塞改进：
- P2: `text-gray-400` 对比度 — 需设计方案（~440 处，待设计规范后批量替换）
- P2: API client Zod 运行时校验（建议增量引入，从高风险 endpoint 开始）
- ~~P2: ErrorBoundary 全覆盖~~ ✅ Batch AI — 13 lazy pages 均已包裹路由级 ErrorBoundary

---

## 五、架构优化 ✅

**全部已修复。** 详见 `docs/REMAINING-WORK.md`。

安全修复（Batch AL）：
- ✅ `/wiki/quick` EDITOR 角色检查 — 防止 VIEWER 触发昂贵的 wiki 生成
- ✅ Domain 路由 business 绑定校验 — 8 个 mutating 路由改用 `Depends(get_effective_business_id)`

非阻塞改进：
- ~~P2: `except Exception` 审计收窄~~ ✅ Batch AI — Top 5 高风险站点已修复
- P2: 超时/限制统一配置迁移（部分已中心化，建议按需渐进迁移）

---

## 六、管线性能与质量进阶优化（延后）

以下优化需要更多设计或评估，建议在当前优化效果验证后再实施。

### 1. DocOrchestrator 统一 [P2]

将 `use_orchestrator_template` 默认改为 `True`，统一 DomainDocAgent 的生成路径。当前 `generate_with_iterations()` 有更丰富的 guardrails/timeouts，需要将这些能力迁移到 DocOrchestrator 模板后再切换。

### 2. Agent semantic_search 查询扩展 [P2]

当前 `WikiPageAgent.semantic_search` 禁用了 `query_expansion`。启用 `expand_depth=1` + graph expansion 可提升召回率，但也会增加工具返回数据量、占用工作记忆。建议仅对 CORE tier 启用。

### 3. 工作记忆动态调整 [P3]

当前固定 200K chars 上限。大域探索可能驱逐早期发现。可根据 tier 动态调整：CORE 300K，STANDARD 200K，SKELETON 100K。需要评估 LLM context window 限制。

### 4. generate_titles 批量化 [P3]

当前每个 module tree 节点 1 次 LLM 调用。可以将 10-20 个节点合并为 1 次 LLM 调用，减少请求数但需要处理 JSON 批量输出的解析可靠性。

### 5. Graph Reviewer Node [P2]

在 `finalize_node` 前加 `graph_review_node`，运行确定性 Cypher 检查（悬空引用、孤立节点），复用 `wiki/lint.py` 查询层。

---

*本文档作为统一的待办追踪入口。已完成项归档见 `docs/REMAINING-WORK.md`。*
