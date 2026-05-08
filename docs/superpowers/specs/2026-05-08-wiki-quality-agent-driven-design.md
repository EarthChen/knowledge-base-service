# Wiki 质量修复 + Agent-Driven 生成引擎设计

**状态**: Implementing (Tasks 1-13 完成, 2026-05-08)  
**审阅**: sequential-thinking 深度审阅完成, 15 项发现已纳入  
**创建**: 2026-05-08  
**分支**: `feat/wiki-quality-agent-driven` (15 commits, 61 新增测试全部通过)  
**合并来源**:
- `PROPOSAL_20260508_135807_business_indexing_and_progress.md` (Closed, 剩余 gap)
- `PROPOSAL_20260508_150922_wiki_quality_remediation.md` (部分内容)
- `PROPOSAL_20260508_170009_wiki_generation_quality_deep_analysis.md` (分析报告)

---

## 1. 问题总结

### 1.1 质量扫描结果 (2026-05-08)

全量重新生成（business_id=default, 847 模块, 63 页面）后自动化扫描发现：

| 问题 | 影响范围 | 严重性 |
|------|---------|--------|
| CONTEXT_GAP 标记残留 | 部分页面 | P0 |
| Markdown 围栏未剥离 | 54% topic 页 | P0 |
| 调用链 100% 缺失 | 24/24 topic 页 | P0 |
| 左侧树空洞（仅 overview） | 55% section | P1 |
| Domain overview 过短 | 54% overview < 300 字 | P1 |
| Overview 路径绕过反幻觉 | 所有 domain overview | P1 |
| tree_linker 截断破坏 Markdown | 部分 overview | P2 |
| 进度 callback 未透传到 per-repo generate | 进度展示 | P2 |

### 1.2 根因

1. **CONTEXT_GAP**: cleanup 仅在 leaf compose 后执行，heal/aggregate 路径跳过；正则不一致（3 个文件各用不同 pattern）
2. **Markdown 围栏**: `_strip_fences` 仅剥离 `json` 围栏，不处理 `markdown`/`md`
3. **调用链缺失**: Indexer 只在 Function 层创建 CALLS (4370 条)，Module 层 CALLS = 0；Module→Function CONTAINS 仅 115/4921 (2.3%)
4. **空洞 section**: LLM 域分类粒度过细（40 域 / 847 模块 = 平均 21，但方差极大）
5. **虚构内容**: `__domains__` overview 由 `tree_linker.py` 组装，使用 `dependency_graph.py` 的 LLM domain description（仅 `SYSTEM_JSON_ONLY` 约束，无反幻觉）
6. **进度透传**: `generate_business_wiki` 中 per-repo `generate()` 未传递 `progress_callback`

---

## 2. 设计概览

分 4 层递进实施，每层构建在前一层基础上：

```
Layer 1: Bug Fix（P0 修复）          ← ~2 天
Layer 2: Graph Fix（图数据补全）      ← ~2 天
Layer 3: Classification Fix（域优化）  ← ~1 天
Layer 4: Agent-Driven Engine（核心）   ← ~1 周
```

---

## 3. Layer 1: P0 Bug Fix

### 3.1 CONTEXT_GAP 正则统一

**统一 pattern** (替换 3 个文件中的不同版本):

```python
# 统一到 wiki/constants.py 或 wiki/cleanup.py
import re
CONTEXT_GAP_RE = re.compile(
    r"<!--\s*CONTEXT_GAP[:\s：][\s\S]+?\s*-->",
    re.DOTALL,
)
```

**变更文件**:
| 文件 | 当前 pattern | 操作 |
|------|-------------|------|
| `wiki/nodes/compose.py` | `r"<!--\s*CONTEXT_GAP[:\s：](.+?)\s*-->"` | 导入统一 pattern |
| `wiki/page_agent.py` | `r"<!--\s*CONTEXT_GAP:\s*(.+?)\s*-->"` | 导入统一 pattern |
| `wiki/quality_evaluator.py` | `r"<!--\s*CONTEXT_GAP:\s*(.+?)\s*-->"` | 导入统一 pattern |

### 3.2 cleanup 全路径覆盖

在所有写 `page_dict["content"]` 的路径末尾调用 `cleanup_context_gaps`:

