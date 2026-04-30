# Wiki Gap Analysis V3 — KB Service vs DeepWiki vs CodeWiki

> **Date:** 2026-04-29  
> **Scope:** Post Pipeline Repair + Content Depth Enhancement Sprint  
> **Method:** sequential-thinking 多视角分析 (开发者、产品、Agent)  
> **Commits analyzed:** `298cbde` → `609e20d` (10 commits)

---

## 1. Executive Summary

KB Service 在 **工程化能力** 上显著领先 DeepWiki 和 CodeWiki：

- **增量更新**、**质量管理**、**Agent MCP 集成**、**搜索导航**、**多视图**、**导出** 均为领先或独有能力

主要落后点集中在 **"内容生成智能度"**：
1. **图表丰富度** (P0) — 缺少独立的 LLM 语义图表生成流水线
2. **结构规划智能度** (P1) — WikiStructurePlanner 是机械图遍历而非 LLM 语义分类

---

## 2. 能力矩阵 — 三方对比

| 维度 | KB Service | DeepWiki | CodeWiki | 判定 |
|------|-----------|----------|----------|------|
| **内容生成 Tier** | 3级 (summary/LLM/structural) + 2轮富化 | 全页 LLM | 多代理 DP 分解 | DeepWiki 叙事最强 |
| **图表生成** | 6种确定性 + LLM正文引导 | LLM语义Mermaid (序列/状态/数据流) | 多模态综合 | **落后** |
| **结构规划** | 机械 CONTAINS 图遍历 | LLM 语义分类 TOC | DP 入口点驱动 | **落后** |
| **多视图** | business_domain / code_structure / system_overview | 无 | 无 | **领先** |
| **增量更新** | webhook + diff + scheduler + SSE | 无 | 无 | **强大领先** |
| **搜索** | 混合 (图谱+向量+FTS) + RRF + CJK | 基础 | 无 | **领先** |
| **代码导航** | 调用链+影响+PR分析+IDE链接 | 文件级链接 | 入口点链式文档 | **领先** |
| **质量管理** | 评分+置信+矛盾+heal+版本+注解+lint | 无 | CodeWikiBench (一次性) | **强大领先** |
| **Agent MCP** | 16+ 工具 | per-page chat | 无 | **强大领先** |
| **业务域分类** | 跨仓库 LLM 分类 + 域概览 | 全局语义分组 | 无 | **领先** |
| **记忆学习** | MemoryLoop + tiers + inject | 无 | 无 | **独有** |
| **导出** | Markdown/ZIP/Obsidian/MkDocs/Git推送/离线包 | 在线查看 | 文件系统 | **强大领先** |

---

## 3. 视角分析

### 3.1 开发者视角

#### 优势
- **代码导航深度**: 调用链追踪 + PR 影响分析 + IDE 深度链接 — 远超对手
- **增量同步**: webhook 触发后自动更新，SSE 实时通知 — 对手完全没有
- **混合搜索**: 图谱+向量+FTS 三路融合，CJK 分词 — 对手基础或没有
- **源码位置**: SourceLocation (file, line, repo, FQN) 精确定位

#### 差距
| ID | 差距 | 对标 | 现状 | 影响 |
|----|------|------|------|------|
| G-D3 | 缺少 LLM 语义图表 (序列图/状态图/数据流) | DeepWiki | 有6种确定性图 + LLM正文引导 | **P0** |
| G-DW1 | 结构规划=机械遍历，无LLM语义分类 | DeepWiki | WikiStructurePlanner: CONTAINS walk | **P1** |
| G-CW2 | 缺少内联代码片段展示 | CodeWiki | 仅 source:// 链接 | P2 |
| G-D5r | 非Python语言文件头提取较弱 | CodeWiki | tree-sitter 支持多语言但 docstring 提取偏 Python | P2 |

### 3.2 产品视角

#### 优势
- **多视图切换**: 业务域 vs 代码结构 vs 系统概览 — 唯一有此能力
- **质量可视化**: 评分卡+覆盖率+置信度+矛盾检测+过时提醒
- **导出生态**: 支持 Obsidian / MkDocs / Git / ZIP — 灵活分发
- **版本管理**: 版本历史 + Diff 对比 + 编辑协作
- **业务流图**: WikiBusinessFlowGraph 可视化

#### 差距
| ID | 差距 | 对标 | 现状 | 影响 |
|----|------|------|------|------|
| G-D3 | 图表丰富度是质量的最直观感知 | DeepWiki | 确定性图 ≠ 语义图 | **P0** |
| G-DW1 | TOC 组织质量影响浏览体验 | DeepWiki | 按文件结构而非语义分组 | **P1** |
| G-T2 | importance_tier 不考虑 business_domain | 自身 | 跨域核心模块可能被降级 | P1 |
| G-P5 | 增量后缺少"什么变了"可视化 | 自身 | 前端只有通知无 changelog | P2 |
| G-P4r | 质量 Badge 缺少叙事解释 | 自身 | 只有数字没有"为什么/如何改善" | P2 |

