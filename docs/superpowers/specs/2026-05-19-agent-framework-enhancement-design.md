# Agent Framework Enhancement — Design Spec

> **状态**: Draft | **日期**: 2026-05-19  
> **前置**: [OpenAI Agents SDK 分析](./2026-05-19-openai-agent-sdk-patterns-analysis.md) | 统一 AgentRunner 已完成

---

## 1. 目标

基于 OpenAI Agents SDK 分析结果，将 6 个高价值模式引入现有 Agent 框架，提升架构整洁度、可测试性和可观测性，同时保留项目独有优势（Tiered Tools、Explore/Write 分离、EarlyStop）。

**约束**：
- 渐进式实施，每个模式独立 PR
- 可较大重构，追求理想架构
- 零回归：所有现有测试必须通过

---

## 2. 分层实施计划

```
Layer 0 ─ WikiRunContext<T>           (DI 基础，所有后续层的依赖)
Layer 1 ─ Guardrails + output_type   (直接提升质量)
Layer 2 ─ @function_tool + Tracing   (提升开发体验)
Layer 3 ─ Handoff                    (多 Agent 扩展)
```

---

## 3. Layer 0: WikiRunContext — 类型化依赖注入

### 3.1 问题

当前 Agent 的依赖通过构造函数注入到 `self` 上：

```python
class WikiPageAgent(GenericAgent):
    def __init__(self, llm, graph_store, *, repo_path=None, search_service=None, ...):
        self._graph = graph_store
        self._repo_path = repo_path
        self._search_service = search_service
```

工具通过 `self._graph` 访问依赖，导致：
- 工具与 agent 实例耦合，无法独立测试
- delegation 状态 (`_delegation_depth`) 挂在 agent 上，多次调用共享状态
- trace_id 无法自然传递

### 3.2 设计

```python
# wiki/agents/context.py

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

T = TypeVar("T")

@dataclass
class RunContext(Generic[T]):
    """Typed DI context passed to tools, guardrails, hooks. NOT sent to LLM."""
    deps: T
    trace_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class WikiDeps:
    """Wiki-specific dependencies."""
    graph_store: Any
    search_service: Any | None = None
    repo_path: str | None = None
    business_id: str = ""
    existing_pages: list[dict] | None = None
    delegation_depth: int = 0
    delegation_count: int = 0


# Convenience alias
WikiRunContext = RunContext[WikiDeps]
```

### 3.3 ToolDef 签名变更

```python
@dataclass
class ToolDef:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[dict[str, Any], RunContext], Awaitable[dict[str, Any]]]
    tier: int = 1
```

### 3.4 迁移策略

- `WikiPageAgent.__init__` 接收 `deps: WikiDeps` 替代散落参数
- 保留旧签名作为兼容 shim（`graph_store` → `WikiDeps(graph_store=graph_store, ...)`)
- 工具 handler 从 `self._graph` 改为 `ctx.deps.graph_store`
- `ToolRegistry.dispatch` 增加 `ctx` 参数

### 3.5 影响范围

| 文件 | 改动 |
|------|------|
| `wiki/agents/context.py` | 新增 |
| `wiki/agents/base_agent.py` | `ToolDef`, `ToolRegistry.dispatch`, `run_tool_loop` 增加 ctx |
| `wiki/page_agent.py` | 所有 `_tool_*` 方法签名 + 内部从 self 改 ctx |
| `wiki/agents/edit_agent.py` | 同上 |
| `wiki/domain_doc_agent.py` | 构造 WikiDeps 传入 |
| `wiki/nodes/*.py` | 构造 agent 时传 deps |
| 测试文件 | 构造 WikiDeps mock |

---

## 4. Layer 1a: Guardrails 标准化

### 4.1 问题

当前防护栏分散且不一致：
- `DefaultToolGuardrail` 有 pre/post_call，但仅工具层
- `OutputGuardrailChain` 在循环外，无法中断
- 无 input guardrail
- 无 tripwire（失败即停）语义

### 4.2 设计