| 文件 | 函数 | 操作 |
|------|------|------|
| `wiki/nodes/heal.py` | `_heal_single_page` | content 赋值后调用 cleanup |
| `wiki/nodes/aggregate.py` | `compose_parent_pages_node` | content 赋值后调用 cleanup |
| `wiki/nodes/persist.py` (或 finalize) | persist 前 | **兜底**: 遍历所有 page 调用 cleanup |

### 3.3 Markdown 围栏剥离

```python
# wiki/json_robust.py._strip_fences
# 通用模式: 剥离任何语言标记的围栏（json/markdown/md/html/text/...）
text = re.sub(r"^```\w*\s*\n?", "", text, count=1)
text = re.sub(r"\n?```\s*$", "", text, count=1)
```

`_parse_wiki_json_response` fallback 路径也调用 `_strip_fences`。

### 3.4 tree_linker 截断修复

```python
# wiki/tree_linker.py._build_domain_overview_content
# 原: summary = " ".join(non_heading)[:150]
# 改: 截断到句子/Markdown 安全边界
def _safe_truncate(text: str, max_len: int = 150) -> str:
    if len(text) <= max_len:
        return text
    cut = text[:max_len]
    # 不在 backtick 内截断
    if cut.count('`') % 2 != 0:
        last_tick = cut.rfind('`')
        if last_tick > 0:
            cut = cut[:last_tick]
    # 回退到最近的句号或空格
    for sep in ('。', '. ', '，', ', ', ' '):
        pos = cut.rfind(sep)
        if pos > max_len // 2:
            return cut[:pos + len(sep)].rstrip()
    return cut.rstrip()
```

同时匹配 `## 概述` | `## Overview`。

### 3.5 进度 callback 透传

```python
# wiki/service.py:generate_business_wiki 中
# 原: await self.generate(...)  # 无 progress_callback
# 改: await self.generate(..., progress_callback=progress_callback)
```

### 3.6 测试清单

- [ ] `test_cleanup_context_gaps`: 覆盖英文冒号、中文冒号、空格、多行、空标记
- [ ] `test_strip_fences_markdown`: 验证 `markdown`/`md`/`json` 围栏均被剥离
- [ ] `test_safe_truncate`: backtick 内不截断
- [ ] `test_progress_callback_per_repo`: 验证 per-repo generate 触发 progress update

---

## 4. Layer 2: Graph Data Fix

### 4.1 补全 Module → CONTAINS → Function

**Module 节点语义定义**:
在当前 indexer 中，Module 节点代表**文件级或类级**的代码分组单元：
- Java: 一个 `.java` 文件中的顶层 Class/Interface = 一个 Module
- Python: 一个 `.py` 文件 = 一个 Module
- Go: 一个 `.go` 文件 = 一个 Module

**CONTAINS 补全策略**（按优先级）:
1. **FQN 前缀匹配**: 若 Function.fqn 以 Module.fqn 为前缀（如 `com.example.UserService.getUser` 属于 `com.example.UserService`），创建 CONTAINS
2. **file_path 匹配**: 若 Function.file_path == Module.file_path，创建 CONTAINS
3. **回退**: 无法匹配的 Function 记录日志但不创建关系

**位置**: indexer 后处理步骤（新建 `indexer/post_process.py` 或在现有 indexer 中添加）

**逻辑**:
1. 查询所有 Function 节点: `MATCH (f:Function) RETURN f.name, f.fqn, f.file_path`
2. 查询所有 Module 节点: `MATCH (m:Module) RETURN m.name, m.fqn, m.file_path`
3. 按 FQN 前缀 → file_path 顺序匹配
4. 批量创建 `(module)-[:CONTAINS]->(function)` 关系，每 100 条一次 Cypher

**预期**: CONTAINS 覆盖率从 2.3% → 90%+

### 4.2 CCB Cypher 查询改造

**文件**: `wiki/cypher_queries.py`

