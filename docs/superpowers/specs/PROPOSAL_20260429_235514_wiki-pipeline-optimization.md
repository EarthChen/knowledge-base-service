# Wiki Pipeline Optimization — 全面优化提案

**状态:** Draft  
**创建时间:** 2026-04-29  
**关联 Issues:** KNOWN-ISSUES.md Issue 1(P0）、Issue 3（P2）、Issue 4（P2）

---

## 1. 背景与目标

### 1.1 现状问题

Wiki 生成流水线存在以下核心问题：

| # | 问题 | 优先级 | 影响 |
|---|------|--------|------|
| Issue 1 | Wiki 页面粒度过细（~967 页） | P0 | 缺乏业务语义聚合，页面无业务价值 |
| Issue 3 | HierarchicalDecomposer 批次超时 | P2 | 某些批次 >2min 被跳过 |
| Issue 4 | Qwen3 思维链导致 LLM 响应极慢 | P2 | 分类批次 100+ 秒 |
| — | LLM 提示词缺乏优化空间 | — | 无 few-shot、无 JSON Schema、entity_digest 可能 token 爆炸 |
| — | 中间结果无持久化 | — | 每次全量重新生成，10-25 分钟 |
| — | 关键节点日志不足 | — | 问题排查困难 |

### 1.2 目标

- **页面粒度**：从 ~967 页降至 50-80 页（DeepWiki 风格）
- **生成性能**：增量更新从 10-25min 降至 2-5min
- **可观测性**：每次 LLM 调用、每个流水线阶段均有结构化日志
- **容错性**：失败可从 checkpoint 恢复，超时自动拆分重试
- **质量保障**：JSON 解析失败率 <1%（StructuredOutputRetry）；CORE 页面质量分 ≥0.7（WikiQualityGate）

### 1.3 设计原则

- **局部引入 LangGraph**：在流水线编排层直接引入 LangGraph，利用其开箱即用的 StateGraph、Checkpoint、Conditional Edge、Structured Output 能力
  - LangGraph StateGraph → Wiki 生成流水线编排
  - LangGraph Checkpoint（MemorySaver/RedisSaver）→ 中间结果持久化
  - LangGraph Conditional Edge → 质量评估-修复循环（WikiQualityGate）
  - LangChain `with_structured_output` + `OutputFixingParser` → JSON 结构化输出约束 + 自动修复
  - `json-repair`（项目已有依赖）→ JSON 自动修复的底层能力
  - LlamaIndex TreeSummarize 思想 → 分层分类策略（不引入框架）
- **引入范围约束**：
  - 在流水线编排层使用 LangGraph（StateGraph + Checkpoint + Conditional Edge）
  - Prompt 管理统一使用 LangChain `ChatPromptTemplate`，替代自实现 PromptRegistry（加薄包装层实现版本 + hash）
  - LLM 调用对外统一为 `LLMPortChatModel`（LangChain ChatModel），新代码全部使用 ChatModel API
  - `LLMPortBridge` 保留为底层实现（ai-gateway SDK adapter），`LLMPortChatModel` 包装它对接 LangChain 生态
  - 现有业务组件（WikiComposer、BusinessDomainPlanner 等）渐进迁移到 ChatModel API
  - 不引入 LangSmith（付费服务），继续用 structlog 记录日志
- **环境兼容性**：项目已满足 LangGraph 所有前置条件（Python ≥3.12、pydantic ≥2.10、httpx、tenacity、json-repair 均已就位）
- **Agent 循环机制**：通过两层 Agent Loop 保障质量（Loop 1: JSON 解析修复 via OutputFixingParser；Loop 2: 页面质量修复 via conditional edge）

---

## 2. 方案设计

### Sprint 1: LangGraph 基础接入 + 可观测性（~4 天）

#### 2.1.1 依赖引入

**文件**: `pyproject.toml`（修改）

```toml
dependencies = [
    # ... existing ...
    "langgraph>=0.2.0",
    "langchain-core>=0.3.0",
]
```

#### 2.1.2 LLMPortChatModel — LangChain Adapter

**文件**: `wiki/langchain_adapter.py`（新增）

将现有 LLMPortBridge 包装为 LangChain ChatModel，使其融入 LangGraph 生态：

```python
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, AIMessage
from langchain_core.outputs import ChatResult, ChatGeneration

class LLMPortChatModel(BaseChatModel):
    """Adapter wrapping LLMPortBridge as LangChain ChatModel.

    Preserves existing LLM infrastructure while enabling LangGraph features.
    """

    bridge: Any  # LLMPortBridge instance
    model_name: str = 'default'

    @property
    def _llm_type(self) -> str:
        return 'llm-port-bridge'

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        **kwargs,
    ) -> ChatResult:
        lm_messages = [
            {'role': 'user' if m.type == 'human' else m.type, 'content': m.content}
            for m in messages
        ]
        result = await self.bridge.complete(lm_messages, model=kwargs.get('model'))
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=result))]
        )

    def _generate(self, messages, stop=None, **kwargs):
        raise NotImplementedError('Use async via _agenerate')
```

**设计要点**：现有 LLMPortBridge 保留不动，Adapter 仅在 LangGraph 层使用。业务组件内部仍直接使用 `LLMPort` 协议。

#### 2.1.3 WikiPipelineState — 流水线状态定义

**文件**: `wiki/pipeline_state.py`（新增）

```python
from typing import TypedDict, Annotated
import operator

class WikiPipelineState(TypedDict):
    # --- Input ---
    business_id: str
    repositories: list[str]
    config: dict

    # --- Stage outputs ---
    modules: dict[str, list]
    domain_mapping: dict[str, list]
    domain_tree: list[dict] | None
    topic_structure: list[dict] | None
    pages: Annotated[list[dict], operator.add]

    # --- Quality tracking ---
    quality_scores: dict[str, float]
    pages_to_heal: list[str]
    heal_attempts: dict[str, int]

    # --- Observability ---
    stage_timings: dict[str, float]
    llm_call_count: int
    errors: list[str]
```

#### 2.1.4 build_wiki_pipeline() — StateGraph 定义

**文件**: `wiki/pipeline_graph.py`（新增）

```python
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

def build_wiki_pipeline() -> StateGraph:
    graph = StateGraph(WikiPipelineState)

    # Nodes — each wraps an existing business component
    graph.add_node('collect_modules', collect_modules_node)
    graph.add_node('classify_domains', classify_domains_node)
    graph.add_node('decompose_hierarchy', decompose_hierarchy_node)
    graph.add_node('plan_structure', plan_structure_node)
    graph.add_node('compose_pages', compose_pages_node)
    graph.add_node('quality_gate', quality_gate_node)
    graph.add_node('heal_pages', heal_pages_node)
    graph.add_node('finalize', finalize_node)

    # Linear flow
    graph.add_edge('collect_modules', 'classify_domains')
    graph.add_edge('classify_domains', 'decompose_hierarchy')
    graph.add_edge('decompose_hierarchy', 'plan_structure')
    graph.add_edge('plan_structure', 'compose_pages')
    graph.add_edge('compose_pages', 'quality_gate')

    # Quality gate loop (conditional edge)
    graph.add_conditional_edges(
        'quality_gate',
        should_heal,
        {'heal_pages': 'heal_pages', 'finalize': 'finalize'}
    )
    graph.add_edge('heal_pages', 'compose_pages')

    graph.set_entry_point('collect_modules')
    graph.set_finish_point('finalize')

    return graph.compile(checkpointer=MemorySaver())


def should_heal(state: WikiPipelineState) -> str:
    """Conditional edge: route to heal if low-quality pages exist."""
    if state.get('pages_to_heal') and any(
        state['heal_attempts'].get(p, 0) < 2 for p in state['pages_to_heal']
    ):
        return 'heal_pages'
    return 'finalize'
```

#### 2.1.5 Node 封装示例 — classify_domains_node

**文件**: `wiki/pipeline_graph.py`（新增，同上文件）

```python
async def classify_domains_node(state: WikiPipelineState) -> dict:
    """Wraps BusinessDomainPlanner.classify() as a LangGraph node."""
    t0 = time.monotonic()
    planner = BusinessDomainPlanner(llm=_get_llm(state))

    domain_mapping = {}
    for repo, modules in state['modules'].items():
        result = await planner.classify(repo, modules)
        for domain, names in result.items():
            domain_mapping.setdefault(domain, []).extend(
                [(repo, n) for n in names]
            )

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    log.info('pipeline_node_done', node='classify_domains',
             domains=len(domain_mapping), elapsed_ms=elapsed_ms)

    return {
        'domain_mapping': domain_mapping,
        'stage_timings': {**state.get('stage_timings', {}), 'classify_domains': elapsed_ms},
    }
```

**设计要点**：每个 node 只负责调用现有业务组件并更新 state。业务组件不感知 LangGraph。

#### 2.1.6 可观测性

LangGraph 内置 tracing 能力，配合 structlog 实现可观测性：

- **Node 级别**：每个 node 开始/结束自动记录日志（通过 LangGraph callback）
- **LLM 调用级别**：通过 LangChain callback handler 记录每次 LLM 调用的 tokens、耗时
- **Pipeline 级别**：finalize_node 输出总结报告（总耗时、各阶段耗时、LLM 调用数、页面数、质量分）

```python
from langchain_core.callbacks import AsyncCallbackHandler

class StructlogCallbackHandler(AsyncCallbackHandler):
    """Bridge LangGraph/LangChain events to structlog."""

    async def on_llm_start(self, serialized, prompts, **kwargs):
        log.info('llm_call_start', model=serialized.get('id', ['unknown'])[-1],
                 prompt_tokens=sum(len(p) // 3 for p in prompts))

    async def on_llm_end(self, response, **kwargs):
        log.info('llm_call_done', response_tokens=len(str(response)) // 3)

    async def on_llm_error(self, error, **kwargs):
        log.error('llm_call_failed', error=str(error)[:200])
```

#### 2.1.7 Prompt 管理 — 使用 LangChain ChatPromptTemplate

**文件**: `wiki/prompts.py`（新增）

使用 LangChain ChatPromptTemplate 统一管理所有 prompt，加薄包装层实现版本号 + content hash：

```python
import hashlib
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

def versioned_prompt(
    name: str,
    template: ChatPromptTemplate,
    version: str = "1.0",
) -> ChatPromptTemplate:
    """Attach version metadata to a ChatPromptTemplate for cache invalidation."""
    template.metadata = {'name': name, 'version': version}
    return template

def prompt_hash(template: ChatPromptTemplate, **kwargs) -> str:
    """Content hash for cache key derivation. Changes when prompt or version changes."""
    version = template.metadata.get('version', '1.0') if template.metadata else '1.0'
    content = f"{version}:{template.format(**kwargs)}"
    return hashlib.sha256(content.encode()).hexdigest()[:16]

# --- Prompt 定义 ---

DOMAIN_CLASSIFY_PROMPT = versioned_prompt(
    name='domain_classify',
    version='2.0',
    template=ChatPromptTemplate.from_messages([
        ('system', (
            "You are a software architecture expert. "
            "Classify repository modules into business domains. "
            "Output ONLY valid JSON."
        )),
        ('human', (
            "Classify the following modules into business domains.\n\n"
            "Rules:\n"
            "- Use 5-20 domains, lowercase-kebab-case names, 1-3 words\n"
            "- Each domain must have ≥3 modules\n"
            "- Place shared utilities under '{infrastructure_label}'\n\n"
            "Example output:\n"
            '{{"user-management": ["UserService", "AuthController"], '
            '"__infrastructure__": ["Utils", "Config"]}}\n\n'
            "Repository: {repository_id}\n"
            "Modules:\n{modules_json}\n\n"
            "Return ONLY valid JSON."
        )),
    ]),
)

TOPIC_STRUCTURE_PROMPT = versioned_prompt(
    name='topic_structure',
    version='1.0',
    template=ChatPromptTemplate.from_messages([
        ('system', "You are a technical documentation planner. Output ONLY valid JSON."),
        ('human', (
            "Based on the following business domain classification, plan a Wiki structure.\n\n"
            "Rules:\n"
            "1. Generate {min_pages}-{max_pages} topic pages total\n"
            "2. Each top-level topic = one business domain or a merge of related domains\n"
            "3. Each topic can have 3-5 sub-pages\n"
            "4. Each page should cover a complete business capability\n"
            "5. Assign every module to exactly one page\n\n"
            "Domains:\n{domain_mapping_json}\n\n"
            "Output JSON: array of {{title, description, modules: [[repo, name], ...], sub_topics: [...]}}"
        )),
    ]),
)
```

**优势**（相比自实现 PromptRegistry）：
- 零额外代码量（langchain-core 已有）
- 与 `with_structured_output`、`OutputFixingParser` 无缝集成
- 支持 `MessagesPlaceholder` 用于 few-shot 动态注入
- `prompt_hash()` 薄包装实现版本号 + cache 失效

---

### Sprint 2: Checkpoint 持久化 + 结构化输出容错（~4 天）

#### 2.2.1 LangGraph Checkpoint 持久化

**使用 LangGraph 内置能力**，不自实现。

Sprint 1 的 `MemorySaver` 在生产环境替换为持久化后端：

```python
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
# 或 Redis 后端（需 langgraph-checkpoint-redis）
# from langgraph.checkpoint.redis import RedisSaver

def build_wiki_pipeline(checkpoint_backend: str = 'sqlite') -> StateGraph:
    if checkpoint_backend == 'redis':
        checkpointer = RedisSaver(redis_url=settings.redis_url)
    else:
        checkpointer = AsyncSqliteSaver.from_conn_string('.wiki_pipeline_cache/checkpoints.db')

    return graph.compile(checkpointer=checkpointer)
```

**优势对比**：

| 维度 | 自实现 WikiPipelineCheckpoint | LangGraph Checkpoint |
|------|--------------------------|----------------------|
| 代码量 | ~200 行 | 0 行（配置即用） |
| 状态恢复 | 手动按 stage 恢复 | 自动从任意 node 恢复 |
| 序列化 | 手动 JSON | 自动（支持 pickle/json） |
| 并发安全 | 依赖 TaskLock | 内置 thread_id 隔离 |
| 存储后端 | 手动实现 Redis/disk | 官方 Redis/Sqlite/Postgres adapter |

**各阶段缓存效果**（与原提案一致）：

| 阶段 | 缓存键 = state snapshot | 预估节省 |
|------|--------------------------|----------|
| classify_domains | modules hash | 60-180s |
| decompose_hierarchy | modules + domains hash | 30-120s |
| compose_pages | entity + code hash + prompt version | ~80% 页面 |

**预估效果**：增量更新从 10-25min 降至 2-5min。

#### 2.2.2 结构化输出容错 — json-repair + OutputFixingParser

**使用项目已有 `json-repair` 依赖 + LangChain 内置 OutputFixingParser**，不自实现。

**问题背景**：项目中有 8+ 处 JSON 解析逻辑，全部采用"试一次，失败就放弃"的模式。

**三级修复策略**：

```python
from json_repair import repair_json
from langchain.output_parsers import OutputFixingParser
from langchain_core.output_parsers import JsonOutputParser

def create_robust_json_parser(llm: LLMPortChatModel, schema: dict | None = None):
    """Create a robust JSON parser with 3-level retry."""
    base_parser = JsonOutputParser(pydantic_object=schema) if schema else JsonOutputParser()
    return OutputFixingParser.from_llm(parser=base_parser, llm=llm, max_retries=2)

async def parse_json_robust(raw: str, llm: LLMPortChatModel | None = None) -> dict | None:
    """Parse JSON with 3-level repair strategy:
    1. json.loads — direct parse
    2. json_repair.repair_json — auto-fix (trailing comma, unclosed brackets, etc.)
    3. OutputFixingParser — LLM fix (agent loop, send error + raw to LLM)
    """
    # Level 1: Direct parse
    text = _strip_fences(raw)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Level 2: json-repair auto-fix
    try:
        repaired = repair_json(text, return_objects=True)
        if isinstance(repaired, (dict, list)):
            log.info('json_auto_repaired', strategy='json-repair')
            return repaired
    except Exception:
        pass

    # Level 3: LLM fix loop (agent loop via OutputFixingParser)
    if llm is not None:
        try:
            fixing_parser = OutputFixingParser.from_llm(
                parser=JsonOutputParser(), llm=llm, max_retries=2
            )
            result = await fixing_parser.aparse(raw)
            log.info('json_llm_fixed', strategy='OutputFixingParser')
            return result
        except Exception as e:
            log.warning('json_all_retries_exhausted', error=str(e)[:200])

    return None
```

**集成方式**：替换项目中 8+ 处重复的 `_parse_domain_map()` 等方法：

```python
# 优化前
raw = (await self._llm.generate(prompt, system="Reply with JSON only.")).strip()
parsed = self._parse_domain_map(raw)
if not parsed:
    return self._all_infrastructure(names_in_order)

# 优化后
raw = (await self._llm.generate(prompt, system="Reply with JSON only.")).strip()
parsed = await parse_json_robust(raw, llm=self._chat_model)
if not parsed or not isinstance(parsed, dict):
    log.warning('json_parse_all_retries_exhausted', task='domain_classify')
    return self._all_infrastructure(names_in_order)
return self._validate_domain_map(parsed)
```

**预估效果**：JSON 解析失败率从 ~5-15% 降至 <1%。

#### 2.2.3 with_structured_output — JSON Schema 约束

对关键的 LLM 调用使用 LangChain 的 `with_structured_output`：

```python
from pydantic import BaseModel

class DomainClassification(BaseModel):
    domains: dict[str, list[str]]  # domain_name -> [module_names]

structured_llm = chat_model.with_structured_output(DomainClassification)
result = await structured_llm.ainvoke(messages)
```

**适用场景**：需要确认 ai-gateway 是否支持 JSON mode / function calling。支持时使用 `with_structured_output`，不支持时用 `parse_json_robust` 作为 fallback。

#### 2.2.4 Qwen3 思维链禁用

**文件**: `llm/base_provider.py`（修改）

在 `LLMPortBridge.generate()` 增加 `extra_params` 支持：

```python
async def generate(self, prompt: str, system: str = '', *,
                   model: str | None = None,
                   extra_params: dict[str, Any] | None = None) -> str:
    # extra_params 透传到 complete/complete_stream
```

#### 2.2.5 模型路由 — 通过 LangGraph config 实现

使用 LangGraph 的 configurable 机制而非自实现 WikiModelRouter：

```python
# 在 node 中根据 task_type 选择模型
async def classify_domains_node(state: WikiPipelineState, config: RunnableConfig) -> dict:
    model = config.get('configurable', {}).get('classification_model', 'default')
    llm = _get_llm(state, model=model)
    ...

# 调用时传入配置
result = await pipeline.ainvoke(
    initial_state,
    config={'configurable': {
        'classification_model': 'qwen3-fast',
        'generation_model': 'qwen3-full',
    }}
)
```

#### 2.2.6 AdaptiveBatchSizer — 自适应批次大小

**文件**: `wiki/adaptive_batch.py`（新增，保留自实现 — 业务逻辑，非编排逻辑）

```python
class AdaptiveBatchSizer:
    """Dynamically adjust batch size based on LLM response time."""

    def __init__(self, initial_size: int = 80, min_size: int = 20, max_size: int = 150):
        self._current = initial_size
        self._min = min_size
        self._max = max_size

    def next_size(self) -> int:
        return self._current

    def record(self, batch_size: int, elapsed_s: float, success: bool) -> None:
        if not success or elapsed_s > 90:
            self._current = max(self._min, self._current // 2)
        elif elapsed_s < 30 and batch_size == self._current:
            self._current = min(self._max, int(self._current * 1.3))
```

#### 2.2.7 Timeout-Split-Retry — 超时拆分重试

**文件**: `wiki/business_domain_planner.py`（修改，保留自实现 — 业务逻辑）

```python
async def _run_batch_with_retry(self, batch, ...):
    try:
        return await asyncio.wait_for(self._classify_single_batch(batch, ...), timeout=120)
    except TimeoutError:
        if len(batch) <= 20:
            return self._all_infrastructure(batch)
        mid = len(batch) // 2
        log.warning("batch_timeout_split", original_size=len(batch))
        r1 = await self._run_batch_with_retry(batch[:mid], ...)
        r2 = await self._run_batch_with_retry(batch[mid:], ...)
        return self._merge_results(r1, r2)
```

---

### Sprint 3: Prompt 优化（~3 天）

#### 2.3.1 域分类 Prompt 重构

**文件**: `wiki/business_domain_planner.py`（修改）

优化前后对比：

| 维度 | 优化前 | 优化后 |
|------|--------|--------|
| Few-shot | 无 | 包含 3 个模块的分类示例 |
| 域数量约束 | 无 | `target_domain_range=(5, 20)` |
| 命名规范 | 无 | lowercase-kebab-case, 1-3 words |
| 最小域大小 | 无 | ≥3 模块 |
| System prompt | "Reply with JSON only" | 专业化描述 |
| 输出方式 | `generate()` + 手动 JSON 解析 | `complete_json()` + JSON Schema（需确认 ai-gateway 支持 JSON mode；不支持时保留 `generate()` + 手动解析作为 fallback） |

#### 2.3.2 entity_digest Token 限制

**文件**: `wiki/composer.py`（修改）

在 `_entity_digest()` 中增加 `max_tokens=4000` 参数：
- 代码片段优先截断（通常最长）
- 方法列表超过 15 个时省略剩余
- related_chunks 超过 3 个时省略剩余

#### 2.3.3 内容生成 Prompt 拆分

**参考**: LangGraph 的节点化思想

将 `_tier2_llm()` 的单次大 prompt 拆为多步：

1. **概述节点**: 生成 Purpose & Key Components（基于元数据）
2. **流程节点**: 生成 Data Flow + How it Works（基于边关系）
3. **图表节点**: 生成 Mermaid diagrams（独立调用，可用专用模型）
4. **合并节点**: 将 1-3 的输出拼装为最终页面（无 LLM 调用）

**执行顺序**：Step 1（概述）→ Step 2（流程分析）顺序执行（Step 2 依赖 Step 1 的上下文）；Step 3（图表）可与 Step 1-2 并行（仅依赖 entity_digest 原始数据）；Step 4（合并）是纯字符串拼接无 LLM 调用。

好处：
- 每步 prompt 更短、更聚焦
- 各节点可独立缓存（概述不变时不重新生成流程图）
- 各节点可用不同模型/参数

#### 2.3.4 跨仓合并 Prompt 简化

**文件**: `wiki/cross_repo_domain_planner.py`（修改）

简化输出格式：从嵌套对象 `{unified: {repo: original}}` 改为 `{unified: [original_names]}`。添加 few-shot example。

---

### Sprint 4: 粒度优化 — 解决 Issue 1 P0（~5 天）

#### 2.4.1 ImportanceTier 过滤

**文件**: `wiki/structure_planner.py`（修改）

在 `_build_module_tree()` 中接收 `importance_tiers` dict，SKELETON 实体不生成独立页面。

用于 repo-level wiki（代码结构视图），减少噪音页面。

#### 2.4.2 TopicBasedStructurePlanner — LLM 驱动的主题结构规划

**文件**: `wiki/topic_structure_planner.py`（新增）

**设计参考**：DeepWiki — LLM 分析文件树 → 生成 XML wiki 结构（8-12 页），每页覆盖一个功能主题。

```python
class TopicBasedStructurePlanner:
    """LLM-driven wiki structure planning by business topics."""

    def __init__(self, llm: LLMPort, prompt_registry: PromptRegistry):
        self._llm = llm
        self._registry = prompt_registry

    async def plan(self, domain_mapping: dict[str, list[tuple[str, str]]],
                   module_metadata: dict[tuple[str, str], dict],
                   importance_tiers: dict[str, str],
                   *, target_pages: tuple[int, int] = (40, 80)) -> list[TopicPage]:
        """Generate topic-based wiki structure.

        Returns list of TopicPage, each containing:
        - title, description
        - covered_modules: list of (repo, module_name) pairs
        - sub_topics: optional child pages
        """
        ...
```

**Prompt 设计**：
```
Based on the following business domain classification, plan a Wiki structure.

Rules:
1. Generate {min}-{max} topic pages total
2. Each top-level topic = one business domain or a merge of related domains
3. Each topic can have 3-5 sub-pages
4. Each page should cover a complete business capability
5. Assign every module to exactly one page

Domains:
{domain_mapping_with_module_summaries}

Output JSON: array of {title, description, modules: [[repo, name], ...], sub_topics: [...]}
```

**与现有组件的关系**：
- 替代 `WikiStructurePlanner._plan_repo()` 在 business wiki 场景中的使用
- 与 `DomainOverviewComposer` 配合：每个主题页 = 一个 domain overview
- 保留现有的 repo-level wiki 作为代码结构视图
- 两个视图通过已有的 `view_type` (business_domain / code_structure) 隔离

**Fallback 策略**：当 LLM 生成的主题结构无效（JSON 解析失败或结构不合理）时，fallback 到 domain_mapping 直接映射方式（每个 domain = 一个主题页），保证流程不中断。

**预估效果**：12 顶层主题 × 4 子页 = ~60 页面（从 967 降至 ~60，符合目标）

---

### Sprint 5: 质量保障 — LangGraph 质量循环（~2 天）

#### 2.5.1 质量评估 + 修复循环 — LangGraph Conditional Edge 实现

**使用 LangGraph 内置的 conditional edge 实现质量循环**，不自实现 WikiQualityGate 类。

Sprint 1 中定义的 `quality_gate` node + `heal_pages` node + `should_heal` conditional edge 已经构成了完整的质量循环。Sprint 5 负责实现这些 node 的具体逻辑。

```python
async def quality_gate_node(state: WikiPipelineState) -> dict:
    """Evaluate page quality, identify pages that need healing."""
    evaluator = WikiQualityEvaluator(llm=_get_llm(state))
    scores = {}
    pages_to_heal = []

    for page_dict in state['pages']:
        page = WikiPage.from_dict(page_dict)
        tier = _get_importance_tier(page, state)

        if tier == ImportanceTier.SKELETON:
            scores[page.path] = 1.0
            continue

        if tier == ImportanceTier.CORE:
            score = await evaluator.llm_judge_evaluate(page)
            threshold = 0.7
        else:
            score = evaluator.structural_check(page)
            threshold = 0.5

        scores[page.path] = score.overall
        attempts = state.get('heal_attempts', {}).get(page.path, 0)
        max_retries = 2 if tier == ImportanceTier.CORE else 1
        if score.overall < threshold and attempts < max_retries:
            pages_to_heal.append(page.path)

    return {
        'quality_scores': scores,
        'pages_to_heal': pages_to_heal,
    }


async def heal_pages_node(state: WikiPipelineState) -> dict:
    """Regenerate low-quality pages with heal hints."""
    evaluator = WikiQualityEvaluator()
    healed_pages = []
    heal_attempts = dict(state.get('heal_attempts', {}))

    for page_path in state['pages_to_heal']:
        page_dict = next((p for p in state['pages'] if p['path'] == page_path), None)
        if not page_dict:
            continue

        page = WikiPage.from_dict(page_dict)
        score = WikiPageQualityScore(
            page_path=page.path,
            completeness=state['quality_scores'].get(page.path, 0),
            overall=state['quality_scores'].get(page.path, 0),
        )
        heal_hint = evaluator.build_heal_prompt_hint(score)
        heal_attempts[page_path] = heal_attempts.get(page_path, 0) + 1

        new_page = await _recompose_page_with_hint(page, heal_hint, state)
        healed_pages.append(new_page.to_dict())
        log.info('page_healed', page=page_path, attempt=heal_attempts[page_path])

    # Replace healed pages in state
    updated_pages = [
        p for p in state['pages'] if p['path'] not in state['pages_to_heal']
    ]
    updated_pages.extend(healed_pages)

    return {
        'pages': updated_pages,
        'heal_attempts': heal_attempts,
        'pages_to_heal': [],  # clear for next quality_gate evaluation
    }


def should_heal(state: WikiPipelineState) -> str:
    """Conditional edge: route to heal if low-quality pages exist."""
    if state.get('pages_to_heal'):
        return 'heal_pages'
    return 'finalize'
```

**质量策略矩阵**（与原方案一致）：

| ImportanceTier | 检查方式 | 阈值 | 最大重试 | 重试增强 |
|---|---|---|---|---|
| SKELETON | 无检查 | — | 0 | — |
| STANDARD | structural_check | 0.5 | 1 | heal_prompt_hint |
| CORE | structural + llm_judge | 0.7 | 2 | heal_prompt_hint + 上次评分反馈 |

**优势**：利用 LangGraph 的 conditional edge，质量循环逻辑变为纯图定义（~5 行配置），无需手写 while loop 或 retry 逻辑。且循环过程中的每次状态变更都会被 Checkpoint 自动持久化。

#### 2.5.2 QualityGateConfig — 质量门槛配置

**文件**: `config.py`（修改）

```python
@dataclass
class QualityGateConfig:
    enabled: bool = True
    core_threshold: float = 0.7
    standard_threshold: float = 0.5
    core_max_retries: int = 2
    standard_max_retries: int = 1
    use_llm_judge_for_core: bool = True
```

生产环境可随时关闭质量门槛以牺牲质量换取速度。

#### 2.5.3 finalize_node — 综合质量报告

```python
async def finalize_node(state: WikiPipelineState) -> dict:
    """Output quality report and pipeline summary."""
    scores = state.get('quality_scores', {})
    heal_attempts = state.get('heal_attempts', {})
    timings = state.get('stage_timings', {})

    healed_count = sum(1 for v in heal_attempts.values() if v > 0)
    flagged = [p for p, s in scores.items() if s < 0.5]

    log.info('pipeline_complete', **{
        'total_pages': len(state.get('pages', [])),
        'passed_first_attempt': len(scores) - healed_count - len(flagged),
        'healed': healed_count,
        'flagged_low_quality': len(flagged),
        'avg_score': sum(scores.values()) / max(len(scores), 1),
        'total_elapsed_ms': sum(timings.values()),
        'stage_timings': timings,
        'llm_call_count': state.get('llm_call_count', 0),
    })

    return {'errors': []}
```

#### 2.5.4 Agent 循环架构视图

两层 Agent Loop 的嵌套关系（均由 LangGraph 管理）：

```
┌──────────────────────────────────────────────────────────────────┐
│ LangGraph StateGraph                                             │
│                                                                  │
│ Loop 2 (Conditional Edge): compose_pages → quality_gate          │
│                                  ↑              │                │
│                                  │     [不达标] → heal_pages     │
│                                  └──────────────┘                │
│                                              │                   │
│                                     [达标] → finalize            │
│                                                                  │
│   ┌──────────────────────────────────────────────────────┐       │
│   │ Loop 1 (OutputFixingParser): 每次 LLM 调用内置         │       │
│   │                                                      │       │
│   │   generate → json.loads → [失败] → json_repair       │       │
│   │      ↑                            → [仍失败] →        │       │
│   │      └─── OutputFixingParser (LLM fix) ←──┘          │       │
│   └──────────────────────────────────────────────────────┘       │
│                                                                  │
│   ✅ 所有状态变更自动 Checkpoint 持久化                             │
└──────────────────────────────────────────────────────────────────┘
```

---

## 3. 影响范围

### 新增文件

| 文件 | 内容 | Sprint |
|------|------|--------|
| `wiki/langchain_adapter.py` | LLMPortChatModel Adapter + StructlogCallbackHandler | 1 |
| `wiki/pipeline_state.py` | WikiPipelineState TypedDict | 1 |
| `wiki/pipeline_graph.py` | build_wiki_pipeline() StateGraph + 所有 node 定义 | 1, 5 |
| `wiki/prompts.py` | 所有 LangChain ChatPromptTemplate 定义 + versioned_prompt + prompt_hash | 1 |
| `wiki/json_robust.py` | parse_json_robust() — json-repair + OutputFixingParser 集成 | 2 |
| `wiki/adaptive_batch.py` | AdaptiveBatchSizer | 2 |
| `wiki/topic_structure_planner.py` | TopicBasedStructurePlanner | 4 |

### 修改文件

| 文件 | 修改内容 | Sprint |
|------|---------|--------|
| `pyproject.toml` | 新增 langgraph + langchain-core 依赖 | 1 |
| `llm/base_provider.py` | `generate()` 增加 `extra_params` 支持 | 2 |
| `wiki/service.py` | 用 pipeline_graph 替代内联流水线编排 | 1 |
| `wiki/business_domain_planner.py` | prompt 重构 + timeout-split-retry + adaptive batch + parse_json_robust | 2-3 |
| `wiki/cross_repo_domain_planner.py` | 合并 prompt 简化 + parse_json_robust | 2-3 |
| `wiki/dependency_graph.py` | parse_json_robust 迁移 | 2 |
| `wiki/context.py` | parse_json_robust 迁移 | 2 |
| `wiki/cot_generator.py` | parse_json_robust 迁移 | 2 |
| `wiki/quality_evaluator.py` | parse_json_robust 迁移 | 2 |
| `wiki/composer.py` | entity_digest token 限制 + 多步 prompt | 3 |
| `wiki/structure_planner.py` | importance_tier 过滤 | 4 |
| `wiki/tiered_prompts.py` | token 限制指导 | 3 |
| `config.py` | WikiConfig + QualityGateConfig 新增字段 | 2, 5 |

### 不再需要自实现的文件（LangGraph 替代）

| 原计划自实现 | 替代方案 |
|------------|---------|
| `wiki/pipeline_checkpoint.py` | LangGraph MemorySaver / AsyncSqliteSaver / RedisSaver |
| `wiki/structured_output_retry.py` | json-repair + LangChain OutputFixingParser |
| `wiki/quality_gate.py` | LangGraph conditional edge（quality_gate_node + heal_pages_node） |
| `wiki/model_router.py` | LangGraph configurable + RunnableConfig |
| `wiki/llm_tracer.py` | LangChain AsyncCallbackHandler + StructlogCallbackHandler |
| `wiki/pipeline_timer.py` | LangGraph node tracing（内置） |
| `wiki/prompt_registry.py` | LangChain ChatPromptTemplate + versioned_prompt 薄包装 |

---

## 4. 风险评估

| Sprint | 风险等级 | 风险说明 | 缓解措施 |
|--------|---------|----------|----------|
| Sprint 1 | **中** | LangGraph 框架引入，需要验证与现有异步架构兼容 | LangGraph 原生支持 async；先在独立分支验证；Adapter 仅 ~30 行；业务组件不改动 |
| Sprint 2 | 中 | Checkpoint 序列化可能遇到自定义对象问题；json-repair 修复可能引入意外数据 | state 全部使用 TypedDict + 基本类型；json-repair 后做 schema 验证 |
| Sprint 3 | 中 | prompt 变更可能影响生成质量 | 新旧 prompt 对比测试；可回退 |
| Sprint 4 | 高 | 架构级改动 | 保留现有 code_structure 视图不变；新增 topic 视图并行 |
| Sprint 5 | 低 | LangGraph conditional edge 已在 Sprint 1 定义，Sprint 5 仅实现 node 逻辑 | 配置化开关；SKELETON 跳过；LLM Judge 仅 CORE 页面 |

---

## 5. 不做什么

- **不引入 LlamaIndex 框架**：仅借鉴其 TreeSummarize 思想
- **不引入 LangSmith**：付费服务，继续用 structlog 记录日志
- **不做流式结果增量持久化**：LangGraph Checkpoint 已覆盖此需求
- **不对已修复的 Issue 2 做进一步改动**
- **不一次性重构所有现有业务组件的 LLM 调用方式**：渐进迁移到 ChatModel API

---

## 6. 未来规划 — 多 Agent 扩展

基于 Sprint 1 引入的 LangGraph StateGraph，后续可以自然地扩展为多 Agent 协作架构。

### Sprint 6（未来）: 多 Agent 协作

将当前单一流水线拆分为多个专业化 Agent，通过 LangGraph 的 sub-graph / multi-agent 机制协作：

```
┌─────────────────────────────────────────────┐
│           Wiki Orchestrator Agent            │
│         (LangGraph StateGraph - 主图)         │
│                                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │ Structure │  │ Content  │  │ Quality  │  │
│  │ Planner   │  │Generator │  │Reviewer  │  │
│  │ Agent     │  │ Agent    │  │ Agent    │  │
│  │(sub-graph)│  │(sub-graph)│  │(sub-graph)│  │
│  └──────────┘  └──────────┘  └──────────┘  │
│       ↓              ↓              ↓       │
│   域分类 +         页面内容生成      质量评估 +  │
│   主题规划 +       Mermaid 图表    修复建议 +   │
│   结构编排         交叉引用          一致性检查   │
└─────────────────────────────────────────────┘
```

**各 Agent 职责**：

| Agent | 职责 | LangGraph 实现 |
|-------|------|---------------|
| Structure Planner | 域分类、层级分解、主题结构规划 | Sub-graph with own state |
| Content Generator | 页面内容生成、Mermaid 图表、交叉引用 | Sub-graph with parallel nodes |
| Quality Reviewer | 质量评估、修复建议、一致性检查 | Sub-graph with conditional loops |

**触发条件**：当单一流水线的 node 数量超过 ~12 个，或需要不同的 LLM 角色设定（system prompt）时。

### Sprint 7（未来）: Human-in-the-Loop

利用 LangGraph 的 `interrupt_before` / `interrupt_after` 机制，在关键节点引入人工审核：

```python
graph.compile(
    checkpointer=checkpointer,
    interrupt_before=['plan_structure'],  # 结构规划前等待人工确认
)
```

适用场景：首次为大型项目生成 Wiki 时，让开发者确认域分类和主题结构的合理性。

### Sprint 8（未来）: 智能增量更新

利用 LangGraph 的 state diff + checkpoint，实现代码变更 → 受影响页面精准更新：
- 监测 git push 事件（已有 webhook）
- 计算受影响的 modules（已有 change_detector）
- 从 checkpoint 恢复上次状态，仅重新执行受影响的 nodes
- LangGraph 的 conditional edge 可跳过未受影响的 stages