```python
# wiki/agents/guardrails.py

from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol, Any

@dataclass
class GuardrailResult:
    """Result of a guardrail check."""
    passed: bool
    output_info: str = ""
    tripwire: bool = False  # True = immediately abort the loop


class InputGuardrail(Protocol):
    """Runs before the first LLM call in run_tool_loop."""
    async def check(self, user_prompt: str, ctx: RunContext) -> GuardrailResult: ...


class OutputGuardrail(Protocol):
    """Runs after the final output is produced."""
    async def check(self, output: str, ctx: RunContext) -> GuardrailResult: ...


class ToolGuardrail(Protocol):
    """Runs around each tool dispatch."""
    async def pre_call(self, name: str, args: dict, ctx: RunContext) -> dict | None: ...
    async def post_call(self, name: str, args: dict, result: str, ctx: RunContext) -> str: ...
```

### 4.3 RunConfig 集成

```python
@dataclass
class RunConfig:
    # ... existing fields ...
    input_guardrails: list[InputGuardrail] = field(default_factory=list)
    output_guardrails: list[OutputGuardrail] = field(default_factory=list)
```

### 4.4 行为规则

- Input guardrails 在首次 LLM 调用前执行
- 任何 guardrail 返回 `tripwire=True` → 立即中断循环，抛出 `GuardrailTrippedError`
- Tool guardrail 的 `pre_call` 返回 `None` → 跳过该工具调用（已有行为）
- Output guardrails 在 `run_generation` 结束后执行

### 4.5 迁移

- `DefaultToolGuardrail` 适配到新 `ToolGuardrail` 协议（增加 ctx 参数）
- `OutputGuardrailChain` 适配为 `OutputGuardrail` 实现
- 新增 `InputGuardrail` 实现：`PromptLengthGuardrail`（防止过长 prompt 消耗 token）

---

## 5. Layer 1b: output_type 声明式结构化输出

### 5.1 问题

当前结构化输出处理散落在多处：
- `WikiPageAgent.write()` 手动调用 `complete_json` + fallback
- 其他 agent 没有统一的结构化输出机制

### 5.2 设计

```python
class GenericAgent(ABC):
    output_type: type[BaseModel] | None = None

    async def run_generation(self, system_prompt: str, user_prompt: str) -> str:
        if self.output_type:
            try:
                result = await self._llm.complete_json(
                    [{"role": "system", "content": system_prompt},
                     {"role": "user", "content": user_prompt}],
                    schema=self.output_type.model_json_schema(),
                )
                return self._render_output(result)
            except Exception:
                log.warning("structured_output_failed_fallback_to_text", exc_info=True)
        return await self._llm.generate(prompt=user_prompt, system=system_prompt)

    def _render_output(self, structured: dict) -> str:
        """Override in subclass to render structured output to final format."""
        return json.dumps(structured, ensure_ascii=False)
```

### 5.3 WikiPageAgent 适配

```python
class WikiPageAgent(GenericAgent):
    output_type = WikiPageOutput

    def _render_output(self, structured: dict) -> str:
        page = WikiPageOutput.model_validate(structured)
        return render_wiki_page(page)
```

---

## 6. Layer 2a: @function_tool 装饰器

### 6.1 问题

14+ 工具的 JSON Schema 手写维护，修改工具签名需同步更新 schema。

### 6.2 设计

```python
# wiki/agents/tool_decorator.py

import inspect
from typing import get_type_hints

def function_tool(
    name: str | None = None,
    *,
    tier: int = 1,
    description: str | None = None,
):
    """Auto-generate ToolDef from function signature + type hints."""
    def decorator(fn):
        tool_name = name or fn.__name__
        hints = get_type_hints(fn)
        params_schema = _build_params_schema(fn, hints)
        fn._tool_def = ToolDef(
            name=tool_name,
            description=description or (fn.__doc__ or "").strip().split("\n")[0],
            parameters=params_schema,
            handler=fn,
            tier=tier,
        )
        return fn
    return decorator


def _build_params_schema(fn, hints: dict) -> dict:
    """Build JSON Schema from function parameters (skip 'self', 'ctx')."""
    sig = inspect.signature(fn)
    properties = {}
    required = []
    for param_name, param in sig.parameters.items():
        if param_name in ("self", "ctx", "args"):
            continue
        prop = _type_to_json_schema(hints.get(param_name, str))
        properties[param_name] = prop
        if param.default is inspect.Parameter.empty:
            required.append(param_name)
    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }
```

### 6.3 用法示例