```cypher
-- 替换 call_chain_cypher (Module→Module 不存在)
-- 新查询: Function CALLS 聚合到 Module 层
MATCH (m1:Module)-[:CONTAINS]->(f1:Function)-[:CALLS]->(f2:Function)<-[:CONTAINS]-(m2:Module)
WHERE m1.name IN $names AND m1 <> m2
RETURN DISTINCT m1.name AS caller_module, m2.name AS callee_module,
       collect(DISTINCT f1.name)[..5] AS sample_caller_fns,
       collect(DISTINCT f2.name)[..5] AS sample_callee_fns
ORDER BY caller_module, callee_module
```

**文件**: `wiki/content_context_builder.py`

更新 `_query_call_chains` 和 `_query_method_call_chains` 使用新 Cypher。

### 4.3 可选：物化 Module-level CALLS

在 indexer 后处理中，基于 Function CALLS 创建聚合边：
```cypher
MATCH (m1:Module)-[:CONTAINS]->(f1:Function)-[:CALLS]->(f2:Function)<-[:CONTAINS]-(m2:Module)
WHERE m1 <> m2
WITH m1, m2, count(*) AS weight
MERGE (m1)-[r:CALLS]->(m2)
SET r.weight = weight, r.aggregated = true
```

### 4.4 测试清单

- [ ] `test_post_process_contains`: 验证 CONTAINS 关系被正确创建
- [ ] `test_ccb_call_chain_from_functions`: 验证新 Cypher 返回 Module 级调用链
- [ ] `test_call_chain_not_empty`: 集成测试，verify 至少部分模块有调用链数据

---

## 5. Layer 3: Domain Classification Fix

### 5.1 域分类优化（混合策略）

**文件**: `wiki/dependency_graph.py`

**借鉴 CodeWiki 的特征导向划分 + DeepWiki 的目录结构辅助**：

采用混合策略（图拓扑连通性 + LLM 语义分类），而非纯 LLM 分类：

1. **第一步（图拓扑预划分）**: 利用 FalkorDB 中的 CALLS 关系，计算模块间调用紧密度，通过连通分量或社区发现（Louvain/Leiden）给出初始分组建议
2. **第二步（目录结构辅助）**: 同一目录下的模块倾向归入同一域
3. **第三步（LLM 语义分类）**: 在预划分基础上，LLM 进行语义微调和命名

在 prompt 中增加约束：
```
约束:
1. 每个域至少包含 3 个模块，禁止单模块域
2. 总域数量不超过 max(15, total_modules / 20)
3. domain.description 必须且仅能基于其 modules 的已知信息概括，禁止添加不在模块中体现的能力描述
4. 若无法确定某模块归属，归入"其他"域
5. 参考以下预分组建议（基于代码调用关系和目录结构）: {pre_groups}
```

### 5.2 小域合并后处理

在域分类结果返回后，增加后处理：

```python
def merge_small_domains(domains: list[DomainNode], min_size: int = 3) -> list[DomainNode]:
    """Merge domains with fewer than min_size modules into siblings."""
    large = [d for d in domains if len(d.modules) >= min_size]
    small = [d for d in domains if len(d.modules) < min_size]
    
    for sd in small:
        # 找最相似的大域（按模块名文本相似度）
        best = max(large, key=lambda ld: _similarity(sd, ld))
        best.modules.extend(sd.modules)
    
    return large
```

### 5.3 Overview 反幻觉

**文件**: `wiki/dependency_graph.py`

将 `SYSTEM_JSON_ONLY` 替换为带反幻觉约束的 system prompt:

```python
SYSTEM_DOMAIN_CLASSIFICATION = """Reply with JSON only. No markdown fences.

CRITICAL RULES:
1. domain.description MUST only summarize capabilities that are directly evidenced by the module names and their known functionality
2. Do NOT invent capabilities not reflected in the modules (e.g., do not mention "privacy configuration" unless a module explicitly handles it)
3. If unsure about a domain's scope, use a conservative generic description
"""
```

### 5.4 小域页面合并

当域仅有 1-2 模块时：
- 不生成单独的 overview + topic 两个页面
- 合并为一个内容完整的单页

### 5.5 Overview 自底向上合成（借鉴 CodeWiki Bottom-Up Synthesis）

当前 overview 由 `tree_linker.py` 使用 `domain.description`（LLM 弱约束文本）直接生成。
改为：先生成所有子 topic 页面，再从子页面内容聚合生成 overview。