### 3.3 Agent 视角

#### 优势
- **MCP 工具集**: 16+ 工具覆盖生成/查询/搜索/导出/分析/快照
- **上下文能力**: ask_about_code (混合检索 + 推理路径), wiki_get_snapshot
- **自动化**: webhook + scheduler + 增量生成
- **记忆循环**: Q&A 持久化 + 衰减分层 + 注入 LLM prompt

#### 差距
| ID | 差距 | 对标 | 现状 | 影响 |
|----|------|------|------|------|
| G-A2 | 缺少"业务能力→实现模块"反向查找工具 | 自身 | 无 wiki_find_implementing_modules | **P1** |
| G-A1r | 没有专门的 wiki_list_domains 工具 | 自身 | 通过 wiki_get_tree(view=business_domain) 间接实现 | P2 |
| G-P3 | 业务维度的影响分析 | 自身 | analyze_impact 仅代码维度 | P2 |

---

## 4. 差距优先级总表

| 优先级 | ID | 差距描述 | 对标 | 预估工作量 |
|--------|----|---------|------|-----------|
| **P0** | G-D3 | 独立 LLM 语义图表生成流水线 (sequence/state/dataflow) | DeepWiki | 3-5天 |
| **P1** | G-DW1 | 结构规划 LLM 语义分类/聚类 | DeepWiki/CodeWiki | 3-5天 |
| **P1** | G-A2 | 业务能力→实现模块反向查找 MCP 工具 | 自身 | 1天 |
| **P1** | G-T2 | importance_tier 纳入 business_domain 权重 | 自身 | 1-2天 |
| **P2** | G-P5 | 增量更新"什么变了"可视化 | 自身 | 2天 |
| **P2** | G-P4r | 质量 Badge 叙事解释 | 自身 | 1天 |
| **P2** | G-D5r | 非Python语言文件头提取增强 | CodeWiki | 2天 |
| **P2** | G-CW2 | 内联代码片段展示 | CodeWiki | 2-3天 |
| **P2** | G-A1r | wiki_list_domains 专用 MCP 工具 | 自身 | 0.5天 |
| **P2** | G-P3 | 业务维度影响分析 | 自身 | 2天 |

---

## 5. 已修复项 (本轮 Sprint 成果)

### Pipeline Repair Sprint (10 commits)
- [x] `mode="structure"` → `"full"` 默认值修复
- [x] Tier-1 backfill trap 消除
- [x] glossary + parent_context 注入 full-gen 叶页
- [x] trigger_enrichment 实装 (异步后台任务 + 并发锁)
- [x] 语法高亮 (react-syntax-highlighter)
- [x] enrichment 语言动态化 (graph 读取而非硬编码)
- [x] glossary 查询排序

### Content Depth Enhancement Sprint (4 commits)
- [x] 接入 layered_architecture + data_flow 图表生成器 (MODULE: 3种, CLASS: 2种)
- [x] 章节模板增强: "How it Works" + Usage Examples + Mermaid 指导
- [x] _entity_digest 增强: neighbor_tier + 结构化 parameters/return_type
- [x] 前端 WikiDiagramSection 渲染结构化图表

### 此前已修复 (Business Intelligence Sprint)
- [x] business_domain 注入 LLM prompt
- [x] Parent 聚合页质量 (inter_child_edges + 协作叙事)
- [x] 增量路径 glossary/parent_context 注入

---

## 6. 建议下一步

### 短期 (1-2 周)
1. **G-D3 (P0)**: 设计 LLM 语义图表生成流水线
   - 为 MODULE 页面生成序列图 (主要调用流)
   - 为 CLASS 页面生成状态图 (如果有状态变化) 或交互序列图
   - 独立的 diagram generation step，结果存入 `WikiPage.diagrams`

2. **G-A2 (P1)**: 新增 `wiki_find_implementing_modules` MCP 工具
   - 基于 `business_domain` 属性反向查找

### 中期 (2-4 周)
3. **G-DW1 (P1)**: 结构规划引入 LLM 语义聚类
   - 在 `WikiStructurePlanner.plan()` 中可选 LLM 分组
   - 对大模块 (>20 children) 启用语义子分组

4. **G-T2 (P1)**: importance_tier 权重纳入 business_domain 跨引用数

### 长期 (1-2 月)
5. G-P5, G-CW2, G-D5r 等 P2 项
