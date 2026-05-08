# Wiki 生成质量深度分析与改进方案

- **状态**: Draft
- **创建时间**: 2026-05-08 17:00
- **关联提案**: PROPOSAL_20260508_150922_wiki_quality_remediation.md

---

## 1. 背景

2026-05-08 对 knowledge-base-service 进行了全量 wiki 重新生成（business_id=default, incremental=false），
处理 847 个模块、2 个仓库（ultron-basic-user, ultron-composite），生成 41 个页面，覆盖 15 个业务域。
生成后对全部 63 个独立页面（39 domain_overview + 24 topic）进行了自动化质量扫描和手工审查。

---

## 2. 质量扫描结果

### 2.1 统计总览

| 指标 | 数值 |
|---|---|
| 总 Section 数 | 40 |
| 总页面（去重） | 63 |
| domain_overview 页面 | 39 |
| topic 页面 | 24 |

### 2.2 问题分布

| 问题类型 | 影响范围 | 严重性 |
|---|---|---|
| **P0-1: Markdown 代码块包裹** | 13/24 topic (54%) | P0 |
| **P0-2: 调用链 100% 缺失** | 24/24 topic (100%) | P0 |
| **P1-1: 左侧树空洞（仅 overview）** | 22/40 sections (55%) | P1 |
| **P1-2: domain overview 过短** | 21/39 overview (< 300 chars) | P1 |
| **P2-1: CONTEXT_GAP 残留** | 2 pages (变体格式) | P2 |
| **P2-2: "此处信息待补充" 占位** | 10 pages | P2 |
| **已修复: Thinking 泄漏** | 0 pages | N/A |
| **已修复: 内容过短** | 0 pages (所有 topic 3000+ chars) | N/A |

---

## 3. 根因分析

### 3.1 P0-1: Markdown 代码块包裹

**现象**: 54% 的 topic 页面内容以 ` ```markdown ` 开头、` ``` ` 结尾，前端显示原始 markdown 文本而非渲染内容。

**根因链**:

1. System prompt 明确要求 JSON 输出: `{"executive_summary": "...", "content": "..."}`
2. LLM 部分场景未遵守 JSON 指令，直接输出 markdown 并用 ` ```markdown ` 围栏包裹
3. `wiki/json_robust.py._strip_fences()` 只剥离 `json` 围栏（`^```(?:json)?`），不处理 `markdown` 围栏
4. JSON 解析失败后，`_parse_wiki_json_response()` fallback 返回原始文本（含围栏）
5. 前端将整个内容作为 markdown 渲染，显示为代码块

**代码位置**: `wiki/json_robust.py:20-26`, `wiki/topic_page_composer.py:74-87`