```python
def _build_domain_overview_from_children(domain, child_pages):
    """基于已生成的子页面内容聚合 overview，而非 LLM 凭空生成。"""
    child_summaries = [extract_executive_summary(p) for p in child_pages]
    # overview = 确定性模板 + 子页面摘要聚合
    # 不再使用 domain.description
```

这保证 overview 内容 100% 来源于已验证的子页面，消除虚构风险。

### 5.6 测试清单

- [ ] `test_merge_small_domains`: 验证小域合并逻辑
- [ ] `test_domain_description_grounded`: 验证反幻觉 prompt 生效（描述不含臆造内容）
- [ ] `test_single_module_domain_merged`: 验证单模块域不产生空洞 overview

---

## 6. Layer 4: Agent-Driven Generation Engine

### 6.1 架构变更

```
当前:
  CCB(全量预查询) → 大prompt → LLM单次生成 → Agent修补CONTEXT_GAP → persist

目标:
  CCB(轻量基线) → WikiPageAgent(14 tools) → 迭代生成 → 质量验证 → persist
                   ↑ query_call_chain
                   ↑ read_code / grep_code / read_source_snippet
                   ↑ query_callers / query_callees / query_implementations
                   ↑ search_entities / query_module_detail
                   ↑ query_domain_dependencies / read_wiki_page / list_files
```

### 6.2 WikiPageAgent 改造

**文件**: `wiki/page_agent.py`

当前 `WikiPageAgent.enrich()` 仅处理含 CONTEXT_GAP 的页面。改造为：

```python
class WikiPageAgent:
    async def generate(
        self,
        module_names: list[str],
        domain_name: str,
        baseline_context: dict,  # CCB 轻量基线
        page_structure: str,     # 期望的页面结构
    ) -> str:
        """Agent-Driven: 自主查询上下文并生成完整 Wiki 页面。"""
        ...

    async def enrich(self, content: str, ...) -> str:
        """保留: 后处理修补 CONTEXT_GAP (fallback 路径)。"""
        ...
```

### 6.3 Agent System Prompt

```python
AGENT_GENERATE_SYSTEM = """你是一个代码知识库内容生成 Agent。你的任务是为指定代码模块生成结构化的 Wiki 页面。

## 输出结构
按以下章节顺序生成 Markdown：

1. ## 概述
   - 模块职责、核心类/接口
   - 使用 search_entities + query_module_detail 获取信息

2. ## 核心业务流程
   - 使用 query_call_chain + query_callers + query_callees 获取调用链
   - 基于真实调用链生成 Mermaid sequenceDiagram
   - 若调用链为空，尝试 read_code 从代码中推断关键流程
   - 仍无法获取则标记 CONTEXT_GAP

3. ## 关键实现
   - 使用 read_code / read_source_snippet 获取核心方法实现
   - 重点描述业务逻辑和设计模式

4. ## 依赖关系
   - 使用 query_domain_dependencies + query_implementations
   - 描述模块间依赖和接口实现关系

## 约束
- 100% 代码溯源：所有描述必须基于工具查询的真实信息
- 严禁编造：不确定的内容标记 <!-- CONTEXT_GAP: description -->
- 每个工具最多调用 {max_rounds} 次
- 工具返回空结果时，记录为 CONTEXT_GAP 而非编造
"""
```

### 6.4 路由策略

在 `topic_page_composer.py` 或 `compose.py` 中添加路由逻辑：

```python
async def _generate_page(module_names, domain_name, graph_store, llm, config):
    agent_enabled = config.get("agent_driven_generation", False)
    function_count = sum(get_function_count(m, graph_store) for m in module_names)
    
    if not agent_enabled:
        # Agent 关闭时走 CCB 路径
        content = await _ccb_single_shot_generate(...)
    else:
        # Agent-Driven 路径 (默认全量启用)
        # 简单模块用较少轮次，复杂模块用完整轮次
        max_rounds = 3 if function_count < SIMPLE_THRESHOLD else 10
        agent = WikiPageAgent(graph_store=graph_store, llm=llm)
        baseline = await _lightweight_ccb(module_names, graph_store)
        content = await agent.generate(
            module_names=module_names,
            domain_name=domain_name,
            baseline_context=baseline,
            page_structure=UNIFIED_PAGE_STRUCTURE,
            max_rounds=max_rounds,
        )
    
    return content
```

