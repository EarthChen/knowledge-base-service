# Phase 6 设计提案 — 统一迭代 RAG 引擎 + 动态模型策略 + Wiki 增强

> **状态**: AwaitingApproval
> **创建**: 2026-05-01 17:04
> **范围**: T7/T8/P3/C4/A1/A5 六项剩余工作的整合设计
> **依赖**: Phase 0–5 已全部完成

---

## 1. 背景与目标

### 1.1 问题陈述

KB Service 在 Phase 0–5 完成后，内容生成质量和基础设施已追平竞品。剩余 6 项工作集中在三个维度：

| 维度 | 项目 | 核心问题 |
|------|------|---------|
| **搜索智能** | P3 页面级 RAG Chat, A1 上下文感知查询, A5 图谱-Wiki 关联 | 问答系统缺乏迭代深入能力，三套搜索系统（DeepSearch/WikiAsk/DeepResearch）各自为政 |
| **模型效率** | T7 LLM 模型策略分离, T8 复杂度评估器深化 | 所有节点共享同一模型，无法按任务类型和复杂度路由到最优模型 |
| **结构智能** | C4 LLM 语义分组 | code_structure 视图按目录分桶，缺乏跨目录语义关联 |

### 1.2 设计目标

1. **统一三套搜索系统**为一个可复用的 `IterativeRAGEngine`，支持自反馈多轮迭代
2. **Dashboard 可配置的模型策略**，支持多 Provider 池 + 按任务类型路由，热重载无需重启
3. **复杂度评估器**驱动模型选择和推理深度
4. **code_structure 视图**增加 LLM 语义分组层
5. **MCP 工具增强**：上下文感知查询 + 统一知识查询

### 1.3 不在范围内

- Wiki 生成管道的重写（仅增强模型路由和复杂度联动）
- 前端组件库重构
- 新增 LLM Provider 类型（复用现有 OpenAI 兼容接口）

---

## 2. 核心设计：统一迭代 RAG 引擎

### 2.1 动机

当前系统有三套独立的 LLM 增强搜索系统：

| 系统 | 文件 | 模式 | 问题 |
|------|------|------|------|
| `DeepSearchEngine` | `query/deep_search.py` | LLM 子查询规划 → hybrid/graph → LLM 判断 → 迭代 | 仅面向代码 KB |
| `WikiAskService` | `wiki/ask.py` | 单次检索 → LLM 回答 | 无迭代能力 |
| `DeepResearchService` | `wiki/deep_research.py` | LLM 子问题 → 多次 WikiAsk → 拼接 | 综合段非 LLM，子问题与检索分离 |

三者核心循环相同：`计划 → 检索 → 生成 → 评估 → (迭代)`。差异仅在检索源和输出格式。

### 2.2 架构概览

```
                    ┌─────────────────────────────────┐
                    │      IterativeRAGEngine          │
                    │     (LangGraph StateGraph)       │
                    │                                  │
                    │  plan → retrieve → generate →    │
                    │  evaluate → [iterate/finalize]   │
                    └──────────┬──────────────────────┘
                               │
                    ┌──────────┴──────────┐
                    │   Retriever (协议)   │
                    └──────────┬──────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
     ┌────────┴──────┐ ┌──────┴────────┐ ┌─────┴──────────┐
     │ WikiRetriever │ │ CodeRetriever │ │ CompositeRetr. │
     │ (WikiSearch)  │ │ (HybridQuery) │ │ (Wiki + Code)  │
     └───────────────┘ └───────────────┘ └────────────────┘
```

### 2.3 LangGraph 状态定义

```python
from dataclasses import dataclass, field
from typing import TypedDict

class RAGState(TypedDict):
    question: str
    scope: RetrievalScope
    round: int
    max_rounds: int
    accumulated_context: list[Chunk]
    current_draft: str
    gaps: list[str]
    next_queries: list[str]
    confidence: float
    is_complete: bool
    sources: list[Source]
    sse_events: list[SSEEvent]
```

### 2.4 工作流节点