**修复方案**:
```python
# json_robust.py._strip_fences 扩展
text = re.sub(r"^```(?:json|markdown|md)?\s*\n?", "", text)
```
同时在 `_parse_wiki_json_response` fallback 路径也调用 `_strip_fences`。

### 3.2 P0-2: 调用链 100% 缺失

**现象**: 所有 24 个 topic 页面的「核心业务流程」章节均显示"当前上下文中未提供调用链数据，不生成流程图"。

**根因链（关键发现）**:

1. **FalkorDB 图数据实际存在调用关系**:
   - `Function → Function` CALLS: **4,370 条**
   - `Module → Module` CALLS: **0 条**
   - `Module → CONTAINS → Function`: **仅 115 条**（4,921 个 Function 中只有 2.3%）
   
2. CCB (ContentContextBuilder) 查询使用 Module 层 Cypher:
   ```cypher
   -- 模块间调用：0 结果（不存在 Module→Module CALLS）
   MATCH (a:Module)-[:CALLS*1..{d}]->(b:Module) WHERE a.name IN $names
   
   -- 方法调用链：极少结果（Module→Function CONTAINS 极稀疏）
   MATCH (m:Module)-[:CONTAINS*1..3]->(cf:Function)-[:CALLS]->(ct:Function)
   WHERE m.name IN $names
   ```
   
3. **Indexer 只在 Function 层创建 CALLS 边，从未创建 Module 层 CALLS**
4. **Module → Function 的 CONTAINS 关系极度不完整**（115/4921 = 2.3%）
5. prompt 指示："若调用链为空则写「当前上下文中未提供调用链数据，不生成流程图」"→ LLM 忠实执行

**代码位置**: 
- Cypher 查询: `wiki/cypher_queries.py:15-34`
- CCB 调用: `wiki/content_context_builder.py:368-460`

**修复方案**:

**短期（修复查询层）**:
修改 CCB 的 Cypher 查询，从 Function 层聚合到 Module 层：
```cypher
-- 新查询：通过 Function CALLS 推导 Module 间调用
MATCH (m1:Module)-[:CONTAINS*1..3]->(f1:Function)-[:CALLS]->(f2:Function)<-[:CONTAINS*1..3]-(m2:Module)
WHERE m1.name IN $names AND m1 <> m2
RETURN DISTINCT m1.name AS caller, m2.name AS callee
```

**中期（补全图数据）**:
在 indexer 中添加后处理步骤：
1. 为所有 Function 创建到所属 Module/Class 的 CONTAINS 关系
2. 基于 Function-level CALLS 聚合生成 Module-level CALLS 边

**长期（Agent-Driven，见第 5 节）**:
让 LLM Agent 在内容生成阶段自主查询调用链。

### 3.3 P1-1: 左侧树空洞

**现象**: 55% 的 section（22/40）仅包含 1 个 overview 页面，无详细 topic 页面。

**根因**:
1. LLM 域分类粒度过细：847 模块 → 40 个 section（平均每域 21 模块，但方差极大）
2. 很多子域仅含 1-2 个模块（如"礼物响应构建"、"道具购买处理"）
3. 模块数 < TopicPageComposer.SIMPLE_THRESHOLD (5) 的域不生成子主题页
4. 只生成一个薄弱的 domain_overview（< 300 chars）

**修复方案**:
- 设置最小域合并阈值（如 < 3 模块的域合并入父域）
- 或在分类阶段限制最大域数量
- 对单模块域：将 overview + detail 合并为单页

### 3.4 P1-2: Domain overview 过短

**现象**: 21/39 个 overview 页面 < 300 字符，部分仅 60-70 字符（一个标题 + 一个模块名）。

**根因**: 与 P1-1 直接关联。当域只有 1 个模块时，overview 输入信息极少，LLM 无法展开描述。

**修复方案**: 联动 P1-1，合并小域后自然解决。

---

## 4. 行业方案对比

### 4.1 三种方案对比

| 维度 | 我们的方案 | DeepWiki (Devin) | CodeWiki (ACL 2026) |
|---|---|---|---|
| **核心架构** | LangGraph Pipeline + 预填充 Prompt | RAG Pipeline (FAISS) | **递归 Agent + Tool Calling** |
| **上下文获取** | CCB 预查询 → 填充 prompt | 向量检索 + 相似度排序 | **Agent 自主决定查询什么** |
| **调用链来源** | 依赖 Module-level CALLS（不存在） | AST 解析 (tree-sitter) | **Agent tool: read_code + deps traversal** |
| **域分类** | LLM 分类（可能过细） | 按目录结构 + LLM 微调 | **依赖图 + 拓扑排序 + 特征导向划分** |
| **薄弱域处理** | 生成空 overview | 合并到父级 | **动态委派：简单模块简略处理** |
| **内容深度** | 取决于预填充数据完整度 | 取决于 RAG 检索质量 | **Agent 可迭代深入查询** |
| **防幻觉** | 强约束 prompt + 后处理 | 源码引用验证 | **Agent 验证：查询 → 确认 → 写入** |
| **质量评分** | ~62% (估算) | 64.06% | **68.79%** |
| **Token 消耗** | 中（单次 prompt） | 中（检索 + 生成） | **高（多轮 tool calling）** |

### 4.2 CodeWiki 核心创新

CodeWiki（FPT Software AI Center, ACL 2026 接收）的关键差异：

**1. 递归 Agent 处理**
```
仓库 → 层次化分解 → 叶子模块
每个叶子模块 → Agent + Tools → 文档
复杂模块 → 动态委派给子 Agent
子模块文档 → LLM 合成 → 父模块文档 → 仓库概览
```
Agent 拥有的工具：`read_code_components`, `generate_sub_module_documentations`, `deps`, `str_replace_editor`

**2. 层次化分解（类动态规划）**
- Tree-sitter AST 解析 → 依赖图 G=(V,E)
- 特征导向模块划分（不是简单的 LLM 分类）
- 拓扑排序保证依赖顺序生成

**3. 多模态合成**
- 子模块文档 → 父模块文档的自底向上合成
- 架构图、数据流图、序列图基于真实依赖生成（非 LLM 凭空编造）

### 4.3 Karpathy CodeWiki (mraza007/codewiki)

另一种轻量方案，核心思想与 CodeWiki 不同但互补：

**1. LLM 维护自己的索引**
```
~/.codewiki/project/
├── _index.md        # LLM 自维护的主索引
├── _architecture.md # 系统概览
├── modules/         # 每模块一篇文章
├── concepts/        # 跨模块概念
├── decisions/       # 设计决策
└── learnings/       # 修复记录
```

**2. 增量更新机制**
- 每篇文章有 `source_files` 前置数据
- `cw status` 对比 git diff，标记过期文章
- Agent 只更新变更相关的文章

**3. 无 RAG**
- 不使用向量数据库
- LLM 读取自己维护的索引和文章
- 在中等规模仓库（~100 文件）效果好

---

## 5. 改进建议

### 5.1 短期修复（1-2 天，解决 P0 问题）

**Fix 1: Markdown 围栏剥离**
- 修改 `_strip_fences` 支持 `markdown`/`md` 围栏
- 在 `_parse_wiki_json_response` fallback 路径增加二次剥离
- 工作量: 2h

**Fix 2: CCB 调用链查询修复**
- 新增从 Function-level CALLS 聚合到 Module 的 Cypher 查询
- 预计将调用链覆盖率从 0% 提升到 50-60%
- 工作量: 4h

**Fix 3: CONTEXT_GAP 正则拓宽**（已完成）
- 正则从 `CONTEXT_GAP:` 扩展为 `CONTEXT_GAP[:\s：]`
- 已部署

### 5.2 中期改进（1 周，解决 P1 问题 + 调用链深度提升）

**改进 1: Indexer 补全图关系**
- 在 indexer 中为 Function 补全 Module/Class CONTAINS 关系
- 基于 Function CALLS 生成 Module-level CALLS 聚合边
- 预计调用链覆盖率提升到 80%+

**改进 2: 域分类优化**
- 设置最小域大小阈值（如 3 模块）
- 小域自动合并入父域或兄弟域
- 减少空洞 section

**改进 3: 小域 overview + detail 合并**
- 当域仅有 1-2 个模块时，合并 overview 和 detail 为单页
- 避免生成几十字的空 overview

### 5.3 长期方向（Agent-Driven 生成）

**将 WikiPageAgent 从「后处理修补」提升为「主生成引擎」**

当前架构:
```
CCB 预查询 → 填充 prompt → LLM 单次生成 → Agent 修补 CONTEXT_GAP
```

目标架构:
```
基线上下文（CCB）→ Agent + 14 种 Tools → 迭代生成
                    ↑ query_call_chain
                    ↑ read_code / grep_code
                    ↑ query_callers / query_callees
                    ↑ query_implementations