```python
class WikiPageAgent(GenericAgent):
    @function_tool(tier=1)
    async def query_module_detail(self, name: str, ctx: WikiRunContext) -> dict:
        """Query detailed info about a module including methods and dependencies."""
        graph = ctx.deps.graph_store
        # ... implementation ...
```

### 6.4 迁移策略

- 新增装饰器模块
- 逐步将 14 个工具从手写 schema 迁移到装饰器
- `_register_tools()` 改为扫描带 `_tool_def` 属性的方法
- 保留 `AGENT_TOOLS` 常量 deprecated，最终删除

---

## 7. Layer 2b: Span Tracing

### 7.1 问题

- 调试 agent 行为时只有平面日志和 JSONL 记录
- 无法关联 explore → write → evaluate 多阶段
- 无法计算每个工具的耗时占比

### 7.2 设计

```python
# wiki/agents/tracing.py

from __future__ import annotations
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

@dataclass
class Span:
    span_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    parent_id: str | None = None
    name: str = ""
    kind: str = "generic"  # agent_run | generation | tool_call | guardrail | handoff
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    status: str = "running"  # running | completed | error

    @property
    def duration_ms(self) -> float | None:
        if self.end_time is None:
            return None
        return (self.end_time - self.start_time) * 1000


class TraceProcessor(Protocol):
    """Pluggable backend for processing completed spans."""
    def on_span_end(self, span: Span) -> None: ...


class AgentTracer:
    """Hierarchical span tree manager."""

    def __init__(self, group_id: str | None = None, processors: list[TraceProcessor] | None = None):
        self._group_id = group_id or uuid.uuid4().hex[:8]
        self._processors = processors or []
        self._root_span: Span | None = None
        self._current_span: Span | None = None

    @property
    def group_id(self) -> str:
        return self._group_id

    def start_span(self, name: str, kind: str = "generic", **meta) -> Span:
        span = Span(
            name=name,
            kind=kind,
            parent_id=self._current_span.span_id if self._current_span else None,
            metadata={"group_id": self._group_id, **meta},
        )
        if self._root_span is None:
            self._root_span = span
        self._current_span = span
        return span

    def end_span(self, span: Span, *, status: str = "completed", error: str | None = None) -> None:
        span.end_time = time.time()
        span.status = status
        if error:
            span.metadata["error"] = error
        for proc in self._processors:
            proc.on_span_end(span)
        if span.parent_id:
            self._current_span = self._find_span(span.parent_id)
        else:
            self._current_span = None

    def _find_span(self, span_id: str) -> Span | None:
        # Simplified: in production use a stack
        return self._root_span if self._root_span and self._root_span.span_id == span_id else None
```

### 7.3 RunConfig 集成

```python
@dataclass
class RunConfig:
    # ... existing fields ...
    tracer: AgentTracer | None = None
```

### 7.4 自动 Span 创建

`run_tool_loop` 自动创建 span：

```
agent_run (name="explore", kind="agent_run")
├── tool_call (name="query_module_detail", kind="tool_call", duration=120ms)
├── tool_call (name="read_code", kind="tool_call", duration=80ms)
└── tool_call (name="semantic_search", kind="tool_call", duration=200ms)
```

### 7.5 TraceProcessor 实现

- `JsonlTraceProcessor`：写入 `data/traces/` （适配现有 `TraceCollector`）
- `StructlogTraceProcessor`：span 完成时 emit structlog event
- 未来：`OpenTelemetryTraceProcessor`

### 7.6 现有 EventCallback 关系

EventCallback 保留不变（用于 SSE streaming），Tracer 是补充层（用于离线分析和调试）。两者可共存。

---

## 8. Layer 3: Handoff 形式化

### 8.1 问题

`delegate_submodule` 是硬编码的单一委派模式，无法扩展：
- 无类型化输入
- 无历史过滤
- depth/count 限制挂在 agent 实例上

### 8.2 设计

```python
# wiki/agents/handoff.py

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Awaitable
from pydantic import BaseModel

@dataclass
class HandoffConfig:
    """Defines how one agent can hand off to another."""
    target_factory: Callable[..., "GenericAgent"]
    tool_name: str = ""  # exposed to LLM as a tool
    description: str = ""
    input_type: type[BaseModel] | None = None
    input_filter: Callable[[list[dict]], list[dict]] | None = None
    max_depth: int = 2
    max_count: int = 3


class DelegateInput(BaseModel):
    """Default input type for submodule delegation."""
    entity_names: list[str]
    focus: str = ""


@dataclass
class HandoffResult:
    output: str
    metadata: dict[str, Any]
    tool_calls_made: int = 0
```