```
┌─────────────────┐
│ initial_search  │──── 用原始问题检索 → top-N 结果
└──────┬──────────┘
       ▼
┌─────────────────┐
│ generate_draft  │──── LLM 生成草稿 + 结构化反思
└──────┬──────────┘     输出: {answer, gaps, next_queries, confidence, is_complete}
       ▼
┌─────────────────┐
│ check_complete  │──── 终止条件判断
└──────┬──────────┘
       │ NO                          YES
       ▼                              ▼
┌──────────────────┐           ┌──────────────┐
│ dynamic_retrieve │           │ final_answer │
│ 用 next_queries  │           └──────────────┘
│ 检索新内容       │
│ 合并到 context   │
└──────┬───────────┘
       │
       ▼ (回到 generate_draft，带累积 context)
```

### 2.5 终止条件（动态轮次控制）

| 条件 | 阈值 | 说明 |
|------|------|------|
| 置信度达标 | `confidence ≥ 0.85` | LLM 自评足够 |
| Gap 收敛 | 当前轮 gaps ≤ 上轮 50% | 信息在收敛 |
| 检索饱和 | 新结果与已有 context 重复 ≥ 80% | 没有新信息了 |
| 硬上限 | `max_rounds = 7`（可配置） | 安全阀 |
| 用户终止 | 前端"停止"按钮 | 主动中断 |

### 2.6 自反馈迭代机制

每轮 `generate_draft` 节点输出结构化反思：

```json
{
  "answer": "当前基于已有信息的最佳回答...",
  "gaps": ["token 刷新机制", "中间件拦截逻辑"],
  "next_queries": ["refresh token flow", "auth middleware interceptor"],
  "confidence": 0.6,
  "is_complete": false
}
```

下一轮 `dynamic_retrieve` 使用 `next_queries` 定向检索缺失信息，新结果追加到 `accumulated_context`。当 context 超出 token 预算时，用嵌入相似度淘汰最不相关的旧 context。

### 2.6.1 Token 预算管理

引擎需要感知当前模型的 context window 大小，动态控制 accumulated_context 的总量：

- **获取方式**：从 `ModelStrategy` 解析当前 `rag_generate` 模型的 `max_context_tokens` 配置（Provider 池中每个模型可声明 context window 大小，默认 128K）
- **预算分配**：context window 的 70% 分配给 accumulated_context，20% 给 system prompt + question，10% 给生成输出
- **淘汰策略**：当 accumulated_context 超出预算时，计算每个 Chunk 与原始 question 的嵌入相似度，淘汰得分最低的 Chunk 直到预算内
- **跨模型切换**：如果 `rag_plan` 和 `rag_generate` 使用不同模型（不同 context window），以 `rag_generate` 的窗口为准

### 2.6.2 错误处理与回退

| 故障场景 | 处理策略 |
|---------|---------|
| LLM 调用超时 | 重试 1 次；仍失败则用当前 accumulated_context 生成 best-effort 回答 |
| LLM 返回格式错误 | 尝试解析非结构化回答作为 final_answer，标记 confidence=0.5 |
| Retriever 检索失败 | 跳过当前轮检索，用已有 context 继续生成 |
| 迭代死循环（连续 2 轮 gaps 不变） | 强制终止，输出当前最佳草稿 |

### 2.7 SSE 实时事件协议

统一的 SSE 事件类型，三套搜索系统共享：

| SSE type | 内容 | 前端展示 |
|----------|------|---------|
| `thinking_start` | `{round, max_rounds}` | "正在思考... (第 N 轮)" |
| `searching` | `{queries, sources_count}` | "正在检索: ..." |
| `sources_found` | `{round, new_sources: [{title, path, relevance}]}` | 展示找到的来源 |
| `draft` | `{round, content, confidence}` | 实时草稿 + 置信度进度条 |
| `gaps` | `{round, gaps, next_queries}` | "发现缺失: ..." |
| `refining` | `{round, reason}` | "正在深入: ..." |
| `token` | `{content}` | 流式输出最终回答 |
| `sources` | `{sources}` | 引用来源列表 |
| `done` | `{final_answer, total_rounds, sources, confidence}` | 完成 |
| `error` | `{message}` | 错误提示 |

### 2.8 Retriever 协议

```python
from typing import Protocol

@dataclass
class Chunk:
    content: str
    source: str
    title: str
    relevance: float
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass
class RetrievalScope:
    scope_type: Literal["page", "business", "repository", "global"]
    page_path: str | None = None
    business_id: str | None = None
    repository: str | None = None

class Retriever(Protocol):
    async def retrieve(
        self,
        queries: list[str],
        scope: RetrievalScope,
        *,
        limit: int = 10,
        exclude_ids: set[str] | None = None,
    ) -> list[Chunk]: ...
```

