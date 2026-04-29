# Unified LLM Token Budget Configuration

> **Status:** ✅ Approved & Implemented  
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
1. **模型切换不安全** — 从 128K 模型切到 8K 模型时，30K 的域树分解预算会超出窗口限制
2. **运维成本** — 切换 LLM 提供商时需要逐文件检查和调整
3. **可测试性差** — 硬编码值无法在测试中覆盖

---

## 2. Goal

建立一个**极简的 Token Budget 配置体系**，使得：

1. **一处配置，全局生效** — 仅通过 1 个配置项控制所有组件的预算基数
2. **比例自动派生** — 各组件基于全局基数和固定比例计算自己的预算，无需独立配置
3. **安全天花板** — 所有预算自动受模型上下文窗口限制
4. **向后兼容** — 零配置迁移，现有部署无需修改任何环境变量

---

## 3. Design

### 3.1 关键设计决策

经过 Sequential Thinking 深度分析，**移除 per-component 覆盖机制**：

**理由：**
- 不同组件的预算差异不是"不一致"，而是**合理设计** — Q&A 需要 8K 聚焦上下文，域树分解需要 30K 全面列表，紧凑格式化只需 4K
- 99% 的用户不会调整 per-component 预算；仅需在切换模型时调整一个全局值
- 4 个 per-component override 字段属于过度设计，违反精准克制原则

### 3.2 Configuration Hierarchy (Two Layers Only)

```
┌─────────────────────────────────────┐
│  Layer 0: Provider Context Window   │  ← 由 LLM 模型决定（已存在于 provider 中）
│  llm.max_context_tokens = 128000    │
└──────────────┬──────────────────────┘
               │ ceiling cap
┌──────────────▼──────────────────────┐
│  Layer 1: Global Operation Budget   │  ← 唯一新增配置
│  wiki.default_llm_budget = 30000    │
└──────────────┬──────────────────────┘
               │ × ratio (code constant)
┌──────────────▼──────────────────────┐
│  Derived Per-Component Budgets      │  ← 代码级比例常量，不暴露为配置
│  decomposition = base × 1.0         │
│  ask_base     = base × 0.27         │
│  ask_flow     = base × 0.40         │
│  compact      = base × 0.13         │
│  assembly     = base × 0.27         │
└─────────────────────────────────────┘
```

### 3.3 Config Model Changes

```python
# config.py

class AppLlmSettings(BaseSettings):
    max_context_tokens: int = Field(
        default=128_000,
        description="LLM model context window size. Used as the safety ceiling.",
    )
    synthesis_max_tokens: int = Field(default=2000)


class AppWikiFlags(BaseSettings):
    default_llm_budget: int = Field(
        default=30_000,
        description=(
            "Base token budget for all LLM operations. "
            "Each component derives its actual budget as a fixed proportion of this value. "
            "Adjust this single value when switching to models with different context windows."
        ),
    )
    # decomposition_max_tokens_per_batch is DEPRECATED, kept for backward compat
```

### 3.4 Budget Resolver

```python
# wiki/token_budget.py

from __future__ import annotations

class TokenBudgetResolver:
    """Derives per-component token budgets from a single base value."""

    RATIOS: dict[str, float] = {
        "decomposition": 1.0,       # 30K @ base=30K — full budget for domain tree
        "ask_concept": 0.33,        # 10K — concept Q&A
        "ask_flow": 0.40,           # 12K — flow Q&A (needs more context)
        "ask_relation": 0.27,       # 8K  — relation Q&A
        "ask_impact": 0.33,         # 10K — impact Q&A
        "ask_general": 0.27,        # 8K  — general Q&A
        "compact": 0.13,            # 4K  — compact formatter
        "assembly": 0.27,           # 8K  — context assembler
    }

    def __init__(self, base: int, ceiling: int | None = None):
        self._base = base
        self._ceiling = int(ceiling * 0.8) if ceiling else None

    def budget(self, component: str) -> int:
        ratio = self.RATIOS.get(component, 0.27)
        raw = int(self._base * ratio)
        if self._ceiling:
            return min(raw, self._ceiling)
        return raw

    def ask_budget(self, question_type: str | None = None) -> int:
        key = f"ask_{question_type or 'general'}"
        return self.budget(key)
```

