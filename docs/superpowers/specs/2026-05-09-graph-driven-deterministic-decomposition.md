# Graph-Driven Deterministic Decomposition — 确定性分解架构设计

> Created: 2026-05-09  
> Status: MOSTLY_IMPLEMENTED — 核心分解算法已实现，残余项见 `proposals/PROPOSAL_20260509_164027_codewiki_quality_improvements.md` B5-B6  
> Category: Architecture / Wiki Quality  
> Related: CodeWiki (ACL 2026), harness + agent-driven system

---

## 1. 问题陈述

### 1.1 当前系统 vs CodeWiki 的质量差距

通过对 CodeWiki 论文 (arXiv:2510.24428) 的深度分析，识别出以下核心差距：

| 维度 | CodeWiki | 当前系统 | 差距影响 |
|------|----------|----------|----------|
| **结构分解** | 依赖图 + 入口点 + 拓扑排序（图算法驱动） | LLM 自由生成 topic title (`TopicBasedStructurePlanner`) | 结构不稳定，相同输入可能产生不同大纲 |
| **结构-代码绑定** | 强绑定——模块树直接反映代码依赖关系 | 弱绑定——LLM 可能"发明"与代码无对应的 topic | 文档与代码架构脱节 |
| **处理顺序** | 拓扑排序确保依赖先处理 | 并行处理无顺序保证 | 跨域引用不完整 |
| **上下文传递** | 全局 registry + complete source access + module tree | domain_cache 每 leaf 新建、CCB/Gather 重复查询 | 跨域知识断裂、token 成本翻倍 |
| **评测体系** | CodeWikiBench 层次化 rubric + 多 Judge Agent | L1 形式检查 + L2 stub | 无法自检内容质量 |
| **动态委托** | Agent 自动拆分过大模块 | 无 | 大 domain 质量下降 |
| **Bottom-up 综合** | parent docs = LLM synthesize(child docs) | overview = 模板填充或截取 topic content | 高层文档缺乏深度 |

### 1.2 CodeWiki 的确定性来源（论文 vs 实际代码）

> **重要修正**: 通过阅读 CodeWiki 的实际开源代码 (github.com/FSoft-AI4Code/CodeWiki)，发现论文描述与实现有差异。

**论文描述**的四步流程：
1. Dependency Graph Construction (Tree-sitter AST → 有向图) — **确定**
2. Entry Point ID + Hierarchical Decomposition — 论文暗示算法驱动
3. Recursive Agent-based Generation — LLM
4. Hierarchical Assembly — LLM

**实际代码**的四步流程：
1. `DependencyGraphBuilder.build_dependency_graph()` → (components, leaf_nodes) — **确定**
2. `cluster_modules()` — **使用 LLM** (`call_llm(format_cluster_prompt(...))`) + 递归分解 — **半确定**
3. `AgentOrchestrator.process_module()` — pydantic_ai Agent + tools — **LLM 驱动**
4. `generate_parent_module_docs()` — LLM synthesize(child docs) — **LLM 驱动**

**CodeWiki 的真正优势不在于"纯确定性"，而在于：**
- **递归分解 + token 约束**: 当 tokens > `max_token_per_module` 时才拆分，保证每个叶子可被单个 Agent 处理
- **Bottom-up processing order**: 子模块先完成 → 父模块可用子模块的文档做综合
- **Agent 拥有完整源码**: 通过 `components` dict 直接访问完整源码，非图查询
- **Dynamic delegation**: Agent 可自主决定是否拆分过大模块

**我们的差距**（重新校准后）：
- 我们的 `TopicBasedStructurePlanner` 与 CodeWiki 的 `cluster_modules` 本质类似（都用 LLM 分组）
- 但我们缺少：递归分解（token 约束）、bottom-up synthesis、dynamic delegation、complete source access

### 1.3 中文域名节点关联断裂

根因调用链：
```
TopicBasedStructurePlanner.plan()
→ LLM 生成 topic title (如: "用户关系与等级管理")
→ compose 用 title 作为 path: "wiki/用户关系与等级管理"
→ persist 写入 WikiPage
→ tree_linker.link_pages_to_nested_tree()
→ _find_best_domain() 尝试匹配 "用户关系与等级管理" vs domain name "用户关系管理"
→ CJK 字符重叠启发式匹配 → 极端情况下失败
```