### 2.9 三个 Retriever 实现

| 实现 | 检索源 | 说明 |
|------|--------|------|
| `WikiRetriever` | `WikiSearchService` | 对 Wiki 页面做 hybrid/graph/semantic 检索 |
| `CodeRetriever` | `HybridQueryService` | 对代码 KB 做混合检索 + 图上下文 |
| `CompositeRetriever` | 两者组合 | 同时搜 Wiki + Code，按 relevance 合并排序 |

### 2.10 三套系统的迁移

| 当前系统 | 迁移为 | Retriever | 额外适配 |
|---------|--------|-----------|---------|
| `WikiAskService` | `IterativeRAGEngine` + `WikiRetriever` | Wiki | SSE v2 兼容 |
| `DeepSearchEngine` | `IterativeRAGEngine` + `CodeRetriever` | Code | 保留 `search_stream` 接口 |
| `DeepResearchService` | `IterativeRAGEngine` + `WikiRetriever` | Wiki | 综合步骤改为 LLM 驱动 |

### 2.11 Dashboard 迭代过程可视化

前端 AskPanel 升级，展示思考过程：

```
┌─────────────────────────────────────────┐
│ 🔍 思考过程                    [停止] │
│                                         │
│ ▸ 第 1 轮 — 初始检索                    │
│   检索: "认证流程" → 找到 5 个相关页面    │
│   置信度: ████░░░░░░ 40%                │
│   缺失: token 刷新机制, 中间件拦截       │
│                                         │
│ ▸ 第 2 轮 — 补充 token 刷新             │
│   检索: "refresh token" → 找到 3 个页面  │
│   置信度: ███████░░░ 70%                │
│   缺失: 中间件拦截逻辑                   │
│                                         │
│ ▸ 第 3 轮 — 补充中间件                  │
│   检索: "auth middleware" → 找到 2 个页面│
│   置信度: █████████░ 92% ✅              │
│                                         │
│ ─────────────────────────────────────── │
│ 📝 最终回答                             │
│ ...                                     │
│                                         │
│ 📎 引用来源 (10 个 sections, 跨 5 页)    │
└─────────────────────────────────────────┘
```

---

## 3. 动态模型策略配置

### 3.1 双层架构

```
第 1 层: Provider 池
  ├── provider "openai"
  │     base_url: https://api.openai.com/v1
  │     api_key: sk-xxx (加密存储)
  │     available_models: [gpt-4o, gpt-4o-mini, gpt-4.1, o3-mini]
  │     default_model: gpt-4o
  ├── provider "anthropic"
  │     base_url: https://api.anthropic.com/v1
  │     api_key: sk-ant-xxx
  │     available_models: [claude-sonnet-4-20250514, claude-opus-4-20250514, claude-3.5-haiku]
  │     default_model: claude-sonnet-4-20250514
  └── provider "local"
        base_url: http://localhost:11434/v1
        api_key: (空)
        available_models: [llama3, qwen2.5]
        default_model: llama3

第 2 层: 任务策略路由
  ├── classification  → openai / gpt-4o-mini
  ├── generation      → anthropic / claude-sonnet-4-20250514
  ├── reasoning       → anthropic / claude-sonnet-4-20250514
  ├── evaluation      → openai / gpt-4o-mini
  ├── heal            → anthropic / claude-sonnet-4-20250514
  ├── diagram         → openai / gpt-4o-mini
  ├── rag_plan        → openai / gpt-4o-mini
  └── rag_generate    → anthropic / claude-sonnet-4-20250514
```

同一 provider 下可为不同任务分配不同模型（如 openai/gpt-4o-mini 用于分类，openai/gpt-4o 用于生成）。

### 3.2 数据模型

SettingsStore 存储格式：

