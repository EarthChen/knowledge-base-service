# Design Spec: Phase 7 — P0 关键修复 + P1 架构整合

> **Status**: Draft  
> **Created**: 2026-05-01  
> **Goal**: 修复 4 个 P0 关键问题，统一 LLM 抽象层为 2 层架构，收敛 3 套搜索系统为 IterativeRAGEngine 单内核，清理次要技术债务。

---

## 1. 背景

Phase 6 完成了迭代式 RAG 引擎和动态模型策略的开发。系统审计（`SYSTEM_REVIEW_20260501_182703`）识别出：
- 4 个 P0 必须修复项（占位实现、硬编码、文档不一致）
- 5 套重叠的 LLM 抽象层
- 3 套并行的深度搜索系统
- 若干次要技术债务

本设计覆盖全部 P0 + P1 工作。

---

## 2. P0 关键修复

### 2.1 `unified_knowledge_query` 接入 IterativeRAGEngine

**问题：** `wiki/mcp_tools.py` L444-472 的 `handle_unified_knowledge_query` 返回模板文本，未接入 RAG 引擎。

**方案：**
- `WikiMCPHandler.__init__` 新增 `rag_engine: IterativeRAGEngine` 必选参数
- `handle_unified_knowledge_query` 逻辑：直接调用 `rag_engine.arun(question, scope, max_rounds)` → 从 `RAGState.current_draft` 取答案，`accumulated_context` 生成引用列表
- `api/mcp_server.py` 装配处注入 engine 实例

**涉及文件：**
- `wiki/mcp_tools.py` — 修改 handler
- `api/mcp_server.py` — 注入 engine

### 2.2 ~~`generate_wiki` 注册到 MCP~~ — 已移除

> `generate_wiki` 不通过 MCP 暴露，由 webhook + 定时任务 + 手动触发。现有 handler 保留为内部预留，不注册到 manifest。工具总数保持 22（12 核心 + 10 Wiki）。

### 2.3 `GatewayLLMProviderAdapter.max_context_tokens` 动态化

**问题：** `llm/base_provider.py` L67-69 硬编码 `return 128000`。

**方案：**
- `GatewayLLMProviderAdapter.__init__` 新增 `max_context_tokens: int | None = None` 参数
- `max_context_tokens` property 优先返回传入值，其次尝试从 `self._provider._config.max_context_tokens` 读取，最后 fallback `128000`

```python
@property
def max_context_tokens(self) -> int:
    if self._max_context_tokens is not None:
        return self._max_context_tokens
    config = getattr(self._provider, "_config", None)
    if config and hasattr(config, "max_context_tokens"):
        return config.max_context_tokens
    return 128_000
```

**涉及文件：**
- `llm/base_provider.py` — 修改 adapter

### 2.4 文档工具数量统一

**问题：** 4 个文档文件仍引用 "20 个工具"。

**方案：** 批量替换为 "22 个工具：12 核心 + 10 Wiki"。

| 文件 | 行号 | 修改 |
|------|------|------|
| `docs/ONBOARDING.md` | L98 | 20→22, 8→10 |
| `docs/README-DOCS.md` | L12 | 20→22, 8→10 |
| `docs/wiki-generation-architecture.md` | L9, L186 | 20→22, 8→10 |
| `docs/CODEMAPS/INDEX.md` | L13 | 20→22 |

### 2.5 CODEMAPS 断裂链接

**问题：** `docs/CODEMAPS/INDEX.md` L35 引用不存在的 spec 文件。

**方案：** 替换为 `../wiki-generation-architecture.md`。

---

## 3. P1-A：LLM 抽象层统一

### 3.1 目标架构

从 5 套抽象收敛为 2 层：

```
层1: BaseLLMProvider (基础设施层)
  ├─ 方法: complete, complete_stream, complete_json, close
  ├─ 实现: OpenAIProvider, AzureOpenAIProvider, CustomOpenAIProvider
  └─ 适配: GatewayLLMProviderAdapter (包装 LLMProvider HTTP 客户端)

层2: LLMPort (统一领域端口) ← wiki/llm_port.py
  ├─ 方法: generate(prompt, system, *, model, max_tokens, reasoning_effort) → str
  ├─        complete(messages, **kwargs) → str
  └─        complete_stream(messages, **kwargs) → AsyncIterator[str]  [可选]
  └─ 适配: LLMPortBridge (已满足，不改动)
```

