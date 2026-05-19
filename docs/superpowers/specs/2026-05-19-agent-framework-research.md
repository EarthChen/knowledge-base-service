# Agent Framework Research: OpenAI Agents SDK 替换可行性分析

> Date: 2026-05-19
> Status: Research Complete / Pending Decision

## 1. Background

当前系统的 Agent 实现采用自定义 ReAct 循环（`wiki/agents/base_agent.py` → `GenericAgent`），
配合 LangGraph 进行宏观管线编排。目标是评估 [OpenAI Agents SDK](https://github.com/openai/openai-agents-python) 是否适合替换自定义 Agent 循环。

## 2. 当前架构

```
LangGraph Pipeline (macro)
  ├── classify_domains
  ├── compose_leaf_modules
  ├── compose_domain_agents  ──→  GenericAgent.run_tool_loop() (custom ReAct)
  ├── quality_gate
  └── heal_pages            ──→  GenericAgent.run_tool_loop()
```

### 核心设计模式

- **两阶段模式**：explore（工具收集证据 → WorkingMemory）→ write（无工具，纯 LLM 生成）
- **质量迭代**：explore → write → evaluate → re-explore（循环直至达标）
- **工具分层**：Tier 1/2/3 渐进式暴露（round 1/3/5）
- **LLM 层**：`LLMPort` 协议，通过 `LLMPortBridge` → `GatewayLLMProviderAdapter` → OpenAI 兼容 HTTP

### 关键文件

| File | Role |
|------|------|
| `wiki/agents/base_agent.py` | `GenericAgent`, `ToolDef`, `ToolRegistry`, `run_tool_loop` |
| `wiki/page_agent.py` | `WikiPageAgent` — 14 tools, explore/write/enrich |
| `wiki/domain_doc_agent.py` | Per-domain 质量迭代 |
| `wiki/agents/doc_orchestrator.py` | 模板方法编排器 |
| `wiki/pipeline_graph.py` | LangGraph StateGraph |
| `llm/base_provider.py` | `LLMPortBridge`, `GatewayLLMProviderAdapter` |

## 3. OpenAI Agents SDK 概述

- **仓库**: https://github.com/openai/openai-agents-python (~26k stars)
- **安装**: `pip install openai-agents`
- **核心原语**: Agent + Runner + Tools + Handoffs + Guardrails

### 关键特性

| Feature | Description |
|---------|-------------|
| Agent Loop | 内置工具调用循环，无需自行管理 |
| Function Tools | `@function_tool` 装饰器，自动 schema 生成 |
| MCP Support | stdio/HTTP/SSE 三种传输方式 |
| Multi-Agent | Handoffs（委托）+ Agents-as-tools（子 Agent） |
| Guardrails | 输入/输出验证，可触发拒绝 |
| Tracing | 内置可视化调试 |
| Sessions | 持久化上下文 |
| Model Flexibility | 支持任意 OpenAI 兼容 API |

### 模型兼容性（关键）

```python
from agents import Agent, AsyncOpenAI, OpenAIChatCompletionsModel

client = AsyncOpenAI(api_key="sk-xxx", base_url="http://ai-gateway.momo.com/v1")
model = OpenAIChatCompletionsModel(model="Local-QWen", openai_client=client)

agent = Agent(name="Explorer", model=model, tools=[...])
```

完全支持 QWen 等 OpenAI 兼容模型，无供应商锁定。

## 4. 替换映射

### 4.1 两阶段模式

**方案 A: 两次 Runner.run()（推荐，等价替换）**

```python
explorer = Agent(name="Explorer", tools=[query_module, read_code, ...])
writer = Agent(name="Writer", tools=[])

# Phase 1: Explore
result = await Runner.run(explorer, "Explore module X, output structured findings")
findings = result.final_output

# Phase 2: Write (clean context, no tools)
page = await Runner.run(writer, f"Write wiki page from:\n{findings}")
```

**方案 C: Subagent（SDK-native 风格）**

```python
explorer = Agent(name="Explorer", tools=[query_module, ...])
writer = Agent(
    name="Writer",
    tools=[explorer.as_tool(description="Research code modules")],
)
result = await Runner.run(writer, "Write wiki page for module X")
```

两种方案都保证 explore 阶段的 LLM 中间文本不会泄漏到 write 阶段。

### 4.2 质量迭代循环

```python
for attempt in range(max_iterations):
    explore_result = await Runner.run(explorer, f"Explore: {uncovered_modules}")
    write_result = await Runner.run(writer, f"Write from:\n{explore_result.final_output}")

    quality = evaluate_quality(write_result.final_output, expected_modules)
    if quality.score >= threshold:
        break
    uncovered_modules = quality.uncovered_modules
```

### 4.3 工具注册

```python
from agents import function_tool

@function_tool
async def query_module_detail(module_name: str, graph_name: str) -> str:
    """Query module structure and methods from knowledge graph."""
    result = await graph_store.execute_query(...)
    return json.dumps(result)
```

### 4.4 工具分层

SDK 无原生支持，但可通过 dynamic tool filtering 实现：

```python
def get_tools_for_phase(round_num: int) -> list:
    tools = TIER_1_TOOLS.copy()
    if round_num >= 3:
        tools.extend(TIER_2_TOOLS)
    if round_num >= 5:
        tools.extend(TIER_3_TOOLS)
    return tools
```

或使用 `defer_loading=True`（仅 OpenAI Responses 路径支持）。

## 5. 替换可行性评估

### 可替换部分

| Current | SDK Equivalent | Effort |
|---------|---------------|--------|
| `GenericAgent.run_tool_loop()` | `Runner.run()` | Low |
| `ToolDef` + `ToolRegistry` | `@function_tool` | Low |
| `delegate_submodule` | `Agent.as_tool()` | Low |
| `LLMPort.complete_with_tools()` | SDK 内部管理 | Zero |
| `WorkingMemory` | `result.final_output` + custom state | Medium |

### 不建议替换的部分

| Component | Reason |
|-----------|--------|
| LangGraph Pipeline | 宏观编排与 Agent 循环职责不同；可保留 |
| `LLMPortBridge` | 仍用于非 Agent 场景（RAG、enrichment） |
| Quality evaluation logic | 业务逻辑，与框架无关 |

### 收益

1. 减少 ~200 行自维护 ReAct 循环代码
2. 内置 Tracing 可视化 Agent 行为
3. 内置 Guardrails 保护输出质量
4. 社区维护，bug fix 和优化持续迭代
5. MCP 原生支持简化工具集成

### 风险

1. **新增依赖**：`openai-agents` 依赖 `openai` Python 包，需确认版本不与现有 `openai` 包冲突
2. **Function Calling 兼容性**：QWen 的 function calling 实现可能与 SDK 预期格式有微小差异（如 parallel_tool_calls、tool_call ID 格式），POC 必验
3. **工具分层降级**：SDK 无原生 Tier 机制，需用 prompt 引导或多次 run 模拟；QWen 可能不如 GPT-4 智能地遵循工具优先级指示
4. **前端事件流适配**：当前 ThinkingEvent/ToolCallEvent 格式与 SDK streaming events 格式不同，前端需要适配层
5. **性能开销**：SDK 内置 tracing/schema 验证/guardrail 检查在高并发 wiki 生成时可能增加延迟，需 benchmark
6. **两阶段模式非原生**：需手动编排，SDK 没有 "discard LLM text, keep only tool results" 的内置概念
7. **升级风险**：SDK 处于活跃开发期，API 可能有 breaking changes

## 6. 建议路径

1. **Phase 0（POC 验证）**: 用 SDK 重写一个简单 Agent（如 `WikiEditAgent`），验证 QWen function calling 兼容性和性能开销
2. **Phase 1（新场景试用）**: 在新 Agent 场景（如 `AskOrchestrator`）中正式使用 SDK
3. **Phase 2（核心迁移）**: 验证通过后，将 `WikiPageAgent` 的工具注册和 Agent loop 迁移到 SDK
4. **Phase 3（清理）**: 移除 `GenericAgent`、`ToolRegistry` 等自维护代码

### POC 验证要点

- [ ] QWen function calling 格式完整支持（tool_calls 解析、多 tool 并行）
- [ ] 高并发场景性能 benchmark（50+ 并行 agent 执行）
- [ ] 前端 event stream 适配方案
- [ ] 工具分层的 prompt 引导方案效果评估

## 7. Claude Agent SDK 对比（排除）

| | OpenAI Agents SDK | Claude Agent SDK |
|--|---|---|
| 模型锁定 | ❌ 无锁定 | ⚠️ 仅 Claude |
| OpenAI 兼容 | ✅ | ❌ |
| 自定义工具 | ✅ function_tool + MCP | ✅ MCP |
| 成本 | 灵活 | Anthropic API 计费 |
| 适用性 | ✅ 通用 + 可用现有 LLM | ❌ 不适合本项目 |

**结论**: Claude Agent SDK 不适合本项目（模型锁定）。OpenAI Agents SDK 是可行的渐进式替代方案。

## 8. 深度审阅结论：迁移决策

### 对已有稳定 Agent（WikiPageAgent, DomainDocAgent）：❌ 不建议迁移

理由：
- 当前代码稳定、简单、透明，维护成本低
- 工具分层和结构化记忆是关键业务价值，SDK 无法原生支持
- 迁移后实质是把 SDK 用成一个「工具调用器」，并没有真正利用其 agent loop 智能
- 迁移成本高（重写+测试+回归），收益低

### 对未来新场景：✅ 可以考虑

适合场景：交互式 Q&A Agent、简单工具编排、多 Agent 协作新功能

### 替代优化方案（不换框架，改善现状）

1. 为现有 GenericAgent 添加轻量级 tracing 装饰器
2. 将工具分层逻辑提取为可配置策略
3. 保持现有架构，按需改进

## 9. 可借鉴的模式（提升生成质量）

以下模式可以直接引入当前系统，**不需要**迁移到 SDK：

### 9.1 Structured Output（结构化输出强制）⭐⭐⭐

**来源**: SDK 的 `output_type=PydanticModel`

**应用方式**: 在 write 阶段使用 `response_format={"type": "json_schema", ...}` 强制 LLM 输出符合预定义 schema 的 JSON

```python
class WikiPageOutput(BaseModel):
    title: str
    summary: str
    sections: list[WikiSection]
    code_references: list[CodeRef]
    modules_covered: list[str]
```

**质量提升**:
- 防止 LLM 生成非标准格式的页面
- 强制包含 `modules_covered` 字段，便于自动检测覆盖缺失
- 代码引用结构化后，code_block_verifier 可更精确验证

### 9.2 Tool Guardrails（工具输入/输出护栏）⭐⭐⭐

**来源**: SDK 的 `@tool_input_guardrail` / `@tool_output_guardrail`

**应用方式**: 在 `ToolRegistry.dispatch()` 前后添加验证层

```python
async def validate_tool_output(tool_name: str, result: str) -> str:
    if not result or result == "No results found":
        return "[EMPTY] " + result
    if len(result) > 10000:
        return result[:10000] + "\n[TRUNCATED]"
    return result

async def validate_tool_input(tool_name: str, args: dict) -> dict | None:
    if tool_name == "query_call_chain" and not args.get("method_name"):
        return None  # 拒绝无效调用
    return args
```

**质量提升**:
- 防止空/无效工具结果污染 WorkingMemory
- 截断超大响应防止 context 溢出
- 拒绝无效工具参数，节省无效调用

### 9.3 Agent Improvement Loop（持续改进飞轮）⭐⭐⭐⭐

**来源**: SDK 的 Traces → Feedback → Evals → Optimize 循环

**应用方式**:

```
生成 Wiki 页面 → 记录 trace（工具调用、结果、质量分）
  ↓
收集反馈（用户编辑、质量分、CONTEXT_GAP 计数）
  ↓
生成 eval set（好/坏页面样本）
  ↓
优化 prompt/策略（基于 eval 结果调整探索深度、写作指令）
```

**质量提升**: 最大的潜在收益。当前系统没有系统化的质量改进回路。通过持续收集「什么样的探索策略产出高质量页面」的数据，可以不断优化 prompt 和工具使用策略。

### 9.4 Context Trimming/Compression（上下文压缩）⭐⭐

**来源**: SDK 的 `session_input_callback`

**应用方式**: 在 explore 阶段每轮开始前，压缩早期工具结果

- 保留最近 N 轮完整工具结果
- 将更早的结果压缩为摘要
- 或按信息密度排序，优先保留高价值结果

**质量提升**: 防止大模块探索时 context 溢出导致信息丢失

### 9.5 Output Guardrail（输出质量门控）⭐⭐

**来源**: SDK 的 Output Guardrails

**应用方式**: 将当前分散的 `evaluate_quality()` 逻辑集中化，与 agent 关联

- 格式检查（Markdown 结构、标题层级）
- 覆盖检查（是否覆盖所有预期模块）
- 引用检查（代码块是否有对应源文件）
- 多级检查并行运行

### 9.6 Smart Early Stop（智能提前终止）⭐

**来源**: SDK 的 `max_turns` + 无新信息时自动终止

**应用方式**: 当 Agent 连续 N 轮未获取新信息时提前终止 explore

```python
if consecutive_empty_results >= 2:
    break  # 提前终止探索
```

## 10. 优先级排序

| 优先级 | 借鉴点 | 实现难度 | 质量提升 | 依赖 SDK |
|--------|--------|---------|---------|---------|
| P0 | Agent Improvement Loop | 高 | ⭐⭐⭐⭐ | ❌ 不需要 |
| P1 | Structured Output | 中 | ⭐⭐⭐ | ❌ 不需要 |
| P1 | Tool Guardrails | 低 | ⭐⭐⭐ | ❌ 不需要 |
| P2 | Output Guardrail 集中化 | 低 | ⭐⭐ | ❌ 不需要 |
| P2 | Context Trimming | 中 | ⭐⭐ | ❌ 不需要 |
| P3 | Smart Early Stop | 低 | ⭐ | ❌ 不需要 |

**关键洞察**: 所有可借鉴的模式都**不需要迁移到 SDK**，可以直接在现有 GenericAgent 架构上实现。
