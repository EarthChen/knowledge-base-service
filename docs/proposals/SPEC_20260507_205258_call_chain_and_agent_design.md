# 设计规格: 方法级调用链 + Cypher 解耦 + Agent Tool-Calling

**日期**: 2026-05-07  
**状态**: Approved  
**前置**: PROPOSAL_20260507_193240_context_augmentation_strategy.md (Phase 1 已实施, Phase 2 已实施)

---

## 1. 目标

在 Phase 1 (上下文增强) 和 Phase 2 (Bottom-Up Synthesis) 的基础上，实施三项改进：

| 优先级 | 任务 | 价值 |
|--------|------|------|
| P0 | 方法级端到端调用链构建器 | 立竿见影提升 Wiki 中业务流程描述的准确性和完整性 |
| P1 | Cypher 查询解耦 | 消除模块间私有常量耦合，为 Agent 和调用链共享查询做准备 |
| P2 | Agent Tool-Calling 基础框架 | 让 LLM 在生成过程中按需查询补充上下文，解决 CONTEXT_GAP |

## 2. P0: 方法级调用链构建器

### 2.1 新增文件: `wiki/call_chain_builder.py`

**职责**: 从 FalkorDB 图谱构建方法级端到端调用链，为 Wiki 生成提供结构化调用路径上下文。

**算法**: 单次 Cypher 批量查询 + Python 层 BFS

**数据流**:
```
graph_store → Cypher 查询 (FUNCTION_CALLS_CY)
            → adjacency_list: dict[str, list[CallTarget]]
            → BFS from entry methods (depth ≤ 5)
            → list[MethodCallChain]
```

### 2.2 数据结构

```python
@dataclass
class CallChainNode:
    func_name: str
    module_name: str
    file_path: str
    signature: str

@dataclass
class MethodCallChain:
    entry_method: str
    entry_module: str
    chain: list[CallChainNode]
    depth: int

class CallChainBuilder:
    MAX_DEPTH = 5
    MAX_CHAINS = 20
    MAX_QUERY_RESULTS = 300

    def __init__(self, graph_store: Any) -> None: ...

    async def build_chains(
        self,
        module_names: list[str],
        max_depth: int = 5,
        max_chains: int = 20,
    ) -> list[MethodCallChain]:
        """单次 Cypher 查询获取作用域内所有 Function→Function CALLS 对，
        Python 层 BFS 构建端到端调用链。"""

    def format_for_prompt(self, chains: list[MethodCallChain]) -> str:
        """格式化为 prompt 参考数据段。"""
```

### 2.3 Cypher 查询

```cypher
-- FUNCTION_CALLS_CY: 获取模块作用域内所有方法级直接调用
-- OPTIONAL MATCH 反查 callee 所属模块，解决方法名重名问题
MATCH (m:Module)-[:CONTAINS*1..3]->(cf:Function)-[:CALLS]->(ct:Function)
WHERE m.name IN $names
OPTIONAL MATCH (mt:Module)-[:CONTAINS*1..3]->(ct)
RETURN cf.name AS caller_method, ct.name AS callee_method,
       m.name AS caller_module, coalesce(mt.name, '') AS callee_module,
       coalesce(cf.file, '') AS caller_file,
       coalesce(ct.file, '') AS callee_file,
       coalesce(cf.signature, '') AS caller_sig,
       coalesce(ct.signature, '') AS callee_sig
LIMIT 300
```

### 2.4 BFS 逻辑

1. 构建 `adjacency: dict[str, list[CallTarget]]`，key 使用 `f"{module}.{func}"` 避免同名方法混淆
2. 识别入口方法：结合 `entity_roles`（entry_point 模块的公共方法优先）+ 启发式（无被调用者的方法）
3. BFS 遍历：`visited` 集合防环，深度限制 `max_depth`
4. 收集有序链路列表，按深度排序，取 top `max_chains`

### 2.5 集成点

1. **`_generate_single_module_summary`**: 调用 `CallChainBuilder.build_chains()` 获取模块内调用链，注入到 prompt
2. **`build_topic_detail_prompt`**: 新增 `## 参考数据：方法级调用链` 段
3. **`EnrichedDomainContext`**: 新增 `method_call_chains: list[dict]` 字段
4. **`ContentContextBuilder.build_context`**: 新增 `_query_method_call_chains` 并行任务

## 3. P1: Cypher 查询解耦

### 3.1 新增文件: `wiki/cypher_queries.py`

**职责**: 集中管理所有被多个模块共享的 Cypher 查询常量。

**迁移清单**:

| 常量 | 原位置 | 使用者 |
|------|--------|--------|
| `METHODS_CY` | content_context_builder.py | ContentContextBuilder |
| `METHOD_CALL_CHAIN_CY` | content_context_builder.py | ContentContextBuilder |
| `ENUMS_CY` | content_context_builder.py | ContentContextBuilder |
| `SNIPPETS_CY` | content_context_builder.py | ContentContextBuilder, pipeline_nodes._generate_single_module_summary |
| `CHUNK_SNIPPETS_CY` | content_context_builder.py | ContentContextBuilder |
| `IMPLEMENTS_CY` | content_context_builder.py | ContentContextBuilder, pipeline_nodes._generate_single_module_summary |
| `CALLERS_CY` | content_context_builder.py | ContentContextBuilder, pipeline_nodes._generate_single_module_summary |
| `call_chain_cypher(depth)` | content_context_builder.py | ContentContextBuilder |
| `FUNCTION_CALLS_CY` (新增) | — | CallChainBuilder, WikiPageAgent |