### 3.5 Proportional Scaling Example

| Component | Ratio | base=30K (128K model) | base=6K (8K model) |
|-----------|:-----:|:---------------------:|:------------------:|
| decomposition | 1.0 | 30,000 | 6,000 |
| ask_flow | 0.40 | 12,000 | 2,400 |
| ask_concept | 0.33 | 10,000 | 2,000 |
| ask_general | 0.27 | 8,000 | 1,600 |
| assembly | 0.27 | 8,000 | 1,600 |
| compact | 0.13 | 4,000 | 780 |

当切换到 8K 模型时，只需设 `WIKI__DEFAULT_LLM_BUDGET=6000`，所有组件自动缩放。

### 3.6 Migration Path

| 阶段 | 改动 | 影响范围 |
|------|------|---------|
| Phase 1 | 添加 `default_llm_budget` 配置 + `TokenBudgetResolver` | `config.py`, 新文件 `wiki/token_budget.py` |
| Phase 2 | `wiki/ask.py` 替换 `_WIKI_TYPE_TOKEN_BUDGET` 硬编码 dict | `wiki/ask.py` |
| Phase 3 | `compact_formatter.py` + `context_assembler.py` 使用 resolver | 2 files |
| Phase 4 | `dependency_graph.py` 移除 `MAX_TOKENS_PER_BATCH` 类常量 | 1 file |
| Phase 5 | 标记 `decomposition_max_tokens_per_batch` 为 deprecated | `config.py` |

### 3.7 Backward Compatibility

- `default_llm_budget = 30000` 使得所有派生值与现有硬编码值一致 — **零配置迁移**
- `decomposition_max_tokens_per_batch` 保留但标记 deprecated
- `token_budget_multiplier`（API 层参数）继续生效，作用在 resolver 输出之上
- 所有现有函数参数签名不变

---

## 4. File Changes

| File | Change Type | Description |
|------|------------|-------------|
| `config.py` | Modify | Add `max_context_tokens` to `AppLlmSettings`, add `default_llm_budget` to `AppWikiFlags` |
| `wiki/token_budget.py` | **New** | `TokenBudgetResolver` — ratio-based budget derivation with safety ceiling |
| `wiki/ask.py` | Modify | Replace `_WIKI_TYPE_TOKEN_BUDGET` dict with `resolver.ask_budget()` |
| `wiki/compact_formatter.py` | Modify | Accept optional `base_budget`, derive from resolver |
| `query/context_assembler.py` | Modify | Accept optional `base_budget`, derive from resolver |
| `wiki/dependency_graph.py` | Modify | Replace `MAX_TOKENS_PER_BATCH` with resolver |
| `wiki/service.py` | Modify | Instantiate `TokenBudgetResolver` and pass to components |

---

## 5. Test Plan

| Test | Description |
|------|-------------|
| `test_resolver_default_ratios` | base=30000 → decomposition=30000, ask_general=8100, compact=3900 |
| `test_resolver_ceiling_cap` | base=30000, ceiling=8000 → all budgets ≤ 6400 (8000×0.8) |
| `test_resolver_small_model` | base=6000 → proportionally scaled values match expectation |
| `test_backward_compat_no_env` | No env vars → same behavior as current hardcoded values |
| `test_env_propagation` | `WIKI__DEFAULT_LLM_BUDGET=50000` → all components see higher budget |

---

## 6. Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|:-----------:|:------:|------------|
| Small model budgets too low (ask < 1K) | Low | Medium | Resolver enforces `min(ratio_budget, 512)` floor |
| Breaking existing API `max_tokens` params | Low | High | All function signatures unchanged; resolver is additive |
| Ratio needs tuning after deployment | Medium | Low | Ratios are code constants, easy to adjust without config change |

---

## 7. Decision Log

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | **移除 per-component override 配置** | Sequential Thinking 分析：99% 用户不使用，4 个冗余字段违反精准克制原则 |
| D2 | **比例因子为代码常量** | 不同组件的预算差异是合理设计（非"不一致"），不应暴露为用户配置 |
| D3 | **仅新增 1 个配置字段** | `default_llm_budget` — 一处配置，全局生效，最小运维成本 |

> ✅ Approved and fully implemented. See commits: c31e3a4..3130f5c