```python
# Provider 池（JSON，category: llm）
"llm.providers" = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "api_key": "sk-xxx",  # 纳入 SENSITIVE_KEYS 加密存储
        "default_model": "gpt-4o",
        "available_models": [
            {"name": "gpt-4o", "max_context_tokens": 128000},
            {"name": "gpt-4o-mini", "max_context_tokens": 128000},
            {"name": "o3-mini", "max_context_tokens": 200000}
        ]
    },
    "anthropic": {
        "base_url": "https://gateway.internal/v1",
        "api_key": "sk-ant-xxx",
        "default_model": "claude-sonnet-4-20250514",
        "available_models": [
            {"name": "claude-sonnet-4-20250514", "max_context_tokens": 200000},
            {"name": "claude-opus-4-20250514", "max_context_tokens": 200000}
        ]
    }
}

# 策略路由（JSON，category: llm）
"llm.strategy.classification" = {"provider": "openai", "model": "gpt-4o-mini"}
"llm.strategy.generation" = {"provider": "anthropic", "model": "claude-sonnet-4-20250514"}
# ... 其他任务类型
```

### 3.3 热重载与配置优先级

所有 `llm.strategy.*` 和 `llm.providers` 加入 `HOT_RELOAD_KEYS`。后端通过 `SettingsStore.get()` 热读，修改即时生效。

**配置优先级（高 → 低）**：
1. Dashboard (DB SettingsStore) — 管理员通过 UI 配置
2. 环境变量 (`LLM__*`) — 部署时注入
3. config.py 默认值 — 代码内置

**安全说明**：Provider 池中的 `api_key` 字段纳入 `SENSITIVE_KEYS` 列表，在 SettingsStore 中加密存储，Dashboard 展示时脱敏（`sk-xxx•••`）。

### 3.3.1 Provider 池与现有 LLMProviderFactory 的关系

Provider 池是对现有 `LLMProviderFactory` 的**增强而非替代**：

- 启动时，`LLMProviderFactory` 按 config.py 注册基础 provider（gateway/openai/azure/custom）
- Dashboard Provider 池的配置作为**动态覆盖层**：当 `llm.providers` 在 SettingsStore 中存在时，`ModelStrategy` 优先使用 DB 配置创建 provider；不存在时回退到 factory 的静态注册
- 动态添加的 Provider 通过 `LLMProviderFactory.register_dynamic(name, config)` 注册，复用 `LLMProvider` 类（OpenAI 兼容接口）

### 3.4 后端 `ModelStrategy` 类

```python
class ModelStrategy:
    def __init__(
        self,
        settings_store: SettingsStore,
        provider_factory: LLMProviderFactory,
        default_provider: str,
        default_model: str,
    ):
        self._store = settings_store
        self._factory = provider_factory
        self._default_provider = default_provider
        self._default_model = default_model

    async def resolve(self, task_type: str) -> tuple[str, str]:
        """返回 (provider_name, model_name)"""
        raw = await self._store.get(f"llm.strategy.{task_type}")
        if raw:
            cfg = json.loads(raw)
            return cfg["provider"], cfg["model"]
        return self._default_provider, self._default_model

    async def get_llm_port(self, task_type: str) -> LLMPort:
        provider_name, model = await self.resolve(task_type)
        provider = self._factory.get_provider(provider_name)
        # LLMPortBridge 需扩展：增加 default_model 参数
        # generate() 调用时若未传 model，使用 default_model
        return LLMPortBridge(provider, default_model=model)
```

### 3.5 任务类型清单

| 任务类型 Key | 说明 | 建议级别 | 使用位置 |
|-------------|------|---------|---------|
| `classification` | 域分类、实体角色分类 | 快 | `business_domain_planner`, `pipeline_nodes.classify` |
| `generation` | Wiki 页面内容生成 | 慢 | `topic_page_composer`, `composer` |
| `reasoning` | CoT 多步推理 | 慢 | `reasoning.MultiStepReasoner` |
| `evaluation` | 质量评判、完整性判断 | 快 | `quality_evaluator`, `IterativeRAGEngine.evaluate` |
| `heal` | 定向修复 | 慢 | `targeted_healer` |
| `diagram` | 图表生成 | 快 | `semantic_diagram_gen` |
| `rag_plan` | RAG 查询规划 | 快 | `IterativeRAGEngine.plan` |
| `rag_generate` | RAG 回答生成 | 慢 | `IterativeRAGEngine.generate` |
| `overview` | 系统概述生成 | 慢 | `system_overview_composer` |
| `context` | 上下文构建（术语表/叙述） | 快 | `context.WikiContextBuilder` |

### 3.6 Dashboard UI

#### Provider 池管理

