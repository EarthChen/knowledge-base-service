# LLM Semantic Diagram Generation Pipeline — G-D3 (P0)

> **Status:** 📝 Draft (Awaiting Approval)  
> **Created:** 2026-04-29  
> **Scope:** Backend pipeline (零前端修改)  
> **Estimated Effort:** ~3 days (3 tasks)  
> **Prerequisite:** P1 Batch Fix Sprint (✅ Completed)  
> **Gap Reference:** `wiki-gap-analysis-v3-20260429_191247.md` G-D3

---

## 1. Background

### 1.1 问题

V3 Gap Analysis 确认 **G-D3 是唯一剩余的 P0 差距**，也是对标 DeepWiki 的最大可见差异。

当前系统有 6 种确定性图表（class diagram, dependency graph, call flowchart, layered architecture, module dependency, data flow），均基于 AST 图谱边的结构性生成。Tier-2 system prompt 已引导 LLM 在正文中生成 Mermaid，但缺少**独立的 LLM 语义图表生成步骤**。

DeepWiki 为每个页面生成专门的语义图表（序列图、状态图、数据流图），展示组件间的业务逻辑交互，而非仅仅是调用关系。   

### 1.2 已具备的基础

- `_entity_digest` 已增强：包含 neighbor_tier、结构化参数/返回值、CALLS 边摘要
- `WikiDiagramSection` 前端组件已可渲染任意 `WikiDiagram` 对象
- `MermaidBlock` 已有错误处理（渲染失败时显示占位符）
- `DiagramType` 枚举可扩展

---

## 2. Design

### 2.1 核心思路

新建独立的 `SemanticDiagramGenerator` 模块，集成到现有 `_build_diagrams` 流程中。复用已有的 `entity_digest` 作为 LLM 上下文，不做额外图谱查询。

```
compose_page
  └─ _build_diagrams (async化)
       ├─ 确定性图表 (diagram_gen.py) ← 保持不变
       └─ LLM 语义图表 (semantic_diagram_gen.py) ← 新增
            ├─ _should_generate() → 触发条件判断
            ├─ _build_prompt() → 构建 system + user prompt
            ├─ llm.generate() → 获取 Mermaid 代码
            └─ _validate_and_clean() → 验证 + 清洗
```

### 2.2 图表类型映射

| PageType | 生成的语义图表 | 触发条件 |
|----------|---------------|----------|
| MODULE_OVERVIEW | `sequenceDiagram` (主调用流) | 模块 CALLS 边数 > 3 |
| CLASS_DETAIL | `stateDiagram-v2` 或 `sequenceDiagram` | 方法数 > 2 |
| API_REFERENCE | `sequenceDiagram` (入口调用链) | 函数被标记为 entry point |

### 2.3 智能触发条件

不是每个页面都生成 LLM 图表，仅当满足以下全部条件时触发：
1. `config.mode == "full"` (非 structure 模式)
2. LLM 可用 (`self._llm is not None`)
3. 页面类型匹配 (MODULE/CLASS/FUNCTION)
4. 复杂度阈值 (边数或方法数达标)

### 2.4 LLM Prompt 设计

**System Prompt:**
```
You are a software architecture diagramming expert. Generate valid Mermaid syntax only. 
No markdown fences, no explanatory text. Return ONLY the Mermaid code.
```

**User Prompt (MODULE 示例):**
```
Based on the following module analysis, generate a Mermaid sequence diagram 
showing the main calling flow between this module's key components.

Module: {name}
Business domain: {business_domain}

Key components and their relationships:
{entity_digest}

Generate a sequenceDiagram that shows:
1. The most important calling sequence (pick the primary use case)
2. Use descriptive messages on the arrows
3. Keep to 5-10 participants maximum
4. Use activate/deactivate for key participants

Return ONLY the Mermaid code starting with "sequenceDiagram".
```

### 2.5 Mermaid 验证

```python
VALID_MERMAID_STARTS = frozenset({
    "sequenceDiagram", "stateDiagram-v2", "stateDiagram",
    "flowchart", "graph", "classDiagram",
})

def _validate_and_clean(raw: str) -> str | None:
    text = raw.strip()
    # Strip markdown fences
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    first_line = text.split("\n")[0].strip()
    if not any(first_line.startswith(p) for p in VALID_MERMAID_STARTS):
        return None
    return text
```

### 2.6 成本控制

- 复用 `entity_digest` (~500-1500 tokens input)
- LLM 输出 ~100-300 tokens (纯 Mermaid 代码)
- 每个图表成本 ~$0.001-0.003
- 仅对 CORE/STANDARD 页面触发，典型仓库约 20-50 页
- **每仓库增加成本: ~$0.05-0.15** (可接受)

### 2.7 安全降级

- LLM 调用失败 → 静默跳过，不影响确定性图表
- Mermaid 语法无效 → 验证拦截，不传给前端
- 前端 MermaidBlock 已有 fallback（渲染失败显示 error placeholder）

---

## 3. Tasks

### Task 1: SemanticDiagramGenerator 核心实现 (~1.5天)

**新建** `wiki/semantic_diagram_gen.py`:
- `SemanticDiagramGenerator` 类
- `_should_generate()` 触发条件
- `_build_prompt()` prompt 构建（MODULE/CLASS/FUNCTION 三种模板）
- `_validate_and_clean()` Mermaid 验证清洗
- `_infer_diagram_title()` 从 Mermaid 类型推断标题

**新建** `tests/wiki/test_semantic_diagram_gen.py`:
- test_module_triggers_sequence_diagram
- test_class_triggers_state_or_sequence
- test_small_module_skips (边数不足)
- test_llm_failure_returns_empty
- test_invalid_mermaid_filtered
- test_markdown_fences_stripped

### Task 2: composer.py 集成 (~1天)

**修改** `wiki/composer.py`:
- `_build_diagrams` → `async _build_diagrams`
- 所有调用点添加 `await`
- 在确定性图表后，调用 `SemanticDiagramGenerator.generate()`
- 仅在 mode=full 且 llm 可用时触发

**扩展** `tests/wiki/test_content_depth_enhancement.py`:
- test_build_diagrams_includes_semantic
- test_build_diagrams_no_llm_skips_semantic
- test_build_diagrams_structure_mode_skips

### Task 3: DiagramType 模型扩展 (~0.5天)

**修改** `wiki/models.py`:
- 添加 `DiagramType.SEQUENCE = "sequence"`
- 添加 `DiagramType.STATE = "state"`

---

## 4. Frontend Impact

**零前端修改。** `WikiDiagramSection` 已支持渲染任意 `WikiDiagram` 对象，`MermaidBlock` 支持所有 Mermaid 图表类型。新增的语义图表将自动在页面上方的图表区域显示。

---

## 5. Risk Assessment

| 风险 | 缓解策略 |
|------|---------|
| LLM 生成无效 Mermaid | 第一行验证 + 静默跳过 |
| 额外 LLM 成本 | 仅 CORE/STANDARD + 复杂度阈值 |
| 生成延迟增加 | entity_digest 已有，仅一次轻量 LLM 调用 |
| 前端重复渲染 | 结构化 diagrams 和正文 mermaid 块位置分开 |
| Mermaid 语法错误到达前端 | MermaidBlock 已有 error fallback |

---

## 6. Success Criteria

- MODULE_OVERVIEW 页面出现 sequenceDiagram 类型的语义图表
- CLASS_DETAIL 页面出现 stateDiagram 或 sequenceDiagram
- LLM 失败时页面仍正常显示确定性图表
- 所有现有测试无回归