断裂点：
1. `business_domain` 属性在 topic 路径下由模块投票得出，可能为空
2. `page_top_level` 是 LLM 自由生成的 title，与 canonical domain name 不一致
3. `_find_best_domain` 的 CJK overlap 用 domain 字符集作分母，长 domain + 短 title 时得分低于 0.5 阈值
4. `persistence.py` 中空 `business_domain` 不覆盖旧值，可能保留脏数据

---

## 2. 设计方案

### 2.1 三层架构

```
┌─────────────────────────────────────────────────────────┐
│            Layer 3: Recursive Generation + Synthesis     │
│  WikiPageAgent / Harness → LLM Generate → LLM Synthesize│
│  (半确定: 结构确定, 内容由 LLM 生成)                      │
├─────────────────────────────────────────────────────────┤
│            Layer 2: Readable Title Generation            │
│  TitleGenerator(LLM) → 给 canonical_key 赋中文标题       │
│  (LLM 仅影响显示名, 不影响结构和关联)                     │
├─────────────────────────────────────────────────────────┤
│            Layer 1: Graph-Driven Decomposition           │  ← 核心新增
│  FalkorDB → SCC → Topo Sort → Community Detection       │
│  (完全确定: 相同图 → 相同模块树 + canonical_key)          │
└─────────────────────────────────────────────────────────┘
```

### 2.2 Layer 1: GraphModuleDecomposer (新建)

**文件**: `wiki/graph_decomposer.py`

**输入**: 
- FalkorDB graph (CALLS/IMPLEMENTS/CONTAINS edges)
- entity_roles (entry_point / has_business_logic / supporting / framework_noise)
- DomainClassifier 的 domain_mapping (域名 → 模块列表)

**算法**:

```
Step 1: Extract — 从 FalkorDB 提取依赖图到内存有向图
  MATCH (a)-[r:CALLS|IMPLEMENTS]->(b) 
  WHERE a.repository = $repo AND b.repository = $repo
  RETURN a.name, r.type, b.name

Step 2: SCC Contraction — Tarjan 算法识别强连通分量
  对于每个 SCC (循环依赖组):
    合并为一个虚拟节点 "scc_{sorted_member_names_hash}"
    保留所有外部边

Step 3: Topological Sort — 确定处理顺序
  对 SCC 缩减图做拓扑排序
  输出: 确定性处理顺序 [module_1, module_2, ...]

Step 4: Domain-Aware Community Detection — 划分 topic
  对每个 domain 内的子图:
    用 connected component 分析
    每个连通分量 = 一个 candidate topic
  合并策略:
    size < min_modules(3) → 合并到同 domain 内最近连通分量
    
Step 5: Generate canonical_key
  对每个 topic:
    canonical_key = f"d{domain_idx:03d}_t{topic_idx:03d}"
    例如: "d001_t001", "d001_t002", "d002_t001"
  对每个 domain:
    canonical_key = f"d{domain_idx:03d}"
    
Step 6: Output Module Tree T
  ModuleTreeNode:
    canonical_key: str       # 确定性唯一 ID
    domain_name: str         # DomainClassifier 原始中文名
    modules: list[str]       # 所属模块名列表
    dependencies: list[str]  # 依赖的其他 canonical_key
    depth: int               # 在树中的深度
    processing_order: int    # 拓扑排序位置
```

**确定性保证**: Steps 1-6 全部是图算法，相同输入 → 相同输出。

### 2.3 Layer 2: TitleGenerator (重构 TopicBasedStructurePlanner)

将 `TopicBasedStructurePlanner` 的职责从"生成结构"降级为"生成标题":

```python
class TitleGenerator:
    """为确定性模块树的每个节点生成人类可读的中文标题。"""
    
    async def generate_titles(
        self,
        module_tree: list[ModuleTreeNode],
        module_metadata: dict[str, dict],
    ) -> dict[str, str]:  # canonical_key → 中文标题
        """LLM 只决定显示名，不改变结构。"""
        prompt = self._build_prompt(module_tree, module_metadata)
        # 输出: {"d001_t001": "用户关系与等级管理", ...}
        return await self._llm.complete_json(prompt)
```

**关键变化**: 即使 LLM 输出不稳定（每次生成不同标题），结构和关联不受影响。

