# Post-B1 Quality Gaps Fix Proposal

**Created:** 2026-04-19T14:49:09  
**Status:** ✅ APPROVED  
**Scope:** Backend retrieval quality + Dashboard UX  
**Context:** B1 Parent-Child Chunk 已完成，本提案解决剩余与主流 RAG 系统的差距

---

## Excluded Items (per user feedback)

| Item | Reason |
|------|--------|
| deep_search MCP registration | Agent 可自行多次调用 rag_query 实现多步检索 |
| 业务流/概念提取 (concept_extraction) | 核心场景不需要，LLM 成本高 |
| Observability (Prometheus/OTel) | 暂不实施 |
| 多语言支持 (C#/Ruby/PHP) | 暂不考虑 |

---

## Sprint 1: 检索质量快速提升 (Backend, ~2h)

这些是"翻开关"级别的改动，投入极小但对检索质量有显著影响。

### R1. 启用 Query Router (默认开启)

**现状**: `search_with_context` 中 `use_query_router=False`，意图感知权重未生效  
**修复**: 将 `use_query_router` 默认值改为 `True`  
**文件**: `query/hybrid_query.py`  
**风险**: Low — router 仅调整 keyword/semantic 权重比，不改变核心逻辑  
**注意**: child_chunks 路径 (`_search_with_child_chunks`) 当前跳过 router，后续优化

- [ ] R1.1: `search_with_context` 参数 `use_query_router` 默认改为 `True`
- [ ] R1.2: 验证 MCP `rag_query` 和 `/hybrid` API 均走 router 路径
- [ ] R1.3: 测试: 不同 query 类型的路由权重正确

### R2. Reranker 开关暴露到 MCP (但不强制默认开启)

**现状**: `RerankConfig.enabled = False`，reranker 已实现但需要用户手动启用  
**修复**: 不改默认值（reranker 需要额外模型加载），但在 MCP tool description 中说明如何启用  
**文件**: `api/mcp_server.py` tool description  
**风险**: None

- [ ] R2.1: 在 `rag_query` tool description 中说明 rerank 可通过配置启用
- [ ] R2.2: 在 README-DOCS 中记录 rerank 配置方法

### R3. MMR 多样性采样

**现状**: RRF fusion 后无多样性控制，同文件多 chunk 可能占满结果  
**修复**: 在 fusion 后添加 per-file diversity cap，最多返回 3 个来自同一文件的结果  
**文件**: `query/hybrid_query.py` 或 `search/fusion.py`  
**风险**: Low — 仅后处理过滤

- [ ] R3.1: 在 `_fuse_expansion_results` 或 `_attach_fusion_scores` 后添加 per-file cap
- [ ] R3.2: Cap 值可配置 (default=3)
- [ ] R3.3: 测试: 同文件 >3 结果时正确截断

### R4. 统一引用格式

**现状**: `matched_excerpt`, wiki Ask `sources`, `graph_context` 各有不同引用格式  
**修复**: 所有检索结果统一包含 `{file, start_line, end_line, name, type}` 基本字段  
**文件**: `query/hybrid_query.py`, `query/semantic_query.py`  
**风险**: Low — additive fields only

- [ ] R4.1: 确保 semantic_matches 始终包含 start_line + end_line
- [ ] R4.2: graph_context 已有 (HybridQueryService._ensure_graph_location_fields)
- [ ] R4.3: 测试

---

## Sprint 2: 搜索体验增强 (Dashboard, ~3h)

### U1. 搜索结果过滤器 (Cypher 层过滤)

**现状**: 仅有 entity_type、k、expand_depth 参数  
**修复**: 添加 repository、language 过滤器到搜索界面  
**实现方案**: **Cypher 层过滤** — 在 vector_search 和 keyword_search 的 Cypher 查询中注入 WHERE 条件，使 FalkorDB 在返回结果前就过滤，减少无效数据传输。  
**文件**: `store/falkordb_store.py`, `query/semantic_query.py`, `query/hybrid_query.py`, `main.py`, `api/mcp_server.py`, `dashboard/src/pages/SearchPage.tsx`  
**风险**: Medium — 修改核心查询方法签名

- [ ] U1.1: `FalkorDBStore.vector_search` 添加可选 `filters: dict` 参数，在 Cypher 中注入 `WHERE n.repository = $repo AND n.language = $lang` 条件
- [ ] U1.2: `FalkorDBStore.keyword_search` 添加可选 `repository`/`language` 过滤参数到 Cypher WHERE
- [ ] U1.3: `SemanticQueryService._search_by_label` 透传 filters 到 vector_search
- [ ] U1.4: `HybridQueryService.search_with_context` 接受 `repository`/`language` 参数并透传
- [ ] U1.5: 后端 `/hybrid` API 和 MCP `rag_query` 添加 `repository`/`language` 参数
- [ ] U1.6: SearchPage 添加 repository 下拉选择器 + language 过滤器
- [ ] U1.7: 测试: Cypher 过滤正确过滤结果

### U2. 搜索历史

**现状**: 仅 CommandPalette 有 quick search，主搜索页无历史  
**修复**: 在 SearchPage 添加搜索历史 (localStorage)，不做 entity 补全（CommandPalette 已有 quick search）  
**文件**: `dashboard/src/pages/SearchPage.tsx`  
**风险**: Low

- [ ] U2.1: 创建 `useSearchHistory` hook (localStorage, 最近 20 条)
- [ ] U2.2: 搜索框下方显示最近搜索词
- [ ] U2.3: 支持键盘上下键选择 + 点击填入

### U3. 搜索结果 Loading 骨架屏

**现状**: 搜索进行中区域为空白  
**修复**: 添加骨架屏占位  
**文件**: `dashboard/src/pages/SearchPage.tsx`  
**风险**: None

- [ ] U3.1: 创建 `SearchResultSkeleton` 组件
- [ ] U3.2: hybrid search pending 时显示 3-5 个骨架卡片

---

## Sprint 3: 图可视化 + 代码浏览 (Dashboard, ~4h)

### U4. 图布局优化 (dagre)

**现状**: grid + random jitter，大图混乱  
**修复**: 使用已安装的 dagre 库实现分层布局  
**文件**: `dashboard/src/components/GraphExplorer.tsx`  
**风险**: Medium — 布局算法变更

- [ ] U4.1: 引入 dagre 计算分层节点位置 (节点上限 200，超过提示缩小范围)
- [ ] U4.2: 根据 edge 类型选择 TB (继承) 或 LR (调用链) 方向
- [ ] U4.3: 保留现有 toggle/filter/minimap 功能

### U5. 代码语法高亮

**现状**: `<pre>` 纯文本显示代码片段  
**修复**: 使用轻量语法高亮库  
**文件**: 代码展示相关组件  
**风险**: Low

- [ ] U5.1: 安装 `prism-react-renderer` (轻量, ~15KB)
- [ ] U5.2: 替换 `<pre>` 为带语法高亮的代码块
- [ ] U5.3: 根据文件扩展名自动检测语言

### U6. 路由级代码分割

**现状**: 仅 Businesses 页面 lazy load  
**修复**: 对 GraphExplorer、Overview (Chart.js)、WikiPage 等重型页面添加 lazy()  
**文件**: `dashboard/src/App.tsx`  
**风险**: Low

- [ ] U6.1: 对 GraphExplorer, Overview, WikiPage, ArchitecturePage 添加 React.lazy
- [ ] U6.2: 添加 Suspense fallback Loading 组件
- [ ] U6.3: 验证首屏加载体积减小

---

## Sprint 4: 可访问性 + 小改进 (Dashboard, ~3h)

### U7. 表格键盘可操作性

**现状**: ArchitecturePage tr onClick 不可键盘触发  
**修复**: 使用 button/role 模式  
**文件**: `dashboard/src/pages/ArchitecturePage.tsx`  
**风险**: Low

- [ ] U7.1: 展开行使用 `<button>` 或 `role="button" tabIndex={0} onKeyDown`
- [ ] U7.2: 添加 aria-expanded 属性

### U8. 对话框 focus trap

**现状**: overlay 对话框 (Indexing, Settings) 无 focus trap  
**修复**: 使用 headlessui Dialog 或手动 focus trap  
**文件**: `dashboard/src/pages/Indexing.tsx` 等  
**风险**: Low

- [ ] U8.1: 对所有 modal 添加 focus trap
- [ ] U8.2: ESC 关闭 + focus 返回触发元素

### U9. API 速率限制

**现状**: 无限流  
**修复**: 添加简单的 per-IP 速率限制 middleware  
**文件**: `main.py`  
**风险**: Low

- [ ] U9.1: 使用 `slowapi` 或自定义 middleware 添加速率限制
- [ ] U9.2: 默认 60 req/min per IP for search endpoints
- [ ] U9.3: MCP endpoints 更宽松限制 (120 req/min)

### U10. 搜索结果导出

**现状**: 无法导出搜索结果  
**修复**: 添加"导出为 JSON"按钮  
**文件**: `dashboard/src/pages/SearchPage.tsx`  
**风险**: None

- [ ] U10.1: 添加 "Export JSON" 按钮
- [ ] U10.2: 下载当前搜索结果为 JSON 文件

---

## 优先级总结

| Sprint | 内容 | 预估耗时 | 影响 |
|--------|------|----------|------|
| Sprint 1 | 检索质量: Router + MMR + 引用格式 | ~2h | Agent 精度显著提升 |
| Sprint 2 | 搜索 UX: 过滤器 + 补全 + 骨架屏 | ~3h | 用户探索效率提升 |
| Sprint 3 | 图布局 + 代码高亮 + 代码分割 | ~4h | 视觉质量提升 |
| Sprint 4 | A11y + 限流 + 导出 | ~3h | 可靠性 + 无障碍 |

---

## 不在范围内

- deep_search MCP (Agent 可多次调用 rag_query)
- 业务流/概念提取 (成本高, 核心场景不需要)
- Observability (Prometheus/OTel, 暂不实施)
- 多语言 C#/Ruby/PHP (暂不考虑)
- Wiki 版本历史 (需要新的存储层, 后续迭代)
- 团队协作/注释功能 (需要用户系统, 后续迭代)