```
┌─ Provider 池 ─────────────────────────────────────┐
│                                                    │
│  ┌ openai ──────────────────────────────────┐      │
│  │ Base URL:    [https://api.openai.com/v1 ]│      │
│  │ API Key:     [sk-xxx•••••••         🔒  ]│      │
│  │ 默认模型:    [gpt-4o                ▼   ]│      │
│  │                                          │      │
│  │ 可用模型:                                │      │
│  │  [gpt-4o        ] [×]                    │      │
│  │  [gpt-4o-mini   ] [×]                    │      │
│  │  [gpt-4.1       ] [×]                    │      │
│  │  [o3-mini       ] [×]                    │      │
│  │  [+ 手动添加]  [🔍 自动发现]             │      │
│  │                                          │      │
│  │                   [测试连接] [删除]       │      │
│  └──────────────────────────────────────────┘      │
│                                                    │
│                            [+ 添加新 Provider]     │
└────────────────────────────────────────────────────┘
```

#### 任务策略路由

```
┌─ 任务模型策略 ──────────────────────────────────────┐
│                                                      │
│  ┌─ 轻量任务 ────────────────────────────────┐      │
│  │ 域分类:    [openai    ▼] / [gpt-4o-mini ▼]│      │
│  │ 质量评判:  [openai    ▼] / [gpt-4o-mini ▼]│      │
│  │ 图表生成:  [openai    ▼] / [gpt-4o-mini ▼]│      │
│  │ RAG 规划:  [openai    ▼] / [gpt-4o-mini ▼]│      │
│  │ 上下文:    [openai    ▼] / [gpt-4o-mini ▼]│      │
│  └────────────────────────────────────────────┘      │
│                                                      │
│  ┌─ 深度任务 ────────────────────────────────┐      │
│  │ 内容生成:  [anthropic ▼] / [claude-sonnet▼]│     │
│  │ 多步推理:  [anthropic ▼] / [claude-sonnet▼]│     │
│  │ 定向修复:  [anthropic ▼] / [claude-sonnet▼]│     │
│  │ RAG 生成:  [anthropic ▼] / [claude-sonnet▼]│     │
│  │ 系统概述:  [anthropic ▼] / [claude-sonnet▼]│     │
│  └────────────────────────────────────────────┘      │
│                                                      │
│  ℹ️ 未配置的任务使用默认 Provider 的默认模型         │
│  ⚡ 修改即时生效，无需重启                           │
│                                              [保存]  │
└──────────────────────────────────────────────────────┘
```

- Provider 下拉框列出 Provider 池中所有已注册的 provider
- Model 下拉框**动态联动**：仅显示所选 provider 的 `available_models`
- 自动发现按钮调用 provider 的 `GET /models` 端点获取可用模型

---

## 4. 复杂度评估器深化 (T8)

### 4.1 当前状态

`DomainComplexityScorer` 输出 LOW/MEDIUM/HIGH，仅影响 token budget 放大。

### 4.2 深化设计

复杂度等级驱动四个维度的自动决策：

| 维度 | LOW | MEDIUM | HIGH |
|------|-----|--------|------|
| **推理深度** | NONE（直接生成） | GUIDED（引导式提示） | MULTI_STEP（多步推理） |
| **模型选择** | 快模型 (classification) | 默认模型 (generation) | 慢模型 (reasoning) |
| **页面结构** | 单页概述 | 概述 + 子页 | 多级子页 + 交叉引用 |
| **图表丰富度** | 仅流程图 | 流程图 + 类图 | 流程图 + 类图 + 序列图 + 依赖图 |
| **Token 预算** | 1.0x | 1.0x | 1.5x |

### 4.3 实现

`DomainComplexityScorer.score()` 返回的 `ComplexityMetrics` 新增 `recommended_strategy` 字段：

```python
@dataclass
class CompositionStrategy:
    reasoning_level: ReasoningLevel
    model_task_type: str  # ModelStrategy 的 task_type key
    page_structure: Literal["flat", "overview_with_subs", "deep_hierarchy"]
    diagram_types: list[str]
    token_multiplier: float

@dataclass
class ComplexityMetrics:
    # ... 现有字段
    recommended_strategy: CompositionStrategy
```