### 2.4 Layer 3: 递归生成 + Bottom-up 综合 (增强现有体系)

借鉴 CodeWiki Algorithm 1:

```
Level 0 (Leaf Modules):
  - WikiPageAgent.generate() per module (现有)
  - 按 topo sort 顺序处理，先处理的模块摘要传给后续模块

Level 1 (Topic Pages):
  - LLM synthesize(child_leaf_docs, module_tree_subtree, dependency_info)
  - 替代当前 DomainOverviewComposer 的模板填充

Level 2 (Domain Overviews):
  - LLM synthesize(child_topic_docs, domain_tree_section, cross_domain_deps)
  - 替代当前 tree_linker._build_domain_overview_content 的截取逻辑

Level 3 (Repository Overview):
  - LLM synthesize(all_domain_overviews, complete_module_tree)
```

### 2.5 中文域名关联的彻底解决

**核心**: 用 `canonical_key` 替代所有启发式字符串匹配。

数据流变更:
```
ModuleTreeNode.canonical_key → compose 写入 page["domain_key"]
→ persist 写入 WikiPage.domain_key 属性
→ tree_linker 直接按 domain_key 分组（O(1) dict lookup）
→ 完全消除 _find_best_domain 启发式匹配
```

变更点:
| 文件 | 变更 |
|------|------|
| `wiki/graph_decomposer.py` | 新建: 核心分解算法 |
| `wiki/topic_structure_planner.py` | 重构为 TitleGenerator（仅生成标题） |
| `wiki/nodes/compose.py` | 使用 ModuleTree 替代 TopicPage |
| `wiki/tree_linker.py` | `_find_best_domain` → `dict[domain_key]` 查表 |
| `wiki/persistence.py` | MERGE 时写入 `domain_key` 属性 |
| `wiki/harness.py` | `domain_cache` 提升为 pipeline-level 单例 |
| `wiki/models.py` | WikiPage 增加 `domain_key` 可选字段 |

---

## 3. Harness + Agent-Driven 系统现存问题清单

### P0 — 架构矛盾（必须解决）

| # | 问题 | 根因 | 修复方案 |
|---|------|------|----------|
| 1 | CCB + Harness Gather 重复查询同一图数据 | 两套系统独立查询 | Harness 直接复用 CCB 的 `EnrichedDomainContext` |
| 2 | `domain_cache` 每个 leaf 新建 | `WikiGenerationHarness` 在 `_compose_single_leaf_domain` 中每次 new | 提升为 pipeline-level 单例，在 LangGraph configurable 中传递 |
| 3 | `repo_path`/`search_service` 未在 pipeline configurable 中传入 | `pipeline_orchestrator.py` 未注入 | 在 configurable 中传入这两个参数 |

### P1 — 质量控制缺陷

| # | 问题 | 根因 | 修复方案 |
|---|------|------|----------|
| 4 | L2 LLM Judge 是 stub | 未实现 | 实现 evaluate_l2 异步调用 LLM 做 factual grounding |
| 5 | L1 仅做形式检查 | evaluate_l1 用 `m.lower() in content.lower()` | 增加代码实体引用验证 |
| 6 | `repair()` 只看 4k 字符且不带工具 | 设计限制 | repair 阶段可带 graph 工具补充事实 |
| 7 | `evaluate` 仅当 L1 失败时运行 L2 | 逻辑设计 | L2 应独立运行于 L1 结果之外 |

### P2 — 性能与可维护性

| # | 问题 | 根因 | 修复方案 |
|---|------|------|----------|
| 8 | `_tool_grep_code` 全仓 rglob 无超时 | 设计遗漏 | 加 asyncio.timeout + 路径范围限制 |
| 9 | 环境变量 `int()` 无容错 | `HarnessConfig.from_env` 缺 try-except | 加 fallback default |
| 10 | `evaluate_l2` 标注 sync | 注释说将来 async | 直接声明为 async |
| 11 | `WorkingMemory` 用 `pop(0)` 截断 | FIFO 丢失重要早期上下文 | 改为 priority + FIFO 混合 |

### P3 — 中文域名专项（由 canonical_key 方案统一解决）