### 6.5 拓扑排序生成顺序（借鉴 CodeWiki）

在 Agent-Driven 批次中，按依赖图拓扑排序确定生成顺序：

```python
async def _topological_generate(modules, graph_store, agent):
    """按依赖关系拓扑排序生成，保证被引用模块先生成。"""
    dep_graph = await _build_dependency_graph(modules, graph_store)
    
    # 处理循环依赖：SCC 分解，同一 SCC 内的模块视为一组同时生成
    sccs = tarjan_scc(dep_graph)
    ordered = topological_sort_sccs(sccs)  # SCC 间拓扑排序
    
    generated_pages = {}
    for scc_group in ordered:
        page = await agent.generate(
            module_names=scc_group,
            # 只传已生成页面的摘要，而非全文（控制 context 大小）
            already_generated_summaries={
                k: extract_executive_summary(v) 
                for k, v in generated_pages.items()
            },
        )
        generated_pages.update({m: page for m in scc_group})
    
    return generated_pages
```

好处：Agent 生成某模块时，可以引用其依赖模块的已生成摘要，内容更连贯。循环依赖通过 SCC 分解处理。

### 6.6 生成后源码引用验证（借鉴 DeepWiki）

Agent 生成完成后，增加引用验证步骤：

```python
async def _verify_citations(content: str, graph_store) -> tuple[str, list[str]]:
    """验证生成内容中提到的实体名是否存在于图中。"""
    mentioned_entities = extract_entity_names(content)
    verified = []
    unverified = []
    for name in mentioned_entities:
        exists = await graph_store.node_exists(name)
        if exists:
            verified.append(name)
        else:
            unverified.append(name)
    
    if unverified:
        # 标记不可验证的引用
        for name in unverified:
            content = content.replace(
                name, f"{name}<!-- UNVERIFIED_REFERENCE -->"
            )
    
    return content, unverified
```

### 6.7 Token 消耗控制

| 控制手段 | 值 |
|---------|---|
| Agent 最大工具调用轮次（复杂模块） | 10 |
| Agent 最大工具调用轮次（简单模块） | 3 |
| 每个工具返回结果上限 | 2000 tokens |
| 简单模块阈值 (SIMPLE_THRESHOLD) | < 3 Functions (基于平均 2.7 Functions/Module) |
| Agent 总输出上限 | 4000 tokens |
| 并发 Agent 数 | 3 (避免 LLM API 过载) |
| Agent 超时 | 120 秒 / 页面 |

**成本估算**:
- 单页 Agent 路径: ~10,500 tokens (System 500 + 5 轮×1200 + 输出 4000)
- 单页 CCB 路径: ~3,000-5,000 tokens
- 24 topic × 10,500 + 39 overview × 3,000 ≈ **370K tokens / 次全量生成**
- 增幅: ~2-3x (vs 当前纯 CCB)

### 6.6 Fallback 策略

```
Agent 生成 → 超时(>120s) / LLM API 错误 / 输出 < 200 chars
    → 自动降级到 CCB + 单次生成
    → 仍然失败
    → 生成最小骨架页面 + CONTEXT_GAP 标记

Agent 部分成功 → 生成了 3/4 个 section 但最后一个失败
    → 保留已成功的 section + 对失败 section 标记 CONTEXT_GAP
```

### 6.7 配置开关

```python
# config.yaml 或环境变量
WIKI__AGENT_DRIVEN_GENERATION: bool = False  # 默认关闭，逐步开启
WIKI__AGENT_MAX_TOOL_ROUNDS: int = 10       # 复杂模块最大轮次
WIKI__AGENT_SIMPLE_ROUNDS: int = 3          # 简单模块最大轮次
WIKI__AGENT_SIMPLE_THRESHOLD: int = 3       # 简单/复杂分界 (Function 数)
WIKI__AGENT_TIMEOUT_SECONDS: int = 120      # 单页超时
```

### 6.8 测试清单