Pipeline 节点从 `ComplexityMetrics.recommended_strategy` 获取决策，再通过 `ModelStrategy.get_llm_port(strategy.model_task_type)` 获取对应 LLM。

### 4.4 优先级规则

当 Dashboard 显式配置了某任务的模型策略时，复杂度推荐不会覆盖用户选择。优先级：

1. **Dashboard 显式配置** — 管理员明确指定某任务用特定模型
2. **复杂度自动推荐** — `DomainComplexityScorer` 根据域特征推荐策略
3. **系统默认** — 未配置时使用默认 provider/model

具体实现：`ModelStrategy.resolve(task_type, complexity=None)` 先检查 DB 是否有 `llm.strategy.{task_type}` 的显式配置；如果没有且传入了 `complexity`，则使用 `ComplexityMetrics.recommended_strategy` 的映射。

---

## 5. LLM 语义分组 (C4)

### 5.1 当前状态

- `code_structure` 视图：按 repository 建 `WikiSection`，每个 section 下 flat 列出该仓所有 `WikiPage`
- `WikiStructurePlanner._semantic_group_modules` 已实现 LLM 语义分组，但未用于 `code_structure` 视图

### 5.2 设计

在 `code_structure` 视图的 repo section 下，增加一层 LLM 语义分组的 sub-section：

```
当前:
  WikiSpace
  └── WikiSection("repo-A", code_module)
      ├── WikiPage("auth_service.py")
      ├── WikiPage("user_model.py")
      ├── WikiPage("payment_handler.py")
      └── WikiPage("order_service.py")

增强后:
  WikiSpace
  └── WikiSection("repo-A", code_module)
      ├── WikiSection("认证与用户管理", semantic_group)
      │   ├── WikiPage("auth_service.py")
      │   └── WikiPage("user_model.py")
      └── WikiSection("交易处理", semantic_group)
          ├── WikiPage("payment_handler.py")
          └── WikiPage("order_service.py")
```

### 5.3 实现路径

1. `tree_linker.link_pages_to_tree` 的 `code_structure` 路径中，当单仓页面数 ≥ `semantic_group_threshold`（默认 8）时：
   - 收集该仓所有 WikiPage 的 title + summary
   - 调用 `WikiStructurePlanner._semantic_group_modules`（复用现有逻辑）
   - 创建 semantic_group 类型的 WikiSection
   - WikiPage 挂到对应 semantic_group section 下
2. 页面数 < 阈值时保持 flat 结构

### 5.4 配置

- `WIKI__CODE_STRUCTURE_SEMANTIC_GROUP`: bool（默认 false，逐步启用）
- `WIKI__CODE_STRUCTURE_SEMANTIC_GROUP_THRESHOLD`: int（默认 8）
- 使用 `ModelStrategy.get_llm_port("classification")` 获取快模型

### 5.5 增量更新时的语义分组策略

- **新增页面**：将新页面分配到已有的最匹配语义组（通过嵌入相似度 + 组描述对比），避免每次重新分组所有页面
- **页面删除**：如果语义组只剩 1 个页面，将其合并到最近的组
- **全量重新分组**：仅在 `full` 模式生成时触发，增量更新默认不重新分组

---

## 6. MCP 工具增强

### 6.1 A1: 上下文感知 Wiki 查询

**已被 P3 的 IterativeRAGEngine 覆盖**。MCP `wiki_search` 和 `wiki_qa` 工具增加 `page_context` 参数：

```json
{
  "name": "wiki_search",
  "inputSchema": {
    "properties": {
      "repository": {"type": "string"},
      "query": {"type": "string"},
      "page_context": {
        "type": "string",
        "description": "Current wiki page path for context-aware search. Results related to this page are boosted."
      },
      "mode": {"type": "string"},
      "limit": {"type": "integer"},
      "scope": {"type": "string"}
    }
  }
}
```

后端实现：
- 如果传入 `page_context`（page path），加载该页面的 `WIKI_REFERENCES` 边
- 搜索结果中与当前页面有引用关系的结果加权 boost
- `IterativeRAGEngine` 在 page scope 模式下自动注入

### 6.2 A5: 统一知识查询

新增 MCP 工具 `unified_knowledge_query`：