### 8.3 WikiPageAgent 适配

```python
class WikiPageAgent(GenericAgent):
    handoffs: list[HandoffConfig] = []

    def _register_handoffs(self):
        self.handoffs.append(HandoffConfig(
            target_factory=lambda deps: WikiPageAgent(self._llm, deps),
            tool_name="delegate_submodule",
            description="Delegate exploration of a submodule to a child agent",
            input_type=DelegateInput,
            max_depth=2,
            max_count=3,
        ))
```

### 8.4 RunContext 中的 delegation 状态

```python
@dataclass
class WikiDeps:
    # ...
    delegation_depth: int = 0
    delegation_count: int = 0
```

Handoff 时自动递增 depth，检查 max_depth/max_count。

---

## 9. 文件结构变更

```
wiki/agents/
├── __init__.py          (更新 exports)
├── base_agent.py        (RunConfig, ToolDef, ToolRegistry, GenericAgent)
├── context.py           (NEW: RunContext, WikiDeps)
├── guardrails.py        (NEW: GuardrailResult, InputGuardrail, OutputGuardrail, ToolGuardrail)
├── tool_decorator.py    (NEW: @function_tool)
├── tracing.py           (NEW: Span, TraceProcessor, AgentTracer)
├── handoff.py           (NEW: HandoffConfig, HandoffResult)
├── memory.py            (unchanged)
├── events.py            (unchanged)
├── doc_orchestrator.py  (minor: accept ctx)
├── ask_orchestrator.py  (minor: accept ctx)
├── research_orchestrator.py (minor: accept ctx)
├── edit_agent.py        (migrate to ctx + @function_tool)
├── flow_doc_agent.py    (minor)
├── topic_doc_agent.py   (minor)
├── section_utils.py     (unchanged)
└── turn_compressor.py   (unchanged)
```

---

## 10. 测试策略

每层独立测试：
- **Layer 0**: 测试 RunContext 传递、工具通过 ctx 访问依赖、兼容 shim
- **Layer 1a**: 测试 tripwire 中断、input guardrail 阻止、output guardrail 检测
- **Layer 1b**: 测试 structured output 成功/fallback 路径
- **Layer 2a**: 测试 decorator schema 推断、自动注册
- **Layer 2b**: 测试 span 层次结构、processor 回调
- **Layer 3**: 测试 handoff depth/count 限制、input_filter

---

## 11. Open Questions（审阅后补充）

以下为 sequential-thinking 审阅中识别的实现级细节，不影响整体架构方向，在实现时确认：

1. **@function_tool adapter 层**：decorator 的 handler 签名是独立参数 `(self, name: str, ctx)` 而非 `(args: dict, ctx)`。需在 decorator 内部自动将 `dict args` 解包为函数参数（类似 OpenAI SDK 的 Griffe 方式）。

2. **Tripwire 处理策略**：`run_tool_loop` 遇到 tripwire 时，应返回 `RunResult(memory, status="tripped")` 而非抛异常，让调用方决定如何处理。需定义 `RunResult` 类型。

3. **output_type 与 OutputGuardrail 顺序**：明确执行链为 `generate → structured_parse → output_guardrails → return`。

4. **Tracing 并发安全**：`AgentTracer._current_span` 应使用 `contextvars.ContextVar` 管理，避免并发 agent（如 delegation gather）冲突。

5. **Schema 生成**：`@function_tool` 的 `_build_params_schema` 应使用 Pydantic `TypeAdapter` 自动处理 `Optional`、`list[str]`、默认值等复杂类型。

6. **Handoff factory 签名**：明确 `target_factory: Callable[[WikiDeps], GenericAgent]`，factory 接收新的 deps（已递增 delegation_depth）。

---

## 12. 风险与缓解

| 风险 | 缓解 |
|------|------|
| tool handler 签名变更影响大 | 兼容 shim：旧签名自动适配新协议 |
| 测试量大 | TDD：先写测试再实现 |
| 性能影响 (tracing overhead) | tracer 可选，default None |
| 过度设计 | 每层完成后评估是否继续下一层 |