- [ ] `test_agent_generate_basic`: Agent 能生成包含所有章节的完整页面
- [ ] `test_agent_tool_usage`: Agent 在生成过程中调用了 query_call_chain 等工具
- [ ] `test_agent_fallback_on_error`: Agent 失败时正确降级到 CCB 路径
- [ ] `test_agent_max_rounds_limit`: 验证轮次限制生效
- [ ] `test_agent_no_hallucination`: 验证 Agent 输出不含 FalkorDB 中不存在的实体名
- [ ] `test_simple_module_fewer_rounds`: 简单模块用 max_rounds=3
- [ ] `test_agent_context_gap_on_empty_tools`: 工具返回空时标记 CONTEXT_GAP 而非编造
- [ ] `test_agent_behavior_verification`: Agent 生成了调用链但未调用 query_call_chain 工具 → 警告
- [ ] `test_agent_partial_success`: Agent 3/4 section 成功、1 section 失败 → 保留成功部分
- [ ] `test_topological_sort_with_cycles`: 循环依赖通过 SCC 正确处理
- [ ] `test_overview_from_children`: Overview 内容 100% 来源于子页面摘要

---

## 7. 执行顺序

```
Phase 1 (Day 1-2): Layer 1 — P0 Bug Fix [无外部依赖]
  ├── 正则统一 + cleanup 全路径覆盖
  ├── Markdown 围栏剥离（通用 \w* 模式）
  ├── tree_linker 截断修复 + 中文标题匹配
  ├── 进度 callback 透传
  └── 测试 + 部署验证

Phase 2 (Day 3-4): Layer 2 — Graph Data Fix [无外部依赖]
  ├── 定义 Module 语义 + CONTAINS 补全策略（FQN 优先 → file_path 回退）
  ├── Indexer 后处理: 补全 CONTAINS 关系
  ├── CCB Cypher 查询改造
  └── 测试 + 重新索引验证

Phase 3 (Day 5): Layer 3 — Domain Classification Fix [依赖 Phase 2]
  ├── 混合域分类（图拓扑预分组 + 目录辅助 + LLM 微调）
  ├── 小域合并后处理
  ├── Overview 反幻觉 (SYSTEM_DOMAIN_CLASSIFICATION)
  └── 测试 + 重新生成验证

Phase 4a (Day 6-8): Layer 4 Core — Agent 基础实现 [依赖 Phase 2]
  ├── WikiPageAgent.generate() 实现
  ├── Agent System Prompt 初版
  ├── 路由策略（全量 Agent，简单/复杂分轮次）
  ├── Fallback 机制（超时 120s / 输出 < 200 chars / 部分成功保留）
  ├── 配置开关
  └── 基础测试

Phase 4b (Day 9-10): Layer 4 Advanced — 高级特性
  ├── 拓扑排序 + SCC 循环依赖处理
  ├── 自底向上合成（Overview 基于子页面聚合）
  ├── 源码引用验证（backtick 内实体检查）
  ├── Agent 行为验证层
  ├── A/B 对比测试（Agent vs CCB）
  └── Prompt 调优迭代

Phase 5 (Day 11-12): 集成验证
  ├── 全量重新索引 + 生成
  ├── 质量扫描对比（before vs after）
  ├── Token 消耗分析
  ├── A/B 质量评分对比
  └── 文档更新
```

---

## 8. 成功标准

| 指标 | 当前值 | 目标值 |
|------|--------|--------|
| CONTEXT_GAP 残留页面 | 2+ | 0 |
| Markdown 围栏页面 | 54% | 0% |
| 调用链覆盖率（图数据驱动） | 0% | ≥ 60% |
| 调用链覆盖率（含 Agent 推断） | 0% | ≥ 75% |
| 空洞 section 比例 | 55% | ≤ 20% |
| Overview < 300 字 | 54% | ≤ 20% |
| 虚构内容页面 | 存在 | 0（所有描述可溯源） |
| 进度展示完整性 | 缺少 per-repo | 全阶段覆盖 |
| 实体引用验证通过率 | 未测量 | ≥ 90% |

**质量评估方案（A/B 对比）**:
对同一批模块，同时用 Agent 路径和 CCB 路径生成，对比：
- 内容长度和结构完整性
- 调用链/代码片段覆盖率
- LLM 评分（准确性/完整性/可读性 1-5 分）
- 提到的实体在图中存在的比例

---

## 9. 行业方案借鉴清单