```

优势:
- Agent 自主决定需要查询哪些信息（而非盲目预填充）
- 调用链、代码片段按需获取，不受预查询失败影响
- 复杂模块可多轮深入，简单模块快速生成
- 与 CodeWiki 的 Agent 方案思路一致

劣势:
- Token 消耗增加 2-3 倍
- 生成时间更长
- 需要精心设计 Agent 提示以控制质量

---

## 6. 验证数据

### 6.1 FalkorDB 图数据统计

```
Graph: kb_default
├── Module nodes:         1,816
├── Function nodes:       4,921
├── Function→Function CALLS: 4,370
├── Module→Module CALLS:     0     ← 根因
├── Module→Function CONTAINS: 115  ← 严重不足
└── Class→Class CALLS:       0
```

### 6.2 页面质量扫描样本

```
用户资料服务                 |  5715 chars | OK (CONTEXT_GAP 文字提及但非原始标记)
用户财富与魅力值服务          |  4277 chars | CLEANED_GAP(1)
直播与语音互动处理            |  5342 chars | OK
ClosedFriendRecordService  |  5027 chars | OK
UserRelationRemoteServiceImpl | 8159 chars | OK
业务系统MOA服务实现           |  9613 chars | CLEANED_GAP(1)
应用商店弹窗服务              |  5475 chars | OK
送礼订单与礼物处理            |  6828 chars | OK (markdown 围栏待修复)
亲密关系与注销回调处理         |  4545 chars | RAW_GAP (变体格式)
```

### 6.3 search_entities 工具失败日志

```
[WARNING] agent_tool_failed | error='Type mismatch: expected String or Null but was List' | tool=search_entities
```
原因: FalkorDB 中部分节点属性存储为 List 而非 String，Cypher WHERE 子句类型不匹配。
影响: Agent 在 CONTEXT_GAP 修复时无法通过 search_entities 查找相关实体。