| # | 问题 | 根因 |
|---|------|------|
| 12 | 缺少 canonical domain ID | 依赖启发式字符串匹配 |
| 13 | `business_domain` 空时不覆盖旧值 | persistence MERGE 逻辑 |
| 14 | `_fix_ascii_only_titles` 不处理"中文但偏离"的标题 | 仅检查纯 ASCII |

---

## 4. 实施优先级

```
Sprint 1 — 确定性基础 + 中文域名修复 (P0 + P3):
  ① 新建 GraphModuleDecomposer（SCC + 拓扑排序 + Connected Component）
  ② 重构 TopicBasedStructurePlanner → TitleGenerator（LLM 仅生成标题）
  ③ 实现 canonical_key 贯穿管线（planning → compose → persist → link）
  ④ tree_linker 用 canonical_key 替代 _find_best_domain 启发式匹配
  ⑤ domain_cache 提升为 pipeline-level 单例

Sprint 2 — 质量提升 + CodeWiki 关键能力对齐 (P1):
  ⑥ 消除 CCB/Gather 重复查询（Harness 直接复用 EnrichedDomainContext）
  ⑦ 实现 L2 LLM Judge（factual grounding 检查）
  ⑧ repair() 增加工具调用能力
  ⑨ Bottom-up LLM synthesis 替代模板填充（借鉴 CodeWiki generate_parent_module_docs）
  ⑩ Dynamic Delegation: WikiPageAgent 增加 delegation tool（借鉴 CodeWiki generate_sub_module_documentation）
  ⑪ Cross-Module Registry: domain_cache 扩展为全局引用注册表

Sprint 3 — 性能优化 (P2):
  ⑫ grep_code 超时 + 范围限制
  ⑬ HarnessConfig 容错
  ⑭ WorkingMemory priority 策略
```

---

## 5. CodeWiki 开源实现分析 (github.com/FSoft-AI4Code/CodeWiki)

> 通过 `git clone` 实际阅读源码后的关键发现

### 5.1 论文描述 vs 实际实现的差异

| 论文描述 | 实际代码 | 影响 |
|----------|----------|------|
| "hierarchical decomposition inspired by dynamic programming" | `cluster_modules.py` 使用 **LLM** 做模块聚类（`call_llm(format_cluster_prompt(...))`） | 分解并非纯确定性，也依赖 LLM |
| "topological sorting for dependency ordering" | `get_processing_order()` 实为简单 **DFS**（子先于父） | 不是真正的拓扑排序 |
| "cross-module reference management via global registry" | `CodeWikiDeps.registry` 初始化为 **空 dict `{}`**，未见写入逻辑 | 功能未完全实现 |
| "dynamic delegation for complex modules" | 通过 pydantic_ai Tool `generate_sub_module_documentation` 实现 | 实现良好 |

### 5.2 CodeWiki 的核心架构（实际代码）

```
DocumentationGenerator.run()
├── DependencyGraphBuilder.build_dependency_graph()   # Tree-sitter AST → (components, leaf_nodes)
├── cluster_modules(leaf_nodes, components, config)   # LLM聚类 → module_tree (递归)
│   ├── format_cluster_prompt(components, current_tree) → LLM → 解析分组
│   └── 递归: 对每个子组再调 cluster_modules()
├── get_processing_order(module_tree)                  # DFS: 子先于父
└── generate_module_documentation()
    ├── for (leaf): AgentOrchestrator.process_module() # pydantic_ai Agent + tools
    │   ├── read_code_components (完整源码访问)
    │   ├── str_replace_editor (文档编辑)
    │   └── generate_sub_module_documentation (动态委托)
    └── for (parent): generate_parent_module_docs()    # LLM synthesize(child_docs + tree)
```

### 5.3 CodeWiki Agent 的工具集

| 工具 | 实现文件 | 作用 |
|------|----------|------|
| `read_code_components` | `agent_tools/read_code_components.py` | 通过 component_id 读取完整源码 |
| `str_replace_editor` | `agent_tools/str_replace_editor.py` | 编辑文档内容 |
| `generate_sub_module_documentation` | `agent_tools/generate_sub_module_documentations.py` | **动态委托**: 创建子 Agent 处理子模块 |