基于 CodeWiki (ACL 2026)、DeepWiki (Devin)、Karpathy CodeWiki 的分析，以下是可借鉴且纳入本设计的要点：

### 9.1 已纳入本设计的借鉴

| 来源 | 借鉴点 | 纳入位置 |
|------|--------|---------|
| CodeWiki | Agent + Tool Calling 作为主生成引擎 | Layer 4 |
| CodeWiki | Agent 验证：查询 → 确认 → 写入（防幻觉） | Layer 4 Agent System Prompt |
| DeepWiki | AST 驱动的准确依赖图 | Layer 2（补全 CONTAINS） |
| DeepWiki | 目录结构辅助域分类 | Layer 3 域分类约束 |

### 9.2 建议追加纳入的借鉴

| 来源 | 借鉴点 | 影响设计 | 建议 |
|------|--------|---------|------|
| CodeWiki | **拓扑排序生成顺序** — 先生成叶子模块，再合成父级。保证引用已生成模块。 | Layer 4 生成流程 | 在 Agent-Driven 批次中，按依赖图拓扑排序确定生成顺序 |
| CodeWiki | **自底向上合成** — 子模块文档 → 父级 overview。overview 不再由 LLM 凭空生成，而是基于已有子文档聚合。 | Layer 3 + Layer 4 | 重构 overview 生成为「基于子页面内容的聚合」而非独立 LLM 生成 |
| CodeWiki | **特征导向模块划分** — 基于依赖图连通分量 + 模块化度量，而非纯 LLM 分类。 | Layer 3 域分类 | 混合策略：图拓扑连通性 + LLM 语义分类，双重约束 |
| CodeWiki | **动态委派** — 根据模块复杂度动态决定是否深入，而非固定阈值。 | Layer 4 路由策略 | 让 Agent 自评复杂度后决定深入程度 |
| DeepWiki | **源码引用验证** — 生成后对比源码验证。 | Layer 4 质量验证 | 在 Agent 生成后增加引用验证步骤 |
| Karpathy | **增量更新精确化** — source_files 前置数据 + git diff 标记过期。 | 增量生成改进 | 每页记录 source entities，变更时仅重生成关联页面 |

### 9.3 暂不纳入但值得关注的方向

| 来源 | 方向 | 原因 |
|------|------|------|
| CodeWiki | 递归子 Agent 无限深度委派 | 当前规模不需要，且 Token 消耗难控制 |
| Karpathy | LLM 自维护索引（无 RAG） | 我们已有 FalkorDB 图，不需要另建索引 |
| DeepWiki | Docker Compose 一键部署 | 属于运维改进，与本次质量修复无关 |
| DeepWiki | 交互式架构图 UX | 属于前端体验，与本次质量修复无关 |

---

## 10. 风险与缓解

| 风险 | 缓解 |
|------|------|
| Agent Token 消耗过高 | 简单/复杂分轮次；输出上限；成本估算 ~370K tokens/次 |
| Agent 生成时间过长 | 并发限制 + 120s 超时降级到 CCB |
| 新 Cypher 查询性能 | 添加 FalkorDB 索引；批量查询 |
| 域合并导致域名变化 | 合并后重新生成导航树 |
| Agent 行为不可预测 | 保留 CCB fallback；A/B 对比验证；行为验证层 |
| Indexer 后处理增加索引时间 | 批量 Cypher；可配置开关 |
| Agent 不调用工具直接编造 | 行为验证：生成调用链但未调用 query_call_chain → 警告 |
| 循环依赖导致拓扑排序失败 | SCC 分解，同 SCC 内模块同组生成 |
| Phase 4 时间偏乐观 | 拆分为 4a(基础) + 4b(高级)，可独立交付 |

---

## 11. 实施完成度追踪 (2026-05-08 更新)

### Layer 1: P0 Bug Fix — ✅ 全部完成
| 节 | 内容 | 状态 | 备注 |
|----|------|------|------|
| 3.1 | CONTEXT_GAP 正则统一 | ✅ | `wiki/context_gap.py` — T1 |
| 3.2 | cleanup 全路径覆盖 | ✅ | heal.py + aggregate.py — T2 |
| 3.3 | Markdown 围栏剥离 | ✅ | json_robust.py + topic_page_composer.py — T3 |
| 3.4 | tree_linker 截断修复 | ✅ | `_safe_truncate` + 中文标题 — T4 |
| 3.5 | 进度 callback 透传 | ✅ | service.py — T5 |
| 3.6 | 测试清单 | ✅ | 全部覆盖 |

