# Unified LLM Token Budget Configuration

> **Status:** Draft — Awaiting Approval  
> **Created:** 2026-04-29  
> **Author:** AI Assistant  
> **Priority:** Medium  

---

## 1. Background

当前项目中 LLM 上下文大小（token budget）的配置分散在 **7+ 个文件**中，存在以下问题：

| 位置 | 配置方式 | 当前值 | 用途 |
|------|---------|--------|------|
| `config.py` (`AppLlmSettings`) | Pydantic Field | 2,000 | `synthesis_max_tokens` — 深度搜索合成输出 |
| `config.py` (`AppWikiFlags`) | Pydantic Field | 30,000 | `decomposition_max_tokens_per_batch` — 域树 LLM 分解 |
| `llm/openai_provider.py` | 构造参数 | 128,000 | `max_context_tokens` — OpenAI 模型窗口 |
| `llm/azure_provider.py` | 构造参数 | 128,000 | `max_context_tokens` — Azure 模型窗口 |
| `llm/custom_provider.py` | 构造参数 | 32,000 | `max_context_tokens` — 自定义模型窗口 |
| `wiki/ask.py` | 硬编码 dict | 8K–12K | `_WIKI_TYPE_TOKEN_BUDGET` — 问答类型预算 |
| `wiki/compact_formatter.py` | 构造参数 | 4,000 | `max_tokens` — 紧凑格式化 |
| `query/context_assembler.py` | 函数参数默认值 | 8,000 | `max_tokens` — 上下文组装 |
| `wiki/dependency_graph.py` | 类常量 | 30,000 | `MAX_TOKENS_PER_BATCH` — 模块表示构建 |

**核心问题：**
1. **不一致风险** — 修改模型上下文窗口后，下游组件仍使用旧的硬编码值
2. **运维成本** — 切换 LLM 提供商时需要逐文件检查和调整
3. **可测试性差** — 硬编码值无法在测试中覆盖

---

## 2. Goal

建立一个**分层的 Token Budget 配置体系**，使得：

1. 模型上下文窗口大小可在 **一处** 配置，自动传播到所有下游组件
2. 各组件可基于全局值计算自己的预算（百分比/比例），而非独立硬编码
3. 保持向后兼容 — 已有的显式配置仍可覆盖推算值

---

## 3. Design

### 3.1 Configuration Hierarchy

```
┌─────────────────────────────────────┐
│  Layer 0: Provider Context Window   │  ← 由 LLM 模型决定
│  llm.max_context_tokens = 128000    │
└──────────────┬──────────────────────┘
               │ derives
┌──────────────▼──────────────────────┐
│  Layer 1: Global Operation Budget   │  ← 全局默认，取 context_window 的比例
│  wiki.default_llm_budget = 30000    │
└──────────────┬──────────────────────┘
               │ inherits (可覆盖)
┌──────────────▼──────────────────────┐
│  Layer 2: Per-Component Override    │  ← 各组件若需不同值可显式覆盖
│  wiki.ask_token_budget = None       │  ← None 表示继承 Layer 1
│  wiki.decomposition_budget = None   │
└─────────────────────────────────────┘
```

### 3.2 Config Model Changes

```python
# config.py

class AppLlmSettings(BaseSettings):
    # Provider context window — the hard limit of the model
    max_context_tokens: int = Field(
        default=128_000,
        description="LLM model context window size. Used as the ceiling for all budget calculations.",
    )
    synthesis_max_tokens: int = Field(default=2000)


class AppWikiFlags(BaseSettings):
    # ─── Layer 1: Global operation budget ───
    default_llm_budget: int = Field(
        default=30_000,
        description=(
            "Default token budget for LLM batch operations (domain decomposition, "
            "module representation, context assembly). "
            "Components inherit this unless explicitly overridden."
        ),
    )

    # ─── Layer 2: Per-component overrides (None = inherit default_llm_budget) ───
    ask_token_budget: int | None = Field(
        default=None,
        description="Token budget for wiki Q&A context. None = use default_llm_budget.",
    )
    decomposition_token_budget: int | None = Field(
        default=None,
        description="Token budget per batch for domain tree LLM decomposition. None = use default_llm_budget.",
    )
    context_assembly_budget: int | None = Field(
        default=None,
        description="Token budget for context assembler. None = use default_llm_budget.",
    )
    compact_format_budget: int | None = Field(
        default=None,
        description="Token budget for compact formatter. None = use default_llm_budget // 8.",
    )
```