### 3.2 改动方式

- `cypher_queries.py` 中定义所有常量（不带下划线前缀，作为公有 API）
- `content_context_builder.py` 改为 `from wiki.cypher_queries import METHODS_CY, ...`
- `pipeline_nodes.py` 改为 `from wiki.cypher_queries import IMPLEMENTS_CY, ...`
- 原文件中的 `_METHODS_CY` 等删除，避免重复定义

## 4. P2: Agent Tool-Calling 基础框架

### 4.1 新增文件: `wiki/page_agent.py`

**职责**: 对有 CONTEXT_GAP 的 Wiki 页面进行多轮 Tool-Calling 补充。

### 4.2 触发条件 (智能路由)

在 `_compose_single_leaf_domain` 内部：

```
TopicPageComposer.compose() → 生成页面
    ↓
检测 CONTEXT_GAP 标记数量
    ↓
IF gap_count > 0 AND domain_complexity >= MEDIUM:
    WikiPageAgent.enrich(page_content, context) → 多轮补充
ELSE:
    直接使用生成结果
```

不修改 `pipeline_graph.py` 节点结构。

### 4.3 WikiPageAgent 设计

使用 **原生 Tool-Calling API**。当前 `LLMProvider` 基于 OpenAI-compatible API，`complete()` 的 `**kwargs` 已透传到 API body。只需在 `LLMProvider` 新增 `complete_with_tools()` 方法处理 `tool_calls` 响应格式，在 `LLMPort` Protocol 和 `LLMPortBridge` 中新增对应方法。

```python
class WikiPageAgent:
    MAX_ROUNDS = 5
    TOKEN_BUDGET_RATIO = 0.6  # 模型容量的 60%

    tools: list[AgentTool]  # 6 个 Tool 定义
```

### 4.4 6 个 Tool 定义

| Tool | 功能 | 返回大小限制 |
|------|------|-------------|
| `query_module_detail(name)` | 模块详情 (methods, annotations, summary) | 2000 chars |
| `query_callers(name)` | 谁调用了此模块 | 1500 chars |
| `query_callees(name)` | 此模块调用了谁 | 1500 chars |
| `query_implementations(interface)` | 接口的实现类列表 | 1000 chars |
| `query_call_chain(entry_method)` | 方法级调用链 (复用 P0) | 2000 chars |
| `read_source_snippet(name, max_lines)` | 读取源码片段 | 600 chars |

### 4.5 Working Memory 模式 (上下文质量保障)

**核心**: 不将原始 Tool 结果堆积在消息历史中，而是维护结构化工作记忆。

```python
@dataclass
class WorkingMemory:
    discovered_call_chains: list[str]
    discovered_implementations: list[str]
    discovered_callers: list[str]
    code_snippets: list[str]          # 每个 ≤ 400 字符
    resolved_gaps: list[str]

    MAX_TOTAL_CHARS = 6000  # 约 2000 tokens，超过时优先保留最新发现

    def incorporate(self, tool_results: list[ToolResult]) -> None:
        """规则化提取 Tool 结果中的结构化信息，丢弃原始文本。
        超过 MAX_TOTAL_CHARS 时移除最早的条目。"""

    def to_prompt_section(self) -> str:
        """格式化为 prompt 段落，总量约 2000-3000 tokens。"""
```

**每轮 prompt 结构** (大小恒定):
```
[system_prompt]
[user: 原始页面内容 + 工作记忆(结构化) + 待解决 CONTEXT_GAP 列表]
```

优势:
- 上下文不会线性膨胀（与粗暴截断方案的本质区别）
- 通过规则化提取（非 LLM）保留关键信息，无额外成本
- 每轮 prompt 大小基本恒定

### 4.6 Fallback 机制

- `MAX_ROUNDS = 5` 后强制生成
- 单个 Tool 超时 10s → 跳过该 Tool，继续下一轮
- 所有 Tool 失败 → 返回原始页面内容（不 enrich）

## 5. 实施顺序

```
P1 (cypher_queries.py 解耦)
 → P0 (call_chain_builder.py 构建器 + 集成到 prompt)
   → P2 (page_agent.py Agent 框架 + 集成到 compose 流程)
```

注意: P1 先于 P0，因为 P0 的新 Cypher 查询需要放入 `cypher_queries.py`。

## 6. 测试计划

- P1: 现有 46 个测试全部通过（重构不改变行为）
- P0: 新增 `test_call_chain_builder.py` — 测试 BFS 逻辑、环路处理、深度限制、prompt 格式化
- P2: 新增 `test_page_agent.py` — 测试 Working Memory 提炼、多轮循环、Token Budget 控制、Fallback 机制
