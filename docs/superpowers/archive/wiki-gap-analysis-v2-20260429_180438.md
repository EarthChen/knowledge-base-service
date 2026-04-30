# Wiki 系统能力缺口分析 V2 — 多视角对标 DeepWiki / CodeWiki

> **创建时间:** 2026-04-29  
> **基于:** Sequential-Thinking 8 步结构化分析 + 代码逐项核实  
> **前置:** V1 gap analysis (`wiki-gap-analysis-deepwiki-codewiki.md`) + Pipeline Repair Sprint (✅ 已完成)  
> **对标:** [DeepWiki-Open](https://github.com/AsyncFuncAI/deepwiki-open) / [CodeWiki](https://github.com/FSoft-AI4Code/CodeWiki) (ACL 2026)

---

## 0. 已修复项汇总

### Pipeline Repair Sprint 修复

| 编号 | 缺口 | 修复 |
|------|------|------|
| P0-1 | `generate_business_wiki` mode 默认 `"structure"` | ✅ 改为 `"full"` |
| GAP-G | Tier-1 Backfill Trap（重生成退化） | ✅ 重排 tier 决策逻辑 |
| GAP-B | 全量路径缺少 glossary/parent_context | ✅ 注入轻量级 glossary + parent context |
| GAP-C | `trigger_enrichment` 为空操作 | ✅ 实装为后台异步任务 |
| GAP-E | 前端代码块无语法高亮 | ✅ 集成 react-syntax-highlighter |

### 代码核实确认已修复/部分修复

| 编号 | 缺口 | 状态 | 代码证据 |
|------|------|------|---------|
| G-P1 | 业务域信息未注入页面生成 prompt | ✅ **已修复** | `compose_page` 接收 `business_domain` → 写入 `node.properties` → `_entity_digest` L715-717 输出 `Business Domain: {bd}` 到 Tier-2 prompt |
| G-D4 | 增量路径与全量路径的上下文质量差 | ✅ **已修复** | `generate_incremental` L862-871 传递 `parent_context` + `glossary` 到 `compose_page` |
| G-P2 | Parent 聚合页缺少模块协作叙事 | ✅ **已修复** | `_PARENT_SYSTEM_PROMPT` L38-47 要求 Architecture Overview + Design Patterns + Mermaid 图；`compose_parent_page` L374-385 要求描述 child 协作 + `inter_child_edges` 注入 |
| G-A1 | MCP 工具缺少业务域导航 | ⚠️ **部分修复** | 已有 `wiki_get_tree(view=business_domain)` + `wiki_get_domain_overview` 工具；但缺少独立的 `wiki_list_domains` 列表工具 |
| G-D1 | LLM 生成内容缺少结构化章节深度 | ⚠️ **部分修复** | `_STRUCTURED_SECTIONS_*` L57-81 已有 Purpose/Components/Integration/DataFlow/Design Decisions；但缺少 "How it works" 执行流、"Usage Examples" 示例代码 |
| G-T3 | 叶子节点内容深度不足 | ⚠️ **部分修复** | Function 模板有 Parameters & Return + Usage Context + Design Notes；但缺少设计模式识别、集成点、使用场景示例 |
| G-D2 | 图属性未全量注入 prompt | ⚠️ **部分修复** | `annotations` / `semantic_roles` 已注入 L721-730；`parameters`/`return_type` 仅在 class methods 列表中以截断字符串出现；**`neighbor_tier` 完全缺失** |
| G-P4 | 质量评分 UI 展示不足 | ⚠️ **部分修复** | `WikiQualityScoreCard` 有因子分解条形图；但 badge 仅显示分数，无 "为什么低质量" 解释和改进建议 |
| G-D5 | Module 级文件头注释未充分利用 | ⚠️ **部分修复** | Python module docstring 已提取 L683-700；非 Python 语言仅提取 class 前的 block comment，file header 覆盖窄 |

---

## 1. 产出物质量对比矩阵

| 维度 | DeepWiki | CodeWiki | 当前系统 | 差距评估 |
|------|---------|---------|---------|---------|
| 章节结构规范 | ★★★★★ | ★★★ | ★★★ | **中** |
| 图表丰富度 | ★★★★★ | ★★★ | ★★ | **大** |
| 业务语言表达 | ★★★★ | ★★ | ★★★ | **小** |
| 代码细节深度 | ★★★ | ★★★★ | ★★★ | 小 |
| 交互体验 | ★★★★ | ★★★ | ★★★ | 中 |
| 增量更新 | ★★★ | — | ★★★★ | **领先** |
| 多视图切换 | ★★★ | ★★ | ★★★★ | **领先** |
| Agent 集成 | ★★★ | ★★ | ★★★★★ | **领先** |
| 质量保证体系 | ★★★ | ★★ | ★★★★ | **领先** |
| 业务域检测 | ★★ | ★ | ★★★★ | **领先** |

### 核心洞察

> **经过 Pipeline Repair Sprint 和 Business Intelligence 注入后，当前系统在业务语言表达和章节结构上已有显著改善（从 ★★ 提升到 ★★★），但 LLM 语义图表生成仍是最大短板。**

---

## 2. 仍存在的缺口（经代码核实）

### P0 — 关键路径（最高 ROI）

#### G-D3 / G-DW3: 缺少 LLM 驱动的语义图表 ★★★★ | NOT FIXED

**现状:** `_build_diagrams` (L1063-1084) 仅使用确定性生成器（`generate_dependency_graph`, `generate_class_diagram`, `generate_call_flowchart`）。`diagram_gen.py` 模块注释明确标注 "Deterministic Mermaid diagram generation from graph nodes and edges"。

**缺少:**
- 序列图（Sequence Diagram）— 关键调用链的时序
- 数据流图（Data Flow）— 数据如何在模块间流转
- 状态图（State Machine）— 状态转换逻辑

**对标:** DeepWiki 每章节 LLM 生成语义 Mermaid；CodeWiki 多模态综合。

---

#### G-D2 (残余): `neighbor_tier` 未注入 + 结构化 params/returns 不完整 ★★

**现状:** `_entity_digest` 中 `annotations` / `semantic_roles` / `business_domain` 已注入。但：
- **`neighbor_tier`** — `data_collector._annotate_neighbor_tiers` 计算后 composer 完全忽略
- **`parameters` / `return_type`** — 仅在 class methods 列表中以 `str(...)[:100]` 截断字符串出现，主实体（Function 节点）不单独输出结构化参数信息

---

#### G-T1: 业务视图与代码视图未差异化 ★★★ | NOT FIXED

**现状:** `WikiStructurePlanner.plan()` (L44-77) 仅按 `scope_type`（repo/module/class）分支，无 `business_domain` vs `code_structure` 视图差异逻辑。前端通过 `wiki_get_tree(view=...)` 提供视图切换，但后端树规划完全相同。

**期望:** business 视图按"业务域 > 业务能力 > 实现组件"组织；code 视图按"模块 > 子模块 > 文件/类"。

---

### P1 — 重要提升

#### G-D1 / G-T3 (残余): 章节模板深度和叶子内容 ★★

**现状:** `_STRUCTURED_SECTIONS_*` 已有 Purpose/Components/Integration/DataFlow/Design Decisions 5 大节。

**仍缺:**
- Module/Class 无 "How it Works"（执行流程步骤描述）
- Function 无 "Usage Examples"（代码示例）
- 无明确 "Design Pattern Identification"（设计模式识别）要求

---

#### G-A2: 缺少"代码与业务映射"反向查询 ★★★ | NOT FIXED

**现状:** Wiki MCP 工具集中无专用 "业务能力 → 实现模块" 反向查询工具。Agent 只能通过 `wiki_search` 文本搜索间接获取，无法结构化地问"认证功能由哪些模块实现"。

---

#### G-T2: importance_tier 分配缺少业务感知 ★★ | NOT FIXED

**现状:** `ImportanceScorer.compute_score()` (importance_scorer.py L27-67) 仅使用图指标（in_degree, out_degree, children_count, code_lines, has_subclasses），不考虑 `business_domain`。

---

#### G-DW1: 智能目录结构规划 ★★ | NOT FIXED

**现状:** `WikiStructurePlanner` 基于 CONTAINS 关系递归构建树，无 LLM 调用，无语义聚类。

---

### P2 — 体验优化

#### G-P5: 增量更新用户体验 ★★ | NOT FIXED

**现状:** `WikiIncrementalTrigger` 仅 toast 通用成功消息；`generate_incremental` API 返回聚合数（`pages_regenerated` 计数），但无具体更新页面路径列表；UI 无"哪些页面更新了"的展示。

---

#### G-P3: 缺少"功能分布热力图" ★★ | NOT FIXED

**现状:** Dashboard 仅有节点/边分布饼图（`Overview.tsx`），无基于业务能力的横切视图或热力图。

---

#### G-A4: 影响分析缺少"业务影响"维度 ★★ | NOT FIXED

**现状:** `_handle_wiki_impact` → `CompactFormatter.format_impact()` 返回 `pages_affected` / `entities_affected` / `trigger`，不包含 `business_domain` 影响信息。

---

#### G-P4 (残余): 质量评分详情 ★

**现状:** `WikiQualityScoreCard` 有因子分解视图；Badge 仍为纯数字。缺少 "为什么低质量" 的叙述性解释和改进建议。

---

#### G-D5 (残余): 非 Python 文件头注释覆盖窄 ★

**现状:** Python module docstring 提取良好；Java/JS/TS/Go 仅提取 class 前的 block comment（`_extract_file_header_comment` L704-707），不提取 package 声明前的 license/header。

---

### P3 — 未来版本

| # | 缺口 | 状态 | 描述 |
|---|------|------|------|
| G-DW4 | 多仓库前端聚合视图 | NOT FIXED | CrossRepoBusinessDomainPlanner 存在但前端无聚合视图 |
| G-CW1 | 协作编辑审核流程 | NOT FIXED | 仅单人编辑 |
| G-CW2 | 代码切片内联展示 | NOT FIXED | source_location 仅跳转链接 |
| G-CW3 | 代码变更与 Wiki 版本关联 | NOT FIXED | 版本历史记录 Wiki 变更非代码变更 |
| G-A5 | 代码生成指导知识显式化 | NOT FIXED | 无设计模式/规范可查询格式 |
| G-T4 | 跨树分支关联可视化 | NOT FIXED | 树形严格层级化 |
| G-P6 | 页面间语义关联推荐 | NOT FIXED | Wikilink 基于文本匹配 |
| G-T5 | 树形 Wiki 完整性检查 | NOT FIXED | 无孤立节点检测 |

---

## 3. 系统独特优势（竞争壁垒）

这些能力是 DeepWiki 和 CodeWiki **均不具备**的：

1. **图数据库知识表示** — FalkorDB 存储代码实体与关系，提供结构化 ground truth
2. **增量更新** — graph-diff 驱动的精准变更检测，避免全量重建
3. **业务域自动分类** — CrossRepoBusinessDomainPlanner 的跨仓库业务域识别
4. **业务域注入 LLM prompt** — `business_domain` 已注入 Tier-2 生成上下文（✅ 已验证）
5. **质量保证体系** — 置信度评分 + 矛盾检测 + 主张追踪 + 记忆演化
6. **Agent MCP 集成** — wiki_search/explain/navigate/qa/impact/snapshot + domain 工具
7. **双视图模式** — business_domain 和 code_structure 的切换
8. **页面生命周期** — 版本历史 + 人工编辑 + 软删除 + enrichment pipeline
9. **Parent 聚合质量** — 要求子模块协作叙事 + 架构图 + 设计模式（✅ 已验证）

---

## 4. 优先级路线图（更新后）

### P0 — 关键路径（1-2 周）

| # | 缺口 | 描述 | 预估 |
|---|------|------|------|
| 1 | G-D3/G-DW3 | LLM 语义图表生成（序列图、数据流图、状态图） | 3d |
| 2 | G-T1 | 业务/代码视图树形结构差异化 | 2d |
| 3 | G-D2 残余 | `neighbor_tier` 注入 + Function 节点结构化 params | 1d |

### P1 — 重要提升（2-4 周）

| # | 缺口 | 描述 | 预估 |
|---|------|------|------|
| 4 | G-A2 | 代码-业务反向查询 MCP 工具 | 2d |
| 5 | G-D1/G-T3 残余 | 章节模板补充 How it Works / Usage Examples / Pattern ID | 1d |
| 6 | G-T2 | importance_tier 业务域感知 | 1d |
| 7 | G-DW1 | WikiStructurePlanner 引入 LLM 语义分组 | 3d |

### P2 — 体验优化（4-8 周）

| # | 缺口 | 描述 | 预估 |
|---|------|------|------|
| 8 | G-P5 | 增量更新变更页面列表 + UI 提示 | 2d |
| 9 | G-P3 | 功能分布热力图/业务能力横切视图 | 3d |
| 10 | G-A4 | wiki_impact 增加 business_domain 影响维度 | 2d |
| 11 | G-P4 残余 | 质量低分原因叙述 + 改进建议 | 2d |
| 12 | G-D5 残余 | 非 Python 文件头注释扩展提取 | 2d |
| 13 | G-CW2 | 代码切片内联展示 | 3d |

### P3 — 未来版本

| # | 缺口 | 描述 | 预估 |
|---|------|------|------|
| 14 | G-DW4 | 多仓库前端聚合视图 | 3d |
| 15 | G-CW1 | 协作编辑审核流程 | 5d |
| 16 | G-CW3 | 代码变更与 Wiki 版本关联 | 3d |
| 17 | G-A5 | 代码生成指导知识显式化 | 3d |
| 18 | G-T4 | 跨树分支关联可视化 | 2d |
| 19 | G-P6 | 页面间语义关联推荐 | 2d |
| 20 | G-T5 | 树形 Wiki 完整性检查 | 1d |

---

## 5. 建议下一步

1. **P0-1 (G-D3/G-DW3) 最优先:** LLM 语义图表是用户感知最强的改进，且当前与 DeepWiki 差距最大
2. **P0-2 (G-T1) 并行推进:** 业务/代码视图差异化是产品定位的核心差异点
3. **持续强化竞争壁垒:** 增量更新 + 质量体系 + Agent MCP 是竞对短期无法追赶的护城河