### 3.2 新建 `wiki/llm_port.py`

```python
from __future__ import annotations
from typing import Any, AsyncIterator, Protocol, runtime_checkable

@runtime_checkable
class LLMPort(Protocol):
    """统一的 LLM 领域端口。
    
    合并原 wiki.context.LLMPort (generate) 和 wiki.ask.LLMPort (complete)。
    所有 wiki/rag/ask/research 服务统一使用此协议。
    """

    async def generate(
        self,
        prompt: str,
        system: str = "",
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        reasoning_effort: str | None = None,
    ) -> str: ...

    async def complete(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> str: ...

    async def complete_stream(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> AsyncIterator[str]: ...
```

### 3.3 迁移计划

| 步骤 | 文件 | 改动 |
|------|------|------|
| 1 | `wiki/llm_port.py` | 新建统一 LLMPort |
| 2 | `wiki/context.py` | 删除内联 LLMPort，改为 `from wiki.llm_port import LLMPort` |
| 3 | `wiki/ask.py` | 删除内联 LLMPort，改为 `from wiki.llm_port import LLMPort`；`complete_stream` 不再需要 `getattr` |
| 4 | `wiki/model_strategy.py` | import 路径从 `wiki.context` 改为 `wiki.llm_port` |
| 5 | `wiki/composer.py` | import 路径修改 |
| 6 | `wiki/topic_page_composer.py` | import 路径修改 |
| 7 | `wiki/business_domain_planner.py` | import 路径修改 |
| 8 | `wiki/overview_page_composer.py` | import 路径修改 |
| 9 | `wiki/healing.py` | import 路径修改 |
| 10 | `wiki/service.py` | import 路径修改 |
| 11 | `wiki/bootstrap.py` | import 路径修改 |
| 12 | `wiki/rag/engine.py` | import 路径修改（_LLM 协议对齐） |
| 13 | `wiki/deep_research.py` | import 路径修改 |
| 14 | `llm/base_provider.py` | LLMPortBridge 注释更新 |
| 15 | 测试文件 | import 路径批量更新 |

### 3.4 LLMPortBridge 验证

`LLMPortBridge` 已同时实现：
- `generate(prompt, system, *, model, max_tokens, extra_params)` → 满足 `LLMPort.generate`
- `complete(messages, **kwargs)` → 满足 `LLMPort.complete`
- `complete_stream(messages, **kwargs)` → 满足 `LLMPort.complete_stream`

无需修改 `LLMPortBridge` 本体，只需更新注释说明其适配目标。

### 3.5 不变的部分

- `BaseLLMProvider` 协议和所有实现类 — 不动
- `LLMProvider`（`llm/provider.py`）HTTP 客户端 — 不动（indexer/query 路径继续直接使用）
- `GatewayTaskClient` — 独立命名空间，非 Chat 抽象
- `LLMProviderFactory` — 不动

---

## 4. P1-B：搜索系统直接统一

### 4.1 目标架构

```
API 端点（不变）    编排层（保留差异化）       统一内核           检索层
───────────      ─────────────────      ────────          ───────
/deep-search  →  DeepSearchEngine     →  IterativeRAG  →  CompositeRetriever
/ask/stream   →  WikiAskService       →  IterativeRAG  →    ├─ WikiRetriever
/wiki/research → DeepResearchService  →  IterativeRAG  →    ├─ CodeRetriever
                                                             └─ HybridGraphRetriever (新)
```

### 4.2 新建 `wiki/rag/hybrid_graph_retriever.py`

封装 DeepSearchEngine 的混合搜索 + 图查询能力为 `Retriever` 协议：