```json
{
  "name": "unified_knowledge_query",
  "description": "Combined code graph + wiki knowledge query with iterative deep search",
  "inputSchema": {
    "properties": {
      "query": {"type": "string", "description": "Natural language question"},
      "sources": {
        "type": "array",
        "items": {"type": "string", "enum": ["code", "wiki", "graph"]},
        "description": "Knowledge sources to query",
        "default": ["code", "wiki"]
      },
      "repository": {"type": "string"},
      "max_rounds": {"type": "integer", "default": 3}
    },
    "required": ["query"]
  }
}
```

后端实现：
- 使用 `CompositeRetriever` 同时搜索 Code KB 和 Wiki
- 一次 MCP 调用返回两类知识的综合回答
- 比 Agent 手动组合 `rag_query` + `wiki_search` 更高效

---

## 7. 实施计划

**Sprint 依赖关系说明**：Sprint 1（RAG 基础设施）和 Sprint 2（模型策略）可**并行开发**，因为 RAG 引擎的 Retriever 实现和 ModelStrategy 的 Provider 池管理是独立组件。Sprint 3 依赖 Sprint 1+2 的接口定义。

### Sprint 1: 基础设施（预估 3-4 天）【可与 Sprint 2 并行】

| # | 任务 | 涉及文件 | 说明 |
|---|------|---------|------|
| 1.1 | `Retriever` 协议 + `Chunk`/`RetrievalScope` 数据类 | `wiki/rag/protocol.py` (新) | 统一接口定义 |
| 1.2 | `WikiRetriever` 实现 | `wiki/rag/wiki_retriever.py` (新) | 适配 `WikiSearchService` |
| 1.3 | `CodeRetriever` 实现 | `wiki/rag/code_retriever.py` (新) | 适配 `HybridQueryService` |
| 1.4 | `CompositeRetriever` 实现 | `wiki/rag/composite_retriever.py` (新) | 组合两者 |
| 1.5 | `IterativeRAGEngine` LangGraph 图 | `wiki/rag/engine.py` (新) | 核心引擎 |
| 1.6 | SSE 事件协议定义 | `wiki/rag/events.py` (新) | 统一事件类型 |
| 1.7 | 单元测试 | `tests/wiki/rag/` (新) | 引擎 + 各 Retriever |

### Sprint 2: 模型策略（预估 2-3 天）【可与 Sprint 1 并行】

| # | 任务 | 涉及文件 | 说明 |
|---|------|---------|------|
| 2.1 | `ModelStrategy` 类 | `wiki/model_strategy.py` (新) | 热读 SettingsStore |
| 2.2 | Provider 池 SettingsStore schema | `store/settings_store.py` (改) | `llm.providers` + `llm.strategy.*` |
| 2.3 | HOT_RELOAD_KEYS 扩展 | `api/routes/settings_routes.py` (改) | 通配 `llm.strategy.*` |
| 2.4 | Pipeline 节点注入 ModelStrategy | `wiki/pipeline_orchestrator.py` (改) | configurable 新增 `model_strategy` |
| 2.5 | 各节点使用 ModelStrategy | `wiki/pipeline_nodes.py` (改) | `get_llm_port(task_type)` |
| 2.6 | Dashboard Provider 池 UI | `dashboard/src/components/settings/` (改) | 新增 `LLMProviderPoolSection` |
| 2.7 | Dashboard 策略路由 UI | `dashboard/src/components/settings/` (改) | 新增 `ModelStrategySection` |
| 2.8 | Provider 模型自动发现 API | `api/routes/provider_routes.py` (改) | `GET /llm/providers/{name}/models` |

### Sprint 3: 搜索系统迁移（预估 3-4 天）

| # | 任务 | 涉及文件 | 说明 |
|---|------|---------|------|
| 3.1 | `WikiAskService` 迁移到 IterativeRAGEngine | `wiki/ask.py` (改) | 保留 SSE v2 兼容 |
| 3.2 | `DeepSearchEngine` 迁移 | `query/deep_search.py` (改) | 替换内部循环 |
| 3.3 | `DeepResearchService` 迁移 | `wiki/deep_research.py` (改) | 综合步骤 LLM 化 |
| 3.4 | AskPanel 迭代过程 UI | `dashboard/src/components/wiki/AskPanel.tsx` (改) | 思考过程可视化 |
| 3.5 | DeepSearchSection 适配 | `dashboard/src/components/DeepSearchSection.tsx` (改) | 统一事件消费 |
| 3.6 | API 路由兼容适配 | `api/routes/wiki_ask_routes.py` (改) | page_path 参数 |

