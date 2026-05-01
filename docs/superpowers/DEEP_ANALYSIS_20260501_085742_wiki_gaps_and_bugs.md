# Wiki 系统深度分析报告 — 代码缺陷、能力差距与竞品借鉴

> **状态**: 已完成
> **创建**: 2026-05-01 08:57
> **方法**: 3 个并行探索代理 + sequential-thinking 10 轮深度分析
> **范围**: 后端 119 个 wiki 模块 + 前端 102 个 wiki 组件/hooks + 1403 个测试
> **对标项目**: [DeepWiki-Open](https://github.com/AsyncFuncAI/deepwiki-open) (15.3K ⭐)、[CodeWiki](https://github.com/FSoft-AI4Code/CodeWiki) (ACL 2026)

---

## 1. Executive Summary

KB Service 在基础设施层面（增量更新、多视图、Agent MCP、记忆演化、导出生态、质量保证架构）远超竞品。但在 **"内容生成智能度"** 这个用户感知最直接的核心维度上，与 DeepWiki 和 CodeWiki 存在明显差距。

**三大核心差距:**

| 维度 | 状态 | 影响 |
|------|------|------|
| 内容质量上限 | 无 CoT、无叙事性、无层级深度、无代码上下文 | 用户感知的核心价值 |
| 运行时稳定性 | 11 个确认的运行时 Bug (5 后端 + 6 前端) | 功能可靠性 |
| 前端体验一致性 | i18n 破碎、审批无反馈、模块计数错误 | 产品打磨度 |

**数字摘要:**

| 类别 | 数量 | 状态 |
|------|------|------|
| 确认的运行时 Bug | **11** (5 后端 + 6 前端) | ✅ **11/11 全部已修复** |
| 架构问题 | **10** | ✅ **10/10 全部已修复** |
| 产品能力缺口 | **7** | 🟡 P1/P2/P4/C1/C2/C3 已完成，P5 取消（企业级无需即时体验），P3/C4 待处理 |
| 技术能力缺口 | **8** | 🟡 T1-T6 已完成，T7/T8 待处理 |
| Agent 能力缺口 | **6** | 🟡 A2/A3/A4/A6 取消（MCP 定位为纯查询层），A1/A5 待处理 |
| 前端体验问题 | i18n + SSE + AskPanel | ✅ 全部已修复 |
| 测试补全 | 后端 +38 测试 + 前端 +69 测试 | ✅ **全部关键缺口已补全** |

---

## 2. P0 — 运行时 Bug 清单

### 2.1 后端运行时缺陷 (5 个)

#### BUG-B1: ~~Diagram dict shape 不一致导致 KeyError~~ ✅ 已修复

- **位置**: `pipeline_nodes.py:396-404` → `models.py:353-358`
- **根因**: `compose_pages_node` 生成 diagram dict 用 key `diagram_type`，但 `WikiPage.from_dict` 期望 key `type`
- **修复**: 将 `"diagram_type"` 改为 `"type"` (1 行修复)
- **验证**: `pytest tests/wiki/test_pipeline_e2e.py -x -q` 通过

---

#### BUG-B2: ~~heal_pages_node 嵌套域上下文缺失~~ ✅ 已修复

- **位置**: `pipeline_nodes.py:509-516`
- **修复**: 新增 `_find_domain_in_tree()` 递归辅助函数，替代顶层遍历

---

#### BUG-B3: ~~synthesize_overviews_node 只用顶层域~~ ✅ 已修复

- **位置**: `pipeline_nodes.py:574-578`
- **修复**: 新增 `_flatten_all_domains()` 递归辅助函数，收集所有层级的域

---

#### BUG-B4: ~~detect_reorg 模块计数不准~~ ✅ 已修复

- **位置**: `pipeline_nodes.py:122-127`
- **修复**: 新增 `_count_modules_in_domain_tree()` 递归辅助函数

---

#### BUG-B5: ~~resolved_links 未被持久化~~ ✅ 已修复

- **位置**: `service.py` — 新增 `_persist_resolved_pipeline_wikilinks` 方法
- **修复**: 在页面持久化后，通过确定性 UID 规则 (`WikiPage:{business_id}:{path}`) 映射 path → uid，调用 `add_wiki_reference_edge` 创建 `WIKI_REFERENCES` 边
- **验证**: `test_business_wiki_resolved_links.py` 6 passed

---

### 2.2 前端运行时缺陷 (6 个)

#### BUG-F1: ~~AskPanel repository 参数错误~~ ✅ 已修复

- **位置**: `WikiToolPanel.tsx:250`
- **修复**: 使用 `repository={pageQuery.data?.context?.repository ?? businessId}`

---

#### BUG-F2: ~~Domain review 模块计数始终为 0~~ ✅ 已修复

- **位置**: `WikiToolPanel.tsx:66-73`
- **修复**: mapper 填充 `moduleCount` from `module_count`；`WikiDomainReviewPanel` 使用 `displayedModuleCount()` 展示

---

#### BUG-F3: ~~invalidateWikiQueriesForBusiness 忽略 businessId~~ ✅ 已修复

- **位置**: `invalidateWikiQueries.ts:10-21`
- **修复**: predicate 改为 `k[0] === "wiki" && k.includes(b)`

---

#### BUG-F4: ~~审批按钮无 loading 状态~~ ✅ 已修复

- **位置**: `WikiDomainReviewPanel.tsx` + `WikiToolPanel.tsx`
- **修复**:
  1. `onApprove` 在 `onSuccess` 回调中关闭面板
  2. 按钮添加 `disabled={isPending}` + `aria-busy` + 加载指示器

---

#### BUG-F5: ~~ClaimHistoryPanel 静默失败~~ ✅ 已修复

- **位置**: `ClaimHistoryPanel.tsx:22-24`
- **修复**: 添加 loading/error 状态 UI 反馈

---

#### BUG-F6: ~~useWikiRegenerate 完成任务缓存未刷新~~ ✅ 已修复

- **位置**: `useWikiRegenerate.ts:125-128`
- **修复**: 恢复时如果任务状态为 `completed`，先调用 `invalidateWikiQueriesForBusiness` 再清除任务

---

## 3. 架构问题清单 (10 个)

| # | 问题 | 状态 | 说明 |
|---|------|------|------|
| A1 | ~~两套并行的 System Overview 实现~~ | ✅ 已修复 | pipeline 复用 `SystemOverviewComposer`，带 fallback |
| A2 | ~~循环依赖 page_composer_service ↔ service~~ | ✅ 已修复 | 共享函数提取到 `wiki/helpers.py` |
| A3 | ~~prompts.py 废弃模板~~ | ✅ 已修复 | 删除 `TOPIC_STRUCTURE_PROMPT`，保留基础设施 |
| A4 | ~~CoT 已实现但未接入管道~~ | ✅ 已完成 | 3 级 ReasoningLevel (NONE/GUIDED/MULTI_STEP) 替代旧 cot_generator，已删除废弃代码 |
| A5 | ~~LLMPort Protocol 多处重复定义~~ | ✅ 已修复 | 合并为 `context.py` 单一定义 |
| A6 | ~~quality_gate 仅用 structural_check~~ | ✅ 已修复 | 可配置分层质量门 L1/L2/L3 |
| A7 | ~~pipeline 节点命名与实际功能不符~~ | ✅ 已修复 | 重命名为 `classify_entity_roles` |
| A8 | ~~并发度硬编码~~ | ✅ 已修复 | 通过 `WIKI__COMPOSE_CONCURRENCY` 环境变量配置 |
| A9 | ~~`_normalize_domain_tree` 死参数~~ | ✅ 已修复 | 移除 `domain_mapping` 参数 |
| A10 | ~~i18n 不一致 (12+ 组件)~~ | ✅ 已修复 | 统一使用 `t.wiki.*` namespace |

---

## 4. 能力差距分析 — 产品视角

### 4.1 与 DeepWiki 的差距

| # | 差距 | KB Service 现状 | DeepWiki 做法 | 影响程度 | 优先级 |
|---|------|---------------|-------------|---------|--------|
| P1 | ~~**叙事性内容质量**~~ | ✅ `_SYSTEM_WIKI` 叙事性改写 + prompt 结构放松 | "像技术博客一样写"，解释 WHY 而非列举 WHAT | 极高 | ✅ 已完成 |
| P2 | ~~**Bottom-up 递归生成**~~ | ✅ compose_leaf_pages→summarize_leaves→compose_parent_pages→synthesize_overviews | leaf→parent→system 逐层综合 | 高 | ✅ 已完成 |
| P3 | **页面级 RAG Chat** | AskPanel 全局级，无页面上下文，且 repository 参数有 bug | 每个页面有专属 Chat 窗口，自动注入页面内容 | 高 | P1 |
| P4 | ~~**灵活内容结构**~~ | ✅ 非concise模式已改为 "Required elements (organize freely)" | 允许 LLM 自由组织结构（仅约束关键节） | 中 | ✅ 已完成 |
| P5 | ~~**即时生成体验**~~ | — | URL → 自动创建 Wiki | — | ❌ 取消（企业级知识库无需即时体验，需先 index 再生成） |

### 4.2 与 CodeWiki 的差距

| # | 差距 | KB Service 现状 | CodeWiki 做法 | 影响程度 | 优先级 |
|---|------|---------------|-------------|---------|--------|
| C1 | ~~**递归深化生成**~~ | ✅ leaf→parent→system 逐层综合 | leaf→parent→system 逐层综合 | 极高 | ✅ 已完成 |
| C2 | ~~**入口点驱动解构**~~ | ✅ ENTRY_POINT 角色 + DOMAIN_CLASSIFICATION_ENTITY_ROLES | 从 main/handler/endpoint 出发分析业务流程 | 高 | ✅ 已完成 |
| C3 | ~~**内联代码片段**~~ | ✅ select_key_snippets + snippet_section prompt 注入 | 关键方法签名直接嵌入文档 | 高 | ✅ 已完成 |
| C4 | **LLM 语义分组** | code_structure view 按目录结构遍历 | LLM 语义分组（跨目录相关模块归入同一主题） | 中 | P1 |

### 4.3 综合对比矩阵 (2026-05-01)

| 维度 | KB Service | DeepWiki | CodeWiki | 判定 |
|------|-----------|----------|----------|------|
| **图表生成** | 6种确定性 + LLM多模态 (4类型) | LLM Mermaid | 多模态综合 | ✅ **已追平** |
| **结构规划** | 业务域 LLM 分类 + 层级分解 | LLM 语义 TOC | DP 入口点驱动 | 🟡 业务视图赶超，代码视图落后 |
| **内容生成** | 三级策略 + 复杂度自适应 + 叙事性prompt + TargetedHeal + 3级ReasoningLevel + Bottom-up递归 + 代码注入 | 每页独立 LLM，叙事性强 | 递归多智能体 | ✅ **已追平** |
| **质量保证** | 多维度 Bench + 置信度 + 矛盾 + heal + L1/L2/L3 分层门 + Mermaid 语法验证 | 无 | CodeWikiBench | ✅ **架构领先** |
| **增量更新** | webhook + diff + scheduler + SSE + **索引后自动更新Wiki** (热开关) | ❌ | ❌ | ✅ **强大领先** |
| **多视图** | business_domain / code_structure / overview | ❌ | ❌ | ✅ **独有** |
| **Agent MCP** | 16+ 查询工具（纯查询层） | per-page chat | ❌ | ✅ **强大领先** |
| **记忆演化** | Q&A 循环 + 遗忘曲线 | ❌ | ❌ | ✅ **独有** |
| **导出** | Markdown/ZIP/Obsidian/MkDocs/Git/离线包 | 在线查看 | 文件系统 | ✅ **强大领先** |

---

## 5. 能力差距分析 — 技术视角

| # | 缺失能力 | 现状 | 竞品对标 | 优先级 |
|---|---------|------|---------|--------|
| T1 | ~~**思维链推理 (CoT)**~~ | ✅ `wiki/reasoning.py` 替代废弃 `cot_generator.py`，MultiStepReasoner 实现多步推理 | CodeWiki 多智能体递归 | ✅ 已完成 |
| T2 | ~~**自适应推理深度**~~ | ✅ 3 级 ReasoningLevel + DomainComplexityScorer 自动驱动 | 提案已设计 → 已实现 3 级 | ✅ 已完成 |
| T3 | ~~**分层质量门**~~ | ✅ 可配置 L1 structural + L2 bench + L3 llm_judge，三级覆盖 | KB 架构领先 | ✅ 已完成 |
| T4 | ~~**定向修复 (Targeted Heal)**~~ | ✅ `wiki/targeted_healer.py` + heal_pages_node 集成 | 诊断+JSON patch+fallback | ✅ 已完成 |
| T5 | ~~**Mermaid 语法验证**~~ | ✅ `mermaid-syntax-parser` 集成到 `diagram_quality_check` | - | ✅ 已完成 |
| T6 | ~~**Prompt 集中化管理**~~ | ✅ 共享 prompt 已集中到 `wiki/prompts.py`，6 模块导入 | - | ✅ 已完成 |
| T7 | **LLM 模型策略分离** | 所有节点用同一个 LLM | 提案已设计快/慢模型分离 | P1 |
| T8 | **复杂度评估器** | DomainComplexityScorer 未充分利用 | 提案已设计多维度复杂度 | P1 |

---

## 6. 能力差距分析 — Agent 使用视角

> **MCP 定位决策**: MCP 定位为**纯查询层**。外部 Agent 自带 LLM 能力，系统无需通过 MCP 提供智能能力，不通过 MCP 触发索引和 Wiki 生成。

| # | 缺失能力 | 描述 | 影响 | 状态 |
|---|---------|------|------|------|
| A1 | **上下文感知的 Wiki 查询** | Agent 调用 wiki_search 时无法指定"当前页面"上下文 | Agent 回答缺少页面上下文 | 待处理 |
| A2 | ~~多视角 Wiki 生成工具~~ | MCP 无"指定视角生成"能力 | — | ❌ 取消（MCP 不提供生成能力） |
| A3 | ~~增量生成状态反馈~~ | Agent 触发生成后无法获取实时进度 | — | ❌ 取消（MCP 不提供生成能力） |
| A4 | ~~质量分析工具~~ | MCP 无专门的"分析 wiki 质量"工具 | — | ❌ 取消（如需要，在现有查询接口附带质量分数） |
| A5 | **图谱-Wiki 关联查询** | 图谱查询和 Wiki 查询独立 | 知识属性不统一 | 待处理 |
| A6 | ~~写回能力~~ | Agent 无法通过 MCP 编辑 wiki 内容 | — | ❌ 取消（MCP 定位为只读查询） |

### Agent 能力对比

| 维度 | KB Service | DeepWiki | CodeWiki |
|------|-----------|---------|----------|
| MCP 工具数 | 16+ (纯查询) | per-page chat | 无 |
| 图谱查询 | ✅ | ✖ | ✖ |
| Wiki 查询 | ✅ | ✖ | ✖ |
| 上下文感知查询 | ✖ (待处理 A1) | ✅ (per-page) | ✖ |
| 图谱-Wiki 关联 | ✖ (待处理 A5) | ✖ | ✖ |

**结论**: KB Service 的 Agent MCP 定位为纯查询层，在工具数量和功能广度上领先。待增强上下文感知查询（A1）和图谱-Wiki 关联查询（A5）以提升查询深度。

---

## 7. 竞品可借鉴的具体能力

### 7.1 从 DeepWiki 借鉴

#### D1: ~~叙事性内容生成模式~~ ✅ 已完成
- **修复**: `_SYSTEM_WIKI` + `_build_single_page_prompt` 叙事性改写

#### D2: Per-page RAG Chat (待处理 P3)
- **现状**: AskPanel 全局级，无页面上下文
- **借鉴**: 自动注入当前页面 `content` 作为 conversation context
- **实施**:
  1. 传入 `currentPageContent` 到 AskPanel
  2. Ask API 接受可选 `page_context` 参数
- **预期效果**: 用户在阅读特定页面时提问，获得页面相关的精准回答

#### ~~D3: 即时生成体验~~ ❌ 取消
- **原因**: 企业级知识库产品，需先完成索引再生成 Wiki，无需降低首次使用门槛

### 7.2 从 CodeWiki 借鉴

#### C1: ~~递归深化生成 (Bottom-up)~~ ✅ 已完成
- **实施**: compose_leaf_pages → summarize_leaves → compose_parent_pages → synthesize_overviews

#### C2: ~~入口点驱动解构~~ ✅ 已完成
- **实施**: EntityRoleClassifier + ENTRY_POINT 角色

#### C3: ~~内联代码片段注入~~ ✅ 已完成
- **实施**: select_key_snippets + snippet_section prompt 注入

#### C4: LLM 语义分组 (待处理)
- **借鉴**: code_structure view 用 LLM 语义分组而非目录结构
- **实施**: WikiStructurePlanner 增强 LLM 语义分组
- **预期效果**: 不同目录下的相关模块可以被归入同一主题

---

## 8. 测试覆盖缺口

### 8.1 后端未覆盖模块

| 模块 | 风险等级 | 状态 |
|------|---------|------|
| ~~diagram dict shape 转换路径~~ | **高** | ✅ 已补全 — `test_compose_pages_diagrams.py` |
| ~~嵌套域遍历 (heal/synthesize)~~ | **高** | ✅ 已补全 — `test_pipeline_nodes_audit_fixes.py` 3 个测试 |
| ~~`_expected_wiki_page_paths_dfs`~~ | 中 | ✅ 已补全 — `test_compose_phases.py` 2 个测试 |
| ~~resolved_links 持久化~~ | 中 | ✅ 已补全 — `test_business_wiki_resolved_links.py` |
| ~~`tree_linker.py`~~ | 中 | ✅ 已补全 — `test_tree_linker.py` 13 个测试 |
| ~~`flow_writer.py`~~ | 中 | ✅ 已补全 — `test_flow_writer.py` 9 个测试 |
| ~~`enrichment_coordinator.py`~~ | 中 | ✅ 已补全 — `test_enrichment_coordinator.py` 10 个测试 |
| `finalize_node` | 低 | 仅日志，无独立测试 |
| prompt 实际输出质量 | 中 | mock LLM 不验证实际 prompt 效果 |

### 8.2 前端未覆盖组件 (关键)

| 组件 | 风险等级 | 状态 |
|------|---------|------|
| ~~`WikiToolPanel`~~ | **高** | ✅ 已补全 — 7 个测试 (渲染/Tab/AskPanel/域审阅/ErrorBoundary) |
| ~~`AskPanel`~~ | **高** | ✅ 已补全 — 6 个测试 (渲染/输入/提交/pageContext/流式) |
| ~~`WikiActiveTasks`~~ | 中 | ✅ 已补全 — 5 个测试 (空状态/任务卡片/进度条/Phase i18n/取消) |
| ~~`WikiReferencesPanel`~~ | 中 | ✅ 已补全 — 3 个测试 (加载/空状态/引用行) |
| ~~`WikiDiffViewer`~~ | 中 | ✅ 已补全 — 4 个测试 (加载/错误/Diff渲染/关闭) |
| ~~`WikiExportPanel`~~ | 中 | ✅ 已补全 — 3 个测试 (UI/预览/导出) |
| ~~`WikiLintPanel`~~ | 中 | ✅ 已补全 — 3 个测试 (空状态/运行/无问题) |
| ~~`WikiLandingPage`~~ | 中 | ✅ 已补全 — 2 个测试 (空状态/可访问性) |

### 8.3 未覆盖 Hooks

| Hook | 状态 |
|------|------|
| ~~`useWikiReview`~~ | ✅ 已补全 — 3 个 mutation 测试 |
| ~~`useWikiDomainTree`~~ | ✅ 已补全 — 4 个测试 |
| ~~`useWikiIncremental`~~ | ✅ 已补全 — 含 invalidation 验证 |
| ~~`invalidateWikiQueries`~~ | ✅ 已补全 — predicate 行为验证 |
| ~~`useWikiNavigation`~~ | ✅ 已补全 — 3 个测试 |
| ~~`useWikiQualityScore`~~ | ✅ 已补全 — 3 个测试 |
| ~~`useWikiAnnotations`~~ | ✅ 已补全 — 4 个测试 (CRUD) |

---

## 9. ~~前端 i18n 问题详细清单~~ ✅ 全部已修复

所有 12+ 组件已统一使用 `useI18n` 的 `t.wiki.*` namespace。新增 i18n key 分布在：
- `t.wiki.domain_review.*` — 域审阅面板
- `t.wiki.sidebar.*` — 侧边栏切换
- `t.wiki.topic_tree.*` — 主题树导航
- `t.wiki.topic_content.*` — 主题内容审阅
- `t.wiki.knowledge_graph.*` — 知识图谱
- `t.wiki.business_flow.*` — 业务流
- `t.wiki.related_pages.*` — 相关页面
- `t.wiki.claims.*` — 主张历史
- `t.wiki.eventsReconnecting` — SSE 重连提示

---

## 10. 优先级排序与实施路线

### Phase 0: 紧急修复 ✅ 已完成 (2026-05-01)

| 任务 | 影响 | 状态 |
|------|------|------|
| BUG-B1: diagram dict `diagram_type` → `type` | 图表功能完全失效 | ✅ 已修复 |
| BUG-B2: heal_pages_node 嵌套域上下文 | heal 质量下降 | ✅ 已修复 |
| BUG-B3: synthesize_overviews 嵌套域遍历 | system overview 不完整 | ✅ 已修复 |
| BUG-B4: detect_reorg 模块计数 | reorg 判定偏差 | ✅ 已修复 |
| BUG-F1: AskPanel repository 参数修复 | Ask 查询范围错误 | ✅ 已修复 |
| BUG-F2: Domain review module count 修复 | 审查信息缺失 | ✅ 已修复 |
| BUG-F3: invalidateWikiQueriesForBusiness 修复 | 过度缓存刷新 | ✅ 已修复 |
| BUG-F4: 审批按钮 loading 状态 | 重复提交风险 | ✅ 已修复 |
| BUG-F5: ClaimHistoryPanel 静默失败 | 无 UI 反馈 | ✅ 已修复 |
| BUG-F6: useWikiRegenerate 缓存刷新 | 数据过期 | ✅ 已修复 |
| BUG-B5: resolved_links 持久化 | 资源浪费 | ✅ 已修复 |

### Phase 1: 内容质量提升 ✅ 已完成

| 任务 | 预期效果 | 状态 |
|------|---------|------|
| ~~复用 SystemOverviewComposer 替代 thin node~~ | system overview 质量提升 | ✅ 已完成 (A1) |
| ~~Topic 生成 prompt 叙事性增强~~ | 从"API 列表"变为"技术故事" | ✅ 已完成 — `_SYSTEM_WIKI` + `_build_single_page_prompt` 叙事性改写 |
| ~~Targeted heal 替代 full regen~~ | heal 成功率提升，保留好的 sections | ✅ 已完成 — 新增 `wiki/targeted_healer.py`，heal_pages_node 优先使用 |
| ~~prompt 集中化管理~~ | 测试与生产一致性 | ✅ 已完成 — `SYSTEM_JSON_ONLY`/`SYSTEM_WIKI_AUTHOR`/`SYSTEM_WIKI_HEAL` 集中到 `prompts.py`，6 个模块改为导入 |
| ~~嵌套域遍历修复 (heal/synthesize)~~ | 嵌套域信息不再丢失 | ✅ 已完成 (BUG-B2/B3) |

### Phase 2: CoT 与自适应推理 ✅ 已完成

| 任务 | 预期效果 | 状态 |
|------|---------|------|
| ~~ReasoningLevel 架构 (NONE/GUIDED/MULTI_STEP)~~ | 推理深度可控 | ✅ `wiki/reasoning.py` |
| ~~域分类 GUIDED prompt~~ | 分类 confidence 提升 | ✅ classify_domains_node 集成 |
| ~~Topic 生成 MULTI_STEP~~ | 内容深度提升 | ✅ TopicPageComposer + MultiStepReasoner |
| ~~复杂度评估器接入~~ | 自动选择推理深度 | ✅ DomainComplexityScorer 驱动 |
| ~~删除废弃 cot_generator.py~~ | 代码清洁 | ✅ 已删除 + config/UI 清理 |

### Phase 3: Bottom-up 与代码注入 ✅ 已完成

| 任务 | 预期效果 | 状态 |
|------|---------|------|
| ~~summarize_leaves_node (无 LLM 成本)~~ | 为 parent page 提供输入 | ✅ 已完成 — `pipeline_nodes.py` + LeafSummary dataclass |
| ~~compose_parent_pages_node~~ | 层级综合能力 | ✅ 已完成 — 含 route_parent_or_overview 条件路由 |
| ~~select_key_snippets + prompt 注入~~ | 文档与代码关联 | ✅ 已完成 — `snippet_selector.py` + TokenBudgetCalculator |
| ~~ENTRY_POINT 角色增强~~ | 入口点驱动的业务意义 | ✅ 已完成 — EntityRoleClassifier + DOMAIN_CLASSIFICATION_ENTITY_ROLES |

### Phase 4: 前端体验 ✅ 核心已完成

| 任务 | 预期效果 | 状态 |
|------|---------|------|
| ~~i18n 统一 (12+ 组件 + 4 个新组件)~~ | 国际化一致性 | ✅ 已完成 |
| Per-page RAG Chat (AskPanel 上下文注入) | 页面级精准问答 | 待处理 (P3) |
| ~~SSE 断连 UI 反馈~~ | 连接状态可见 | ✅ 已完成 |
| ~~审批/审查 UX 完善~~ | 操作反馈一致 | ✅ 已完成 |
| ~~前端测试补全 (isPending/reconnecting/error)~~ | 防止回归 | ✅ 已完成 |

### Phase 5: 质量保证 ✅ 已完成

| 任务 | 预期效果 | 状态 |
|------|---------|------|
| ~~分层质量门 (L1 structural / L2 bench / L3 llm_judge)~~ | 内容质量全面把控 | ✅ 已完成 |
| ~~Mermaid 语法验证 (`mermaid-syntax-parser`)~~ | 图表语法检查 | ✅ 已完成 |
| ~~核心组件测试补全 (WikiToolPanel, AskPanel)~~ | 防止回归 | ✅ 已完成 |

---

## 11. 架构优势总结 (KB Service 领先项)

KB Service 在以下维度保持显著领先：

1. **增量更新体系**: webhook + diff + scheduler + SSE + 索引后自动更新 Wiki（dashboard 热开关），竞品均无此能力
2. **多视图生成**: business_domain / code_structure / overview，独有
3. **Agent MCP 生态**: 16+ 查询工具（纯查询层定位），最丰富的 Agent 集成
4. **记忆演化系统**: Q&A 循环 + 遗忘曲线，独有
5. **导出生态**: Markdown/ZIP/Obsidian/MkDocs/Git/离线包，远超竞品
6. **质量保证架构**: L1/L2/L3 分层质量门 + 置信度 + 矛盾检测 + 主张追踪 + Mermaid 语法验证
7. **版本控制与 Diff**: 页面级版本历史和差异对比

---

## 12. 已完成 — Wiki Auto-Update on Index (2026-05-01)

索引完成后自动触发 `WikiService.generate_incremental`，保持 Wiki 与代码同步。Dashboard 热开关支持动态启用/禁用。

| 任务 | 状态 |
|------|------|
| `IncrementalIndexer` 添加 `wiki_auto_updater` 回调 + `settings_store` 注入 | ✅ 已完成 |
| `_check_auto_update_enabled` 从 DB 热读配置，故障回退启动配置 | ✅ 已完成 |
| `KnowledgeBaseService` → `ServiceRegistry` 依赖注入链 | ✅ 已完成 |
| `SettingsStore` 统一生命周期（`main.py` → `app.state`） | ✅ 已完成 |
| Settings API `HOT_RELOAD_KEYS` 标记 `wiki.auto_update_on_index` | ✅ 已完成 |
| 10 个新增测试覆盖（回调/禁用/错误隔离/优先级/DB配置/故障回退/热重载标志/接线验证） | ✅ 已完成 |

---

## 13. 剩余工作汇总

| 类别 | 项目 | 描述 | 优先级 |
|------|------|------|--------|
| 技术 | T7: LLM 模型策略分离 | 快/慢模型分离，不同节点使用不同级别 LLM | P1 |
| 技术 | T8: 复杂度评估器深化 | DomainComplexityScorer 多维度利用 | P1 |
| 产品 | P3: 页面级 RAG Chat | AskPanel 注入当前页面上下文，Ask API 接受 `page_context` | P1 |
| 产品 | C4: LLM 语义分组 | code_structure view 用 LLM 语义分组替代目录结构 | P1 |
| Agent | A1: 上下文感知 Wiki 查询 | wiki_search 支持"当前页面"上下文 | P1 |
| Agent | A5: 图谱-Wiki 关联查询 | 统一图谱和 Wiki 的知识查询 | P2 |

**核心结论**: KB Service 的"基础设施"和"可扩展性"远超竞品。Phase 0–5 已全面完成核心工作：11 个运行时 Bug 全部修复、10 个架构问题全部解决、内容质量提升（叙事性 + CoT + Bottom-up + 代码注入）、可配置分层质量门（L1/L2/L3）+ Mermaid 语法验证、i18n 国际化统一、前端测试补全、**索引后自动更新 Wiki + 热开关**。**内容生成能力和质量保证已追平竞品**。剩余差距集中在 LLM 模型策略分离（T7）、复杂度评估器深化（T8）、页面级 RAG Chat（P3）、LLM 语义分组（C4）和 Agent 查询增强（A1/A5）。