**关键**: `CodeWikiDeps` 包含:
- `absolute_repo_path` — 完整仓库路径
- `components: dict[str, Node]` — 所有代码组件 + 源码
- `module_tree` — 完整模块树（全局共享）
- `path_to_current_module` — 当前位置
- `current_depth` / `max_depth` — 递归深度控制
- `registry` — 全局引用注册表（但实际为空 dict）

### 5.4 对我们设计的影响

CodeWiki 的 clustering **也用 LLM**，但有关键差异：
1. **递归分解**: 当 token > `max_token_per_module` 时递归分解，保证每个叶子可被单个 Agent 处理
2. **Agent 拥有完整源码访问**: 通过 `components` dict 直接读取，非图查询
3. **Bottom-up synthesis 是真实的**: `generate_parent_module_docs()` 加载 child `.md` 文件 → LLM 综合
4. **Dynamic delegation 由 Agent 自行决策**: 复杂模块获得委托工具，Agent 自主判断是否拆分

---

## 6. 修订后的能力对齐矩阵（实施后 — 无遗留项）

| CodeWiki 能力 | CodeWiki 实际实现 | 实施后状态 | Sprint |
|---|---|---|---|
| Dependency Graph | Tree-sitter AST → 内存有向图 | ✅ FalkorDB + Tree-sitter（更强） | — |
| Entry Point ID | in-degree=0 leaf nodes | ✅ entity_roles entry_point | — |
| Hierarchical Decomp | **LLM clustering** + 递归 | ✅ GraphModuleDecomposer (SCC+拓扑+CC) + LLM title（更确定） | Sprint 1 |
| Processing Order | DFS 子先于父 | ✅ 拓扑排序全层级 bottom-up | Sprint 1 |
| Agent per Leaf | pydantic_ai Agent + tools | ✅ WikiPageAgent | — |
| Dynamic Delegation | `generate_sub_module_documentation` tool | ✅ 在 WikiPageAgent 增加 delegation tool | Sprint 2 |
| Cross-Module Registry | 空 dict（未完全实现） | ✅ domain_cache 升级 + 生成期引用注册 | Sprint 2 |
| Bottom-up Synthesis | LLM synthesize(child docs + tree) | ✅ DomainOverviewComposer 升级为 LLM synthesis | Sprint 2 |
| Evaluation | CodeWikiBench multi-judge | ✅ L1 + L2 LLM Judge | Sprint 2 |
| canonical_key | 不需要（不支持中文） | ✅ 贯穿全链路 | Sprint 1 |
| **我们的独有优势** | **CodeWiki 不具备** | | |
| 混合检索 (vector + property graph) | ❌ | ✅ | — |
| 置信度评分 + claim tracking | ❌ | ✅ | — |
| Incremental update (freshness API) | ❌ | ✅ | — |
| 中文业务域原生支持 | ❌ | ✅ | Sprint 1 |
| 多仓库跨域分类 | ❌ | ✅ | — |
| Wiki 搜索 + Q&A | ❌ | ✅ | — |

---

## 7. 完整对齐论文的实施路线图

### 7.1 对齐策略

> **核心思路**: 不是"抄袭"CodeWiki，而是"超越"它 — 用论文的理想架构 + 开源代码的实践教训 + 我们的独有优势。

CodeWiki 论文 vs 实际代码的差异给了我们机会：
- 论文描述的图算法分解是"理想"方案，但开源代码用了 LLM clustering
- 我们有 FalkorDB 持久化图存储，可以真正实现论文描述的图算法分解
- 这意味着我们可以比 CodeWiki 实际代码更忠实于论文的理想架构

### 7.2 三层架构对齐矩阵

| 论文章节 | CodeWiki 论文描述 | CodeWiki 实际实现 | 我们的实现路径 | 超越点 |
|---|---|---|---|---|
| §2.1 Dependency Graph | Tree-sitter AST → 有向图 | 同论文（graph_builder.py） | FalkorDB 已有完整依赖图 | **持久化 + 增量更新** |
| §2.2 Hierarchical Decomp | SCC + 拓扑 + CC 分解 | **LLM clustering** + 递归 | GraphModuleDecomposer: SCC + 拓扑排序 | **真正的图算法，比 CodeWiki 代码更确定** |
| §2.3 Recursive Agent | DFS bottom-up + delegation | pydantic_ai Agent + tools | WikiPageAgent + bottom-up + delegation tool | **混合检索提供更丰富上下文** |
| §2.4 Hierarchical Assembly | LLM synthesize(child docs) | generate_parent_module_docs() | ParentSynthesizer (新模块) | **canonical_key 保证结构一致性** |
| §3 CodeWikiBench | 4维 LLM Judge | 未在开源代码中 | L2 LLM Judge (4维) | **L1 确定性检查 + L2 LLM 双层评估** |