```python
class HybridGraphRetriever:
    """将 HybridQueryService + GraphQueryService 封装为 Retriever 协议。"""
    
    def __init__(
        self,
        hybrid_service: HybridQueryService,
        graph_service: GraphQueryService,
    ) -> None:
        self._hybrid = hybrid_service
        self._graph = graph_service

    async def retrieve(
        self, queries: list[str], scope: RetrievalScope,
    ) -> list[Chunk]:
        chunks: list[Chunk] = []
        for query in queries:
            # 混合搜索
            hybrid_results = await self._hybrid.search_with_context(
                query, business_id=scope.business_id
            )
            for r in hybrid_results:
                chunks.append(Chunk(
                    content=r.content,
                    source=Source(title=r.title, path=r.path),
                    score=r.score,
                ))
            # 图查询（补充结构化关系）
            graph_results = await self._graph.query(
                query, business_id=scope.business_id
            )
            for r in graph_results:
                chunks.append(Chunk(
                    content=str(r),
                    source=Source(title="graph", path=""),
                    score=0.5,
                ))
        return chunks
```

### 4.3 改写 `DeepSearchEngine`

- 删除 `_plan`、`_execute_single`、`_synthesize` 内部方法
- `__init__` 接收 `engine: IterativeRAGEngine`（必选参数）
- `search` 方法：

```python
async def search(self, question, business_id, ...):
    scope = RetrievalScope(business_id=business_id)
    state = await self.engine.arun(question, scope, max_rounds=5)
    return {
        "analysis": state["current_draft"],
        "search_trace": self._build_trace(state["sse_events"]),
        # business_flows 和 code_locations 可从 current_draft 后处理提取
    }
```

- `search_stream` 方法：将 RAG `sse_events` 映射为 DeepSearch 的事件格式
- 删除 `use_iterative_rag` flag 和旧路径

### 4.4 改写 `WikiAskService`

- `__init__` 接收 `engine: IterativeRAGEngine`（必选参数）
- `ask_stream` 方法：直接调用 `IterativeRAGEngine.arun`
- 输出格式保持不变：`rag-progress` → `wiki-answer` → `wiki-sources` → `wiki-answer-complete`
- 删除 `use_iterative_rag` flag、`rag_engine` 可选参数

### 4.5 改写 `DeepResearchService`

- `__init__` 接收 `engine: IterativeRAGEngine`（必选参数）
- `research` 方法：每个子问题调用 `engine.arun(sub_q, scope, max_rounds=5)`
- 保留子问题分解和最终合成逻辑
- 删除 `use_iterative_rag` flag、旧路径

### 4.6 Bootstrap 装配

```python
# wiki/bootstrap.py
wiki_retriever = WikiRetriever(wiki_search_service)
code_retriever = CodeRetriever(code_search_service)
hybrid_graph_retriever = HybridGraphRetriever(hybrid_service, graph_service)
composite = CompositeRetriever([wiki_retriever, code_retriever, hybrid_graph_retriever])

rag_engine = IterativeRAGEngine(
    retriever=composite,
    llm=llm_port,
    max_rounds=7,
)

ask_service = WikiAskService(..., engine=rag_engine)
deep_search = DeepSearchEngine(..., engine=rag_engine)
deep_research = DeepResearchService(..., engine=rag_engine)
```

### 4.7 删除的配置

- `config.py` 中的 `iterative_rag_enabled: bool = False` — 删除
- `DeepSearchEngine.__init__` 中的 `rag_engine: Any | None = None`, `use_iterative_rag: bool = False` — 改为必选
- `DeepResearchService.__init__` 中的同上
- `WikiAskService.__init__` 中的同上

---

## 5. P1-B2：IterativeRAGEngine 3-LLM 自适应升级

### 5.1 背景

当前 `IterativeRAGEngine` 中 `plan_llm` 和 `evaluate_llm` 参数存在但未接入任何图节点。需要实现完整的 3-LLM 架构，并通过自适应升级机制控制成本。

### 5.2 自适应升级流程

```
Round 1: 最低成本探测
  initial_search(原始问题) → generate_draft(fast 模型)
  if confidence >= 0.85 → finalize（1 轮结束，零额外开销）

Round 2+: 信号驱动升级
  plan(plan_llm: 分解 gaps + 问题为子查询) → dynamic_retrieve → generate_draft
  plan 节点仅在 Round 2+ 且 confidence < 0.85 时自动启用

Round 3+: 独立评估兜底
  if confidence 仍 < 0.7 且已迭代 >= 2 轮 →
  evaluate(evaluate_llm: 独立评估答案质量，输出改进方向) → 反馈为新的 next_queries
```

