# OpenAI Agents SDK 可借鉴模式分析

> **状态**: 分析完成 | **日期**: 2026-05-19  
> **结论**: 不引入 SDK 依赖，选择性借鉴设计模式自行实现

---

## 背景

对 [openai-agents-python](https://github.com/openai/openai-agents-python) 进行深度分析，评估哪些架构模式可提升本项目 Agent 系统质量。

**前置经验**：项目曾尝试 LangGraph + LLM 直调方案，效果差；迁移到自建 Agent 模式（Explore/Write + tiered tools）后显著改善。

---

## 决策：不引入 SDK

| 原因 | 说明 |
|------|------|
| LLM 绑定 | SDK 深度绑定 OpenAI API，项目使用自托管模型 + 自定义 `LLMPort` |
| 执行模型不匹配 | SDK 为单一 ReAct 循环；项目核心是 Explore/Write 两阶段分离 |
| 分层工具激活 | tier 1/2/3 渐进式工具暴露是核心竞争力，SDK 不支持 |
| 侵入性 | 迁移需重写 WikiPageAgent、DomainDocAgent、所有 Orchestrator |
| 依赖锁定 | 受制于 OpenAI SDK 版本节奏和 breaking changes |

---

## 已借鉴模式（6 项，已实现）

| # | 模式 | 实现位置 |
|---|------|---------|
| 1 | Tool Guardrails | `wiki/tool_guardrail.py` → `DefaultToolGuardrail` |
| 2 | Smart Early Stop | `wiki/early_stop.py` → `EarlyStopDetector` |
| 3 | Context Trimming | `wiki/context_manager.py` → `ContextManager` |
| 4 | Structured Output | `wiki/structured_output.py` → `WikiPageOutput` |
| 5 | Output Guardrail | `wiki/output_guardrail.py` → `OutputGuardrailChain` |
| 6 | Quality Trace | `wiki/quality_trace.py` → `TraceCollector` |

---

## 未实施但有借鉴价值的模式（7 项）

### 1. 统一 Runner 抽象 ⭐ (已决定实施)

**SDK 模式**: 单一 `Runner` 类拥有完整的 turn loop、终止规则、流式输出。

**当前差距**: `GenericAgent.run_tool_loop()` 和 `WikiPageAgent.explore()` 是两套实现，防护栏/事件/tier 行为不一致。

**实施方案**: 合并为统一的 `AgentRunner`，保留 tier 分层作为扩展。

### 2. RunContext\<T\> 类型化上下文

**SDK 模式**: `RunContextWrapper[T]` 不发送给 LLM，仅传递给 tools/hooks/guardrails 作为 DI。

**当前状态**: 依赖通过 agent 构造函数注入（`self._graph`, `self._search_service`），与 `WorkingMemory` 边界模糊。

**建议**: 定义 `WikiRunContext` dataclass 清晰分离 DI 上下文与 LLM 可见记忆。优先级中等，可在 Runner 统一后自然引入。

### 3. 三层防护栏 + Tripwire

**SDK 模式**:
- Input guardrail: 链开始前，parallel/blocking 可选
- Tool guardrail: 每次工具调用前后
- Output guardrail: 最终输出检查
- Tripwire: 触发即中断循环

**当前状态**: 有 tool pre/post_call 和 output chain，但无 input 层，无 tripwire 中断语义。

**建议**: 在 Runner 统一后自然引入 input guardrail 和 tripwire。当前优先级低。

### 4. Handoff vs Agent-as-Tool 形式化

**SDK 模式**:
- Handoff: 控制权完全转移给子 agent
- Agent-as-Tool: 主 agent 保持控制，子 agent 返回结果
- 类型化 input_type + input_filter 管理上下文传递

**当前状态**: 仅 `delegate_submodule`（agent-as-tool 模式），无类型化元数据。

**建议**: 当需要引入更多专家 agent 时再形式化。当前优先级低。

### 5. Span 树追踪 + Hooks

**SDK 模式**: `trace()` → `agent_span` → `generation_span` / `function_span`，支持 group_id 关联多阶段。

**当前状态**: 平面 EventCallback + JSONL TraceCollector + structlog，无层次追踪。

**建议**: 如有调试困难再引入。当前优先级低。

### 6. 声明式 output_type

**SDK 模式**: `Agent(output_type=MyModel)` 在定义时声明输出类型。

**当前状态**: `complete_json(schema)` + 手动 fallback。功能上已满足。

**建议**: 可作为 Runner 统一的附带改进。

### 7. @function_tool 装饰器

**SDK 模式**: 从函数签名自动推断 JSON Schema。

**当前状态**: 手写 `AGENT_TOOLS` JSON Schema 列表 (14 个工具)。

**建议**: 可减少维护成本，但 14 个工具已稳定，ROI 有限。

---

## 当前项目独有优势（SDK 不具备）

| 能力 | 说明 |
|------|------|
| 分层工具激活 (Tiered Tools) | Tier 1/2/3 按轮次渐进暴露，减少工具选择过载 |
| Explore/Write 两阶段分离 | Explore 只收集上下文，Write 只负责生成，互不干扰 |
| EarlyStopDetector | 连续空轮自动停止，节省 token |
| Nudge 机制 | 模型过早停止时注入提示继续 |
| ContextManager 裁剪 | 按相关性智能截断过长上下文 |
| 质量迭代循环 | evaluate → re-explore → regenerate |

---

## 行动项

- [x] 分析完成并固化文档
- [ ] **统一 AgentRunner** — 合并 `base_agent.run_tool_loop` 和 `page_agent.explore` 为单一执行引擎
- [ ] (可选) 引入 `WikiRunContext` DI 分离 — Runner 统一后评估