### Layer 2: Graph Data Fix — ✅ 核心完成, ⚠️ 接入待办
| 节 | 内容 | 状态 | 备注 |
|----|------|------|------|
| 4.1 | CONTAINS 补全策略 | ✅ 逻辑 | `indexer/post_process.py` — T6 |
| 4.1 | 接入 indexer 流程 | ❌ 待接入 | `supplement_contains_relationships` 需要在 indexer pipeline 中调用 |
| 4.2 | CCB Cypher 查询改造 | ✅ | `call_chain_cypher` 已更新 — T7 |
| 4.2 | content_context_builder 适配 | ❌ 待适配 | CCB 中使用新 Cypher 返回的 caller_functions/callee_functions |
| 4.3 | 物化 Module-level CALLS | ❌ 可选 | 设计中标记为可选 |

### Layer 3: Domain Classification Fix — ⚠️ 部分完成
| 节 | 内容 | 状态 | 备注 |
|----|------|------|------|
| 5.1 | 域分类优化 | ⚠️ 部分 | 反幻觉 prompt ✅, 图拓扑预分组 + 目录辅助 ❌ |
| 5.2 | 小域合并后处理 | ✅ | `wiki/domain_merger.py` — T8 |
| 5.3 | Overview 反幻觉 prompt | ✅ | `SYSTEM_DOMAIN_CLASSIFICATION` — T8 |
| 5.4 | 小域页面合并 | ❌ 未实现 | 1-2 模块域 → 单页合并 |
| 5.5 | Overview 自底向上合成 | ✅ 逻辑 | `wiki/overview_synthesizer.py` — T12, 未接入 pipeline |

### Layer 4: Agent-Driven Engine — ⚠️ 核心已实现, 接入待办
| 节 | 内容 | 状态 | 备注 |
|----|------|------|------|
| 6.2 | WikiPageAgent.generate() | ✅ | `wiki/page_agent.py` — T9 |
| 6.3 | Agent System Prompt | ✅ | `wiki/agent_prompts.py` — T9 |
| 6.4 | 路由策略 + 配置开关 | ✅ 逻辑 | `wiki/agent_config.py` — T10 |
| 6.4 | 接入 compose pipeline | ❌ 待接入 | AgentConfig 未 wire 到 `_compose_single_leaf_domain` |
| 6.5 | 拓扑排序 + SCC | ✅ | `wiki/topo_sort.py` — T11 |
| 6.5 | 接入生成流程 | ❌ 待接入 | 拓扑排序未 wire 到页面生成批次 |
| 6.6 | 源码引用验证 | ✅ | `wiki/citation_verifier.py` — T13 |
| 6.6 | 接入质量验证 | ❌ 待接入 | 未在 pipeline 中调用 |
| 6.7 | Fallback + 配置 | ✅ | generate() 内置 skeleton fallback |

### 待完成项汇总 (Pipeline 接入层)
| # | 内容 | 优先级 | 说明 |
|---|------|--------|------|
| W1 | `supplement_contains_relationships` 接入 indexer | P0 | 新 Cypher 查询依赖 CONTAINS 关系 |
| W2 | `AgentConfig` + `generate()` 接入 compose pipeline | P0 | Agent-Driven 生效的关键 |
| W3 | `content_context_builder.py` 适配新 Cypher 返回 | P1 | caller_functions/callee_functions 字段 |
| W4 | `overview_synthesizer` 接入 tree_linker/aggregate | P1 | 消除 overview 虚构 |
| W5 | `citation_verifier` 接入质量验证 | P1 | 检测幻觉实体 |
| W6 | `topo_sort` 接入页面生成批次 | P2 | 优化生成顺序 |
| W7 | 图拓扑预分组 + 目录辅助域分类 | P2 | 需额外开发 |
| W8 | 小域页面合并 (1-2 模块 → 单页) | P2 | 需在 compose 中处理 |