### 5.3 LangGraph 图结构变更

**新增节点：**
- `plan`: 接收 `gaps` + 原始问题，用 `plan_llm` 生成精准子查询
- `evaluate`: 接收 `current_draft` + `question` + `accumulated_context`，用 `evaluate_llm` 独立评估

**新增路由：**
```python
def route_after_draft(state):
    if confidence >= 0.85 or round >= max_rounds or not next_queries:
        return "finalize"
    if round >= 2 and confidence < 0.7:
        return "evaluate"  # 先评估
    if round >= 2:
        return "plan"  # 先规划再检索
    return "dynamic_retrieve"  # Round 1 后直接追加检索

def route_after_evaluate(state):
    return "plan"  # evaluate 输出的改进方向 → plan 分解 → retrieve

def route_after_plan(state):
    return "dynamic_retrieve"
```

### 5.4 模型选择

通过 `ModelStrategy`（可选）为 3 个节点配置不同模型：

| 节点 | task_type 键 | 默认行为 |
|------|-------------|---------|
| plan | `rag_plan` | 未配置时使用默认 LLM |
| generate | `rag_generate` | 未配置时使用默认 LLM |
| evaluate | `rag_evaluate` | 未配置时使用默认 LLM |

用户通过 Dashboard `llm.strategy.rag_plan` / `rag_evaluate` 配置不同模型（可选）。

### 5.5 构造函数简化

```python
class IterativeRAGEngine:
    def __init__(
        self,
        *,
        retriever: Retriever,
        llm: _LLM,  # 默认 LLM（用于所有节点）
        model_strategy: ModelStrategy | None = None,  # 可选：按 task_type 路由到不同模型
    ):
```

不再暴露 `plan_llm` / `generate_llm` / `evaluate_llm` 3 个独立参数。引擎内部通过 `model_strategy.get_llm_port(task_type)` 获取各节点的 LLM（未配置时 fallback 到 `llm`）。

### 5.6 SSE 事件扩展

新增事件类型：
- `planning`: `{"type": "planning", "round": N, "sub_queries": [...]}`
- `evaluating`: `{"type": "evaluating", "round": N, "score": 0.65, "suggestions": [...]}`

### 5.7 涉及文件

- `wiki/rag/engine.py` — 增加 plan/evaluate 节点，修改路由逻辑，简化构造函数
- `wiki/rag/events.py` — 增加 planning/evaluating 事件类型
- `tests/wiki/rag/test_engine.py` — 更新测试覆盖 3-LLM 路径

---

## 6. P1-C：次要修复

### 5.1 Business 路由去重

确认 `business_routes.py` 和 `business_sync_routes.py` 中 `GET /api/v1/businesses` 的重复端点，删除 sync 中的冗余定义。

### 5.2 compose_concurrency 统一配置源

`pipeline_nodes.py` 中 `os.getenv("WIKI__COMPOSE_CONCURRENCY")` 改为从 `AppWikiFlags.compose_concurrency` 读取。

---

## 6. 测试策略

| 层级 | 覆盖范围 |
|------|---------|
| 单元测试 | 新 `LLMPort` Protocol 满足性验证；`HybridGraphRetriever` 检索测试 |
| 集成测试 | 3 个搜索服务通过 IterativeRAGEngine 的端到端流程 |
| 回归测试 | 所有现有 wiki/rag/ask/search 测试必须通过 |

---

## 7. 风险与缓解

| 风险 | 缓解措施 |
|------|---------|
| LLM import 路径批量修改遗漏 | grep 全局搜索 `from wiki.context import LLMPort` 和 `from wiki.ask import LLMPort` |
| DeepSearch 结构化输出（business_flows）丢失 | 保留后处理节点，从 RAG draft 中 LLM 提取 |
| 现有测试 mock 路径变更 | 测试文件同步更新 import |
| SSE 事件格式不兼容 | 添加事件映射层，保持前端不变 |

---

*待审批后使用 writing-plans 创建实施计划。*
