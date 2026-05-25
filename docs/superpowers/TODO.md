# 待办事项与改进建议

**Created:** 2026-05-24
**Last Updated:** 2026-05-25 (Round 6 — §二/§三/§四/§五 全部 P1/P2/P3 已清零)

---

## 一、未实现设计提案

### 1. 多视图 Wiki 结构 [P3]

当前 Wiki 仅有"业务域视图"（`/__domains__/`）。构想三种视图：

| 视图 | 路由前缀 | 使用场景 |
|------|---------|---------|
| **业务域视图** | `/__domains__/` | 理解业务功能、跨仓库业务流 |
| **仓库视图** | `/__repos__/` | 代码导航、仓库级架构理解 |
| **技术文档** | `/__tech__/` | 技术决策参考、新人 onboarding |

### 2. Parent Domain Overview Agent 重构 [P2]

将 `compose_parent_pages_node` 重构为 Agent 模式（`ParentDomainDocAgent`），继承 `DocOrchestrator`。

### 3. 非代码文件轻量解析 [P2]

`indexer/languages/` 新增 Dockerfile/K8s YAML/Protobuf 轻量 parser。

### 4. Graph Reviewer Agent [P2] *(借鉴 UA)*

在 `finalize_node` 前加 `graph_review_node`，运行确定性 Cypher 检查（悬空引用、孤立节点）。

### 5. Persona-Adaptive UI [P3] *(借鉴 UA)*

根据用户角色调整 Wiki 展示深度。

### 6. Git Diff 图叠加层 [P2] *(借鉴 UA)*

Graph Explorer 中叠加当前工作区变更的可视化。

### 7. 可提交图快照 (Onboarding) [P2] *(借鉴 UA)*

图导出为 JSON 文件提交到 Git，降低 onboarding 成本。

### 8. Post-Commit Hook 安装器 [P3] *(借鉴 UA)*

一键安装 git hook 保持图新鲜。

### 9. 前端曝露语言概念 [P3] *(借鉴 UA)*

在 Graph Explorer / 节点面板中显示编程模式概念。

---

## 二、域分类精度优化 ✅

**全部已修复。** 详见 `docs/REMAINING-WORK.md` (Batch A → AD, 共 30+ 项)。

仅保留 1 项非阻塞改进：
- P3: 嵌入生成仅进程内 LRU 缓存（需持久化层，暂不处理）

---

## 三、管线质量与性能 ✅

**全部已修复。** 详见 `docs/REMAINING-WORK.md` (Batch A → AE, 共 40+ 项)。

仅保留 1 项非阻塞改进：
- P3: 嵌入跨运行复用（需持久化层，暂不处理）

---

## 四、前端 Dashboard 质量 ✅

**全部已修复。** 详见 `docs/REMAINING-WORK.md` (Batch G → AF, 共 40+ 项)。

仅保留非阻塞改进：
- P2: `text-gray-400` 对比度 — 需设计方案确定替代色
- P2: API client 无运行时类型校验 — 需 Zod schema 规划
- P2: ErrorBoundary 覆盖 — 需统一 error UI 设计
- P3: Suspense `aria-live`/`aria-busy`
- P3: `prefers-reduced-motion` 处理
- P3: ChartJS register 提取
- P3: FileExplorer h1 层级

---

## 五、架构优化 ✅

**全部已修复。** 详见 `docs/REMAINING-WORK.md` (Batch AG)。

仅保留非阻塞改进：
- P2: 广泛 `except Exception` 吞异常 — 需逐模块审计收窄
- P2: 超时/限制分散于 env 而非 `AppWikiFlags` — 需统一配置迁移

---

## 六、Understand-Anything 对比总结

### KB Service 优势

| 维度 | KB Service | UA |
|------|-----------|-----|
| **检索** | 3-way RRF + 可选 reranker + 图扩展 | 图内模糊/语义搜索 |
| **存储** | FalkorDB 属性图 + 向量索引 (同一存储) | JSON 文件 |
| **Wiki 管线** | LangGraph 20+ 节点 + 质量门 + heal 循环 | 摘要+tour (无质量迭代) |
| **Agent 引擎** | 统一 `run_agent_loop` + guardrails + 工具分层 | slash command 编排 |
| **多租户** | `kb_{business_id}` 隔离图 | 单仓库 JSON |
| **平台覆盖** | HTTP API + MCP + 仪表盘 | 15+ IDE 插件 |

### 可借鉴 UA 模式 (新功能提案)

| 优先级 | 模式 | 备注 |
|--------|------|------|
| **P1** | 图谱 JSON 导出 + Docs-as-Code | 已列入 §一.7 |
| **P1** | Post-commit 一键增量 Hook | 已列入 §一.8 |
| **P1** | Diff Impact 产品化工作流 | 已列入 §一.6 |
| P2 | Graph Reviewer Agent | 已列入 §一.4 |
| P2 | 分析进度 + 部分结果策略 | 节点级 checkpoint 暴露给 UI |
| P2 | 节点描述多语言 | 索引阶段按目标语言生成 |
| P3 | Cursor 插件形态 | 薄客户端调用 HTTP/MCP |
| P3 | 语义批处理 | 按 import 邻居聚批降低 token 成本 |

---

*本文档作为统一的待办追踪入口。已完成项归档见 `docs/REMAINING-WORK.md`。*