### 7.3 Phase 实施计划

#### Phase 1: 图算法分解 + Bottom-up 顺序 (对齐 §2.1-2.2)

**目标**: 结构确定性 + 中文域名修复

```
新建文件:
  wiki/graph_module_decomposer.py
    - GraphModuleDecomposer 类
    - _load_dependency_graph(repo_id) → 从 FalkorDB 加载
    - _compute_scc(graph) → Tarjan 算法 / FalkorDB 内置
    - _condense_graph(graph, sccs) → 合并循环依赖
    - _topological_sort(condensed) → 确定性处理顺序
    - _recursive_decompose(nodes, max_tokens) → 递归分解大模块
    - _assign_canonical_keys(tree) → 生成 slug ID

修改文件:
  wiki/pipeline_orchestrator.py
    - 用 GraphModuleDecomposer 替代 TopicBasedStructurePlanner 的结构规划
    - 处理顺序改为 bottom-up (叶子 → 父级)
  wiki/topic_structure_planner.py
    - 重构为 TitleGenerator: 只接收 canonical_key + 代码实体列表 → 生成可读标题
  wiki/tree_linker.py
    - _find_best_domain() 改为 canonical_key 精确匹配
  wiki/persistence.py
    - 新增 canonical_key 字段持久化
```

**验收标准**: 相同代码库运行 3 次，生成的模块树结构完全一致

#### Phase 2: 递归生成 + 综合 + 评估 (对齐 §2.3-2.4 + §3)

**目标**: 内容质量对齐

```
新建文件:
  wiki/parent_synthesizer.py
    - 接收 child docs → LLM 综合为 parent overview
    - 参考 CodeWiki generate_parent_module_docs() 模式

修改文件:
  wiki/page_agent.py
    - 增加 delegate_submodule tool (对齐 CodeWiki dynamic delegation)
    - 增加 read_source_code tool (对齐 CodeWiki read_code_components)
  wiki/harness.py
    - gather 阶段直接复用 EnrichedDomainContext (消除 CCB 重复)
    - domain_cache 改为 pipeline-level 注入
  wiki/harness_evaluator.py
    - 实现 evaluate_l2: 4维 LLM Judge (completeness, accuracy, readability, structure)
  wiki/nodes/compose.py
    - 父级页面改为调用 ParentSynthesizer 而非模板填充
```

**验收标准**: L2 评估平均分 ≥ 3.5/5.0

#### Phase 3: 优化 + 多模态 (增强)

```
修改文件:
  wiki/harness.py
    - gather 增加 API spec 解析 (OpenAPI/Swagger)
    - gather 增加 inline comment/docstring 专门提取
  wiki/page_agent.py
    - grep_code tool 增加超时和范围限制
  wiki/agent_config.py
    - HarnessConfig 增加容错回退
```

### 7.4 为什么这比 CodeWiki 更好

```
                    CodeWiki (论文)    CodeWiki (代码)    我们 (Phase 1+2 后)
分解确定性            理想化描述          LLM clustering      图算法 (SCC+拓扑)
持久化                无                  文件系统             FalkorDB 图存储
增量更新              不支持              不支持               freshness API
中文支持              不支持              不支持               canonical_key
检索能力              components dict     components dict     混合检索 (vector+graph)
评估                  CodeWikiBench       未实现              L1+L2 双层评估
Cross-module ref      论文提及            空 dict (未实现)     domain_cache + registry
```

---

## 参考文献

1. CodeWiki: Evaluating AI's Ability to Generate Holistic Documentation for Large-Scale Codebases. arXiv:2510.24428v6, ACL 2026. ([GitHub](https://github.com/FSoft-AI4Code/CodeWiki))
2. DocAgent: A multi-agent system for automated code documentation generation. ACL 2025 Demo.
3. RepoAgent: An LLM-powered open-source framework for repository-level code documentation generation. EMNLP 2024 Demo.