### Sprint 4: 增强功能（预估 2-3 天）

| # | 任务 | 涉及文件 | 说明 |
|---|------|---------|------|
| 4.1 | 复杂度评估器深化 (T8) | `wiki/domain_complexity.py` (改) | `CompositionStrategy` |
| 4.2 | 复杂度 → ModelStrategy 联动 | `wiki/pipeline_nodes.py` (改) | 按复杂度选模型 |
| 4.3 | code_structure 语义分组 (C4) | `wiki/tree_linker.py` (改) | 复用 `_semantic_group_modules` |
| 4.4 | MCP wiki_search + page_context (A1) | `wiki/mcp_tools.py` (改) | 参数扩展 |
| 4.5 | MCP unified_knowledge_query (A5) | `wiki/mcp_tools.py` (改) | 新工具 |
| 4.6 | 集成测试 | `tests/wiki/` | 全链路 |

### Sprint 5: 测试与文档（预估 1-2 天）

| # | 任务 | 说明 |
|---|------|------|
| 5.1 | 端到端测试 | 各场景覆盖 |
| 5.2 | 前端组件测试 | AskPanel 迭代 UI |
| 5.3 | 文档更新 | ARCHITECTURE.md, MCP-INTEGRATION.md |
| 5.4 | DEEP_ANALYSIS 更新 | 标记 T7/T8/P3/C4/A1/A5 完成 |

---

## 8. 迁移与回滚策略

### 8.1 渐进式迁移

三套搜索系统**逐个迁移**，每次迁移保留旧路径 72 小时：

| 阶段 | 操作 | 回滚方式 |
|------|------|---------|
| 1 | `WikiAskService` 增加 `use_iterative_rag` 开关（默认 false） | 关闭开关即回退 |
| 2 | 验证通过后默认启用，旧代码保留但标记 `@deprecated` | 切换开关 |
| 3 | `DeepSearchEngine` 同理 | 同上 |
| 4 | `DeepResearchService` 同理 | 同上 |
| 5 | 全部稳定后删除 `@deprecated` 旧代码 | — |

### 8.2 Feature Flags

| Flag | 默认值 | 说明 |
|------|--------|------|
| `WIKI__ITERATIVE_RAG_ENABLED` | false | 启用 IterativeRAGEngine |
| `WIKI__MODEL_STRATEGY_ENABLED` | false | 启用 Dashboard 模型策略配置 |
| `WIKI__CODE_STRUCTURE_SEMANTIC_GROUP` | false | 启用 code_structure 语义分组 |

---

## 9. 风险与缓解

| 风险 | 影响 | 缓解策略 |
|------|------|---------|
| IterativeRAGEngine 迭代次数过多导致成本飙升 | 高 LLM 调用费用 | 硬上限 + 快模型做 plan/evaluate + 成本监控 |
| 多 Provider 热切换时连接不稳定 | 搜索/生成失败 | Provider 健康检查 + fallback 到默认 |
| 语义分组质量不稳定 | code_structure 视图混乱 | 默认关闭 (feature flag)，逐步验证 |
| SSE 事件协议变更导致前端兼容性问题 | 旧客户端崩溃 | 新事件类型向前兼容，旧 type 保留 |
| 三套系统迁移期间的回归 | 搜索功能中断 | 逐个迁移，保留旧路径作 fallback |

---

## 10. 与现有架构的关系

```
新增组件:
  wiki/rag/              ← IterativeRAGEngine 及 Retriever 实现
  wiki/model_strategy.py ← 动态模型策略

改动组件:
  wiki/ask.py            ← 迁移到 IterativeRAGEngine
  wiki/deep_research.py  ← 迁移到 IterativeRAGEngine
  query/deep_search.py   ← 迁移到 IterativeRAGEngine
  wiki/pipeline_nodes.py ← 使用 ModelStrategy
  wiki/domain_complexity.py ← CompositionStrategy
  wiki/tree_linker.py    ← 语义分组
  wiki/mcp_tools.py      ← page_context + unified_query
  dashboard/src/components/wiki/AskPanel.tsx    ← 迭代 UI
  dashboard/src/components/settings/*           ← Provider 池 + 策略路由 UI
```