### 3.3 Budget Resolution Helper

```python
# config.py or wiki/token_budget.py

class TokenBudgetResolver:
    """Resolves effective token budgets from hierarchical config."""

    def __init__(self, llm_cfg: AppLlmSettings, wiki_cfg: AppWikiFlags):
        self._llm = llm_cfg
        self._wiki = wiki_cfg

    @property
    def context_window(self) -> int:
        return self._llm.max_context_tokens

    @property
    def default_budget(self) -> int:
        return self._wiki.default_llm_budget

    def ask_budget(self, question_type: str | None = None) -> int:
        base = self._wiki.ask_token_budget or self.default_budget
        # Per-type multipliers can still apply
        multipliers = {
            "concept": 1.25, "flow": 1.5, "relation": 1.0,
            "impact": 1.25, "general": 1.0,
        }
        return int(base * multipliers.get(question_type or "general", 1.0))

    def decomposition_budget(self) -> int:
        return self._wiki.decomposition_token_budget or self.default_budget

    def context_assembly_budget(self) -> int:
        return self._wiki.context_assembly_budget or self.default_budget

    def compact_format_budget(self) -> int:
        return self._wiki.compact_format_budget or (self.default_budget // 8)
```

### 3.4 Migration Path

| 阶段 | 改动 | 影响范围 |
|------|------|---------|
| Phase 1 | 添加 `default_llm_budget` + `TokenBudgetResolver` | `config.py`, 新文件 `wiki/token_budget.py` |
| Phase 2 | `wiki/ask.py` 读取 resolver 替代硬编码 | `wiki/ask.py` |
| Phase 3 | `compact_formatter.py` + `context_assembler.py` 读取 resolver | 2 files |
| Phase 4 | `dependency_graph.py` 的 `MAX_TOKENS_PER_BATCH` 替换为 resolver | 1 file |
| Phase 5 | 移除 `decomposition_max_tokens_per_batch` (被 `decomposition_token_budget` 替代) | `config.py` |

### 3.5 Backward Compatibility

- 所有新字段都有合理默认值，无需修改现有环境变量
- `decomposition_max_tokens_per_batch` 在 Phase 5 之前保持，标记 deprecated
- 已有的 `token_budget_multiplier` 参数（API 层）继续生效，在 resolver 输出上应用乘数

---

## 4. File Changes

| File | Change Type | Description |
|------|------------|-------------|
| `config.py` | Modify | Add `max_context_tokens` to `AppLlmSettings`, add `default_llm_budget` + per-component overrides to `AppWikiFlags` |
| `wiki/token_budget.py` | **New** | `TokenBudgetResolver` class |
| `wiki/ask.py` | Modify | Replace `_WIKI_TYPE_TOKEN_BUDGET` dict with resolver call |
| `wiki/compact_formatter.py` | Modify | Accept optional resolver, fallback to constructor param |
| `query/context_assembler.py` | Modify | Accept optional resolver for default budget |
| `wiki/dependency_graph.py` | Modify | Replace `MAX_TOKENS_PER_BATCH` class constant with resolver |
| `wiki/service.py` | Modify | Instantiate `TokenBudgetResolver` and pass to components |

---

## 5. Test Plan

| Test | Description |
|------|-------------|
| `test_budget_resolver_defaults` | Verify resolver returns correct defaults without overrides |
| `test_budget_resolver_overrides` | Verify explicit per-component values take precedence |
| `test_ask_budget_multipliers` | Verify question-type multipliers apply on top of base budget |
| `test_backward_compat_no_env` | Verify zero-config migration: no env vars → same behavior as before |
| `test_env_override_propagation` | Set `WIKI__DEFAULT_LLM_BUDGET=50000` → all components see higher budget |

---

## 6. Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|:-----------:|:------:|------------|
| Budget too high for small models | Low | Medium | `compact_format_budget` auto-scales as `default // 8` |
| Breaking existing API `max_tokens` params | Low | High | Keep all existing function parameters, resolver is additive |
| Config explosion (too many knobs) | Medium | Low | Per-component overrides default to `None` (invisible) |

---

## 7. Decision Log

> Awaiting user approval.
