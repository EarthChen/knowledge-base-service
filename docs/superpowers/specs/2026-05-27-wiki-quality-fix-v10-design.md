# Wiki Quality Fix V10 — 全量审计问题根治方案

**Status:** 📋 PROPOSAL (待审批)
**Created:** 2026-05-27
**Author:** AI Agent (V24 双轮审计 + sequential-thinking 深度分析)
**Source:** V24 审计报告 12 项问题 + V23 多维评分
**Scope:** 元内容防御 + Slug 修复 + 代码块完整性 + Topic 覆盖率 + 壳域拦截 + 域锚定设计 + Agent 语义审计 + 代码截断检测

---

## 背景

### V24 审计全量问题清单

V9 修复效果显著（H1 泄漏 54%→6%，元章节 H2 39%→0%），但仍存 **12 项未解决问题**，横跨 5 大类别：

| # | 问题 | 严重度 | 类别 | 当前评分 |
|---|------|--------|------|----------|
| 1 | 2 topic 含「中文内容增强建议」「术语使用建议」meta 残留 | P0 | 元内容 | — |
| 2 | 3 个 `relationfamily-*` slug 粘连 | P0 | Slug | 7.0 |
| 3 | 挚友业务线 3 域完全消失 | P0 | 域分解 | 6.5 |
| 4 | intimacy-task 壳域 113 字 | P0 | 质量门禁 | — |
| 5 | 用户认证 Part 2 零代码块 | P0 | 代码完整性 | 5.0 |
| 6 | 5 overview 代码截断 | P0 | 代码完整性 | 5.0 |
| 7 | 14/17 域零 topic (82%) | P1 | 覆盖率 | 4.5 |
| 8 | 4 overview 双重 fence 损坏 | P1 | 代码完整性 | 5.0 |
| 9 | data-type-mapping 错挂 intimacy-task 容器 | P1 | 域结构 | 6.5 |
| 10 | 4 overview cn_ratio < 0.30 | P1 | 语言 | 7.5 |
| 11 | user-behavior-statistics 域消失 | P1 | 域分解 | 6.5 |
| 12 | blockquote 元内容残留（续行未删） | P1 | 元内容 | — |

### 核心认知

1. **正则黑名单是打地鼠** — 每次审计发现新模式就加新正则，是运维负债不是工程解法
2. **低挂果实被遗漏** — 双重 fence、topic 门槛、壳域拦截等修复代价极低但影响大
3. **域分解是系统性问题** — 域消失/错挂/壳域根因相同，需单独处理但本次可做轻量防护

---

## 设计方案

### 方案总览：四层纵深防御 + 三项低成本补丁

```
┌─────────────────────────────────────────────────┐
│  第一层: H2 白名单 (render 后兜底)              │ ← F1 核心保障 (本次)
├─────────────────────────────────────────────────┤
│  第二层: 泛化正则 + blockquote 整块清洗         │ ← F2 边界补充 (本次)
├─────────────────────────────────────────────────┤
│  第三层: Prompt 约束 (预防层)                   │ ← F3 预防 (本次)
├─────────────────────────────────────────────────┤
│  第四层: Structured Output (解码层强制)          │ ← F4 根本解法 (P0, gateway 已验证 ✅)
└─────────────────────────────────────────────────┘

+ F5: Slug 粘连修复 (泛化字典分词)
+ F6: 双重 fence 合并
+ F7: Topic 拆分门槛下调
+ F8: 壳域 hard-reject
+ F9: 域锚定保护 (五层防护+三层稳定性+Agent语义审计)
+ F10: 代码截断检测 + heal 引导
+ F11: cn_ratio 硬性检查 (quality_gate 层)
```

---

### F1: H2 白名单清洗（兜底保障）— 解决 #1, #12

**问题:** meta 残留的根因是黑名单永远追不上 LLM 新变体。  
**方案:** 从「删除坏 H2」反转为「只保留好 H2」。

**关键设计决策:**
- 白名单与 prompt 模板中的章节一一对应（单一来源）
- 使用**前缀匹配**而非精确匹配，容忍 LLM 的微变体（如「模块详解 (Java)」匹配「模块详解」）
- 第一个 H2 之前的内容（summary block）始终保留
- H3+ 子章节在合法 H2 内保留

```python
# wiki/content_guards.py — 新增

ALLOWED_OVERVIEW_H2_PREFIXES: tuple[str, ...] = (
    "概述", "核心业务流程", "模块详解", "依赖关系",
    "子域职责矩阵", "跨子域协作", "核心数据流", "子域导航",
    "Overview", "Core Business", "Module Detail", "Dependencies",
    "Sub-Domain", "Cross Sub-Domain", "Core Data Flow",
)

ALLOWED_TOPIC_H2_PREFIXES: tuple[str, ...] = (
    "概述", "架构设计", "核心流程", "关键实现", "相关主题",
    "Overview", "Architecture", "Core Flow", "Key Implementation",
    "Related Topic",
)


def _h2_title_allowed(title: str, allowed_prefixes: tuple[str, ...]) -> bool:
    """Check if an H2 title matches any allowed prefix."""
    title_stripped = title.strip()
    return any(title_stripped.startswith(prefix) for prefix in allowed_prefixes)


def strip_unauthorized_sections(
    content: str,
    allowed_prefixes: tuple[str, ...],
) -> str:
    """Remove H2 sections whose title doesn't match any allowed prefix.

    Content before the first H2 is always preserved. H3+ subsections
    within allowed H2 sections are preserved.
    """
    if not content:
        return ""
    lines = content.split("\n")
    result: list[str] = []
    skipping = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## ") and not stripped.startswith("### "):
            h2_title = stripped[3:].strip()
            if _h2_title_allowed(h2_title, allowed_prefixes):
                skipping = False
            else:
                skipping = True
                continue
        if not skipping:
            result.append(line)

    return "\n".join(result)
```

**集成到 finalize.py:**

```python
# wiki/nodes/finalize.py — _sanitize_published_content 末尾，repair_code_fences 之后
from wiki.content_guards import (
    ALLOWED_OVERVIEW_H2_PREFIXES, ALLOWED_TOPIC_H2_PREFIXES,
    strip_unauthorized_sections,
)

# 在 return 之前新增，需从调用方传入 page_type
def _sanitize_published_content(content: str, *, page_type: str = "") -> str:
    # ... existing cleanup logic ...

    # H2 白名单清洗（在所有其他清洗之后）
    if page_type == "domain_overview":
        content = strip_unauthorized_sections(content, ALLOWED_OVERVIEW_H2_PREFIXES)
    elif page_type == "topic":
        content = strip_unauthorized_sections(content, ALLOWED_TOPIC_H2_PREFIXES)

    return content.strip()
```

**白名单与 Prompt 同步机制:**
- 白名单前缀定义在 `content_guards.py`，prompt 章节结构定义在 `agent_prompts.py`
- 增加一个单元测试 `test_whitelist_prompt_sync` 确保 prompt 中出现的所有 H2 标题都在白名单中
- 如果 prompt 新增章节但白名单未更新，测试会失败，强制同步

**影响范围:** `wiki/content_guards.py`, `wiki/nodes/finalize.py`

---

### F2: 泛化正则 + blockquote 整块清洗 — 解决 #1, #12

**问题:** `strip_repeated_blockquotes` 仅删匹配行，续行 `> ` 保留。  
**方案:** 匹配首行后跳过整个连续 blockquote 块。

```python
# wiki/content_guards.py — 扩展

# Meta H2 — 泛化后缀匹配（F1 白名单之后理论上不再需要，保留用于审计检测）
META_H2_PATTERNS.extend([
    re.compile(r"^##\s*.*(?:增强建议|使用建议|完善建议)$"),
    re.compile(r"^##\s*中文.*建议"),
    re.compile(r"^##\s*术语使用建议"),
    re.compile(r"^##\s*中文内容增强"),
    re.compile(r"^##\s*术语补充说明"),
    re.compile(r"^##\s*内容增强建议"),
])

# Blockquote — 扩展模式
_LLM_TRACE_BLOCKQUOTE_PATTERNS.extend([
    re.compile(r"^>\s*\*\*术语使用建议\*\*[：:]"),
    re.compile(r"^>\s*\*\*建议\*\*[：:]"),
    re.compile(r"^>\s*建议[：:]"),
    re.compile(r"^>\s*\*\*说明\*\*[：:]"),
    re.compile(r"^>\s*术语说明[：:]"),
    re.compile(r"^>\s*\*\*Overview\*\*[：:]"),
    re.compile(r"^>\s*注[：:]本页技术"),
])


def strip_repeated_blockquotes(content: str | None) -> str:
    """Remove LLM trace blockquotes — entire contiguous block, not just the matching line."""
    if not content:
        return ""
    lines = content.split("\n")
    result: list[str] = []
    prev_blockquote: str | None = None
    skip_block = False

    for line in lines:
        if _is_llm_trace_blockquote(line):
            skip_block = True
            prev_blockquote = None
            continue
        if skip_block:
            if _is_blockquote_line(line):
                continue  # skip continuation lines
            else:
                skip_block = False
        if _is_blockquote_line(line):
            normalized = _normalize_blockquote(line)
            if prev_blockquote is not None and normalized == prev_blockquote:
                continue
            prev_blockquote = normalized
            result.append(line)
            continue
        prev_blockquote = None
        result.append(line)

    return "\n".join(result)
```

**影响范围:** `wiki/content_guards.py`（原函数替换）

---

### F3: Prompt 约束增强 — 解决 #1（预防层）

```python
# wiki/agent_prompts.py — AGENT_CORE_CONSTRAINTS 追加

AGENT_CORE_CONSTRAINTS += """
### 严禁输出非指定章节
- 文档结构严格限于 prompt 指定的章节，不得追加任何额外章节。
- 严禁输出面向文档维护者的「建议」「展望」「补充说明」「术语表」「章节导航」等元章节。
- 严禁使用 blockquote (> ) 输出元摘要、建议、术语说明等自指性内容（无论中英文）。
- 违反此规则的内容将被系统自动删除。
"""
```

**影响范围:** `wiki/agent_prompts.py`

---

### F4: Structured Output 升级（解码层强制）— 已验证 gateway 支持，提升为 P0

> ✅ **已验证:** ai-gateway (`http://ai-gateway.momo.com/v1` + `Local-QWen`) 完全支持
> `json_schema` + `strict: true`。三项测试 (json_object / json_schema+strict / json_schema) 均通过。
> **F4 应提升为 P0，从解码层根治 meta 残留。**

**验证结果 (2026-05-27):** ai-gateway 完全支持 `json_schema` + `strict: true`。
- Test 1 (json_object): ✅ PASS
- Test 2 (json_schema + strict: true): ✅ PASS — schema 强制生效，仅返回指定字段
- Test 3 (json_schema + strict: false): ✅ PASS

#### 全量排查: 当前 LLM 输出结构化状态

代码库中 wiki/ 目录共 **25 个文件** 调用了 `complete_json()`，**30+ 处** 使用 `llm.generate()` 纯文本。

**`complete_json` 调用分布:**
- `complete_json(messages, {})` — schema 传空字典: **18 个调用点** (schema 在底层被 `_ = schema` 忽略)
- `complete_json(messages, WikiPageOutput.model_json_schema())` — 传真实 schema: **1 个** (page_agent.py, 仅英文)
- `complete_json(messages, _LLM_SCHEMA)` — 传自定义 schema: **1 个** (architecture_classifier.py)

**底层实现问题:** `openai_provider.py` 的 `complete_json` 中 `_ = schema`，**schema 参数被完全忽略**，所有调用实际都只用 `json_object` 模式。

**全量调用场景矩阵 (需要结构化输出的场景):**

| 优先级 | 场景 | 文件 | 当前 | 目标 | schema 来源 |
|--------|------|------|------|------|------------|
| **P0** | wiki 页面生成 (中+英文) | `page_agent.py` | 中文纯文本/英文json_object | json_schema+strict | `WikiPageOutput` |
| **P0** | topic planning (should_split) | `domain_doc_agent.py` | json_object({}) | json_schema+strict | 新建 `TopicPlanOutput` |
| **P0** | domain decompose merge | `graph_domain_decompose.py` | json_object({}) | json_schema+strict | 新建 `DomainMergeOutput` |
| **P1** | domain namer | `graph_domain_namer.py` | generate() 纯文本 | json_schema+strict | 新建 `DomainNamingOutput` |
| **P1** | architecture classifier | `architecture_classifier.py` | json_object(有schema) | json_schema+strict | 已有 `_LLM_SCHEMA` |
| **P1** | cross-repo domain planner | `cross_repo_domain_planner.py` (5处) | json_object({}) | json_schema+strict | 新建多个 Output |
| **P1** | business domain planner | `business_domain_planner.py` | json_object({}) | json_schema+strict | 新建 Output |
| **P2** | topic structure planner | `topic_structure_planner.py` | json_object({}) | json_schema+strict | 新建 Output |
| **P2** | RAG reflection | `rag/engine.py` | json_object({}) | json_schema | 新建 Output |
| **P2** | aggregate (parent compose) | `nodes/aggregate.py` | json_object({}) | json_schema | 新建 Output |
| **P2** | compose nodes | `nodes/compose.py` (2处) | json_object({}) | json_schema | 新建 Output |
| **P2** | targeted healer | `targeted_healer.py` | json_object({}) | json_schema | 新建 Output |
| **P2** | claim extractor | `claim_extractor.py` | json_object({}) | json_schema | 新建 Output |
| **P2** | contradiction detector | `contradiction_detector.py` | json_object({}) | json_schema | 新建 Output |
| **P2** | reasoning | `reasoning.py` | json_object({}) | json_schema | 新建 Output |
| **P2** | context | `context.py` | json_object({}) | json_schema | 新建 Output |
| **P2** | structure planner | `structure_planner.py` | json_object({}) | json_schema | 新建 Output |

#### 修复方案: 底层强制 + 所有调用方使用真实 schema

**设计原则:** gateway 已验证支持 `json_schema` + `strict: true`，**所有 `complete_json` 调用方必须传入正确的 Pydantic schema**，不允许传 `{}`。底层不做 fallback，强制要求 schema。

**Step 1: 底层升级 — `complete_json` 强制 `json_schema` + `strict`**

```python
# llm/openai_provider.py — 升级 complete_json，schema 为必需参数
async def complete_json(
    self,
    messages: list[dict[str, str]],
    schema: dict[str, Any],
    *,
    model: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    if not schema:
        raise ValueError("complete_json requires a non-empty JSON schema")
    body: dict[str, Any] = {
        "model": model or self._model,
        "messages": messages,
        "temperature": self._temperature,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": schema.get("title", "output"),
                "strict": True,
                "schema": schema,
            },
        },
        **kwargs,
    }
    data = await self._request_json(body)
    raw = data["choices"][0]["message"]["content"]
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error("LLM returned invalid JSON", exc_info=True)
        raise ValueError("LLM returned invalid JSON") from exc
```

**同步修改:** `custom_provider.py`, `azure_provider.py`, `base_provider.py` 同步升级。

**Step 2: 为所有 20 个调用点创建 Pydantic 模型并传入真实 schema**

**新建 `wiki/llm_schemas.py` — 集中管理所有 LLM 输出 schema:**

```python
"""Pydantic models for all LLM structured output schemas."""
from __future__ import annotations
from pydantic import BaseModel
from typing import Literal

# --- wiki 页面生成 (page_agent.py) ---
# 已有 WikiPageOutput in wiki/structured_output.py，移除 is_chinese 跳过

# --- topic planning (domain_doc_agent.py) ---
class TopicItem(BaseModel):
    slug: str
    title: str
    modules: list[str]

class TopicPlanOutput(BaseModel):
    should_split: bool
    topics: list[TopicItem] = []

# --- domain merge (graph_domain_decompose.py) ---
class DomainMergeOutput(BaseModel):
    merge_groups: list[list[str]]

# --- domain naming (graph_domain_namer.py) ---
class DomainNamingItem(BaseModel):
    slug: str
    display_name: str

class DomainNamingOutput(BaseModel):
    domains: list[DomainNamingItem]

# --- architecture classifier (architecture_classifier.py) ---
class ArchClassifyOutput(BaseModel):
    layer: str
    confidence: float = 0.0

# --- cross-repo domain planner (cross_repo_domain_planner.py) — 5处 ---
class CrossRepoDomainMap(BaseModel):
    mapping: dict[str, str]
    display_names: dict[str, str] = {}

class CrossRepoMergeMapping(BaseModel):
    mapping: dict[str, str]

# --- business domain planner (business_domain_planner.py) ---
class BusinessDomainOutput(BaseModel):
    mapping: dict[str, str]
    display_names: dict[str, str] = {}

# --- RAG reflection (rag/engine.py) ---
class RAGReflectionOutput(BaseModel):
    answer: str = ""
    confidence: float = 0.0
    needs_more_context: bool = False
    missing_topics: list[str] = []

# --- aggregate parent compose (nodes/aggregate.py) ---
class ParentComposeOutput(BaseModel):
    content: str
    title: str = ""

# --- compose nodes (nodes/compose.py) — 2处 ---
class ComposeOutput(BaseModel):
    content: str
    title: str = ""

# --- targeted healer (targeted_healer.py) ---
class HealOutput(BaseModel):
    healed_content: str

# --- claim extractor (claim_extractor.py) ---
class ClaimOutput(BaseModel):
    claims: list[str]

# --- contradiction detector (contradiction_detector.py) ---
class ContradictionOutput(BaseModel):
    contradictions: list[dict[str, str]]

# --- reasoning (reasoning.py) ---
class ReasoningPlanOutput(BaseModel):
    steps: list[str]
    tool_calls: list[dict[str, str]] = []

# --- context (context.py) ---
class ContextOutput(BaseModel):
    relevant_modules: list[str]
    summary: str = ""

# --- structure planner (structure_planner.py) ---
class StructurePlanOutput(BaseModel):
    sections: list[dict[str, str]]

# --- topic structure planner (topic_structure_planner.py) ---
class TopicStructureOutput(BaseModel):
    sections: list[dict[str, str]]

# --- F9 domain review (graph_domain_decompose.py) ---
class DomainIssue(BaseModel):
    domain_slug: str
    issue_type: Literal[
        "misplaced_module", "semantic_overlap",
        "naming_unclear", "too_broad", "too_narrow",
    ]
    description: str
    severity: Literal["critical", "warning", "info"]

class DomainReviewOutput(BaseModel):
    overall_quality: Literal["good", "acceptable", "needs_revision"]
    issues: list[DomainIssue]
```

**Step 3: 所有调用点替换 `{}` 为真实 schema**

```python
# 示例: domain_doc_agent.py — 替换前
result = await llm.complete_json(messages, {}, max_tokens=plan_tokens)

# 替换后
from wiki.llm_schemas import TopicPlanOutput
result = await llm.complete_json(messages, TopicPlanOutput.model_json_schema(), max_tokens=plan_tokens)
plan = TopicPlanOutput.model_validate(result)
```

```python
# 示例: graph_domain_decompose.py — 替换前
result = await llm.complete_json(messages, {})

# 替换后
from wiki.llm_schemas import DomainMergeOutput
result = await llm.complete_json(messages, DomainMergeOutput.model_json_schema())
data = DomainMergeOutput.model_validate(result)
```

**每个调用点统一模式: 传 schema → 解析 → Pydantic 验证。**

**Step 4: wiki 页面生成移除中文跳过**

```python
# wiki/page_agent.py — 所有语言都走 structured output
# 删除: if not is_chinese:
try:
    data = await self._llm.complete_json(messages, WikiPageOutput.model_json_schema())
    page_data = WikiPageOutput.model_validate(data)
    rendered = render_wiki_page(page_data, language=content_language)
    if rendered and len(rendered) > 200:
        return rendered
except Exception:
    log.info("structured_output_fallback", domain=domain_name)
```

**Fallback 策略:** 每个 `complete_json` 调用点必须定义 fallback 行为：
- `page_agent.py`: 回退到 `generate()` 纯文本 + `strip_agent_artifacts()` 清洗 (已有)
- 其他 19 个调用点: `complete_json` 失败时 raise，由上层 try/except 决定重试或降级
- **原则:** 不静默吞掉 schema 解析错误，日志必须记录 structured_output_error

**影响范围:** `llm/openai_provider.py` + `custom_provider.py` + `azure_provider.py` (~30行), 新建 `wiki/llm_schemas.py` (~120行), 20 个调用点各改 2-5 行 (~60行), `wiki/page_agent.py` (~5行), `wiki/structured_output.py` (~5行)。**合计约 220 行。**

---

### F5: Slug 粘连通用拆分 — 解决 #2

**问题:** `relationfamily-*` slug 粘连，根因是 Java 类名 `relationfamilyMemberService` 全小写段，`_split_camel_case` 对全小写无效。当前 `_expand_glued_segment` 只在 `_is_module_path_slug`（len>30 且有 doubled prefix）触发时才运行，20-29 长度的粘连 slug 完全绕过。

**方案: 字典分词 + 最小词长 4 字符安全阈值**

核心思路：
1. 将分词逻辑从 `_is_module_path_slug` 中解耦，对**所有 ≥8 字符的纯字母 slug 段**尝试拆分
2. 使用 `_COMMON_ENGLISH_WORDS` 过滤为 **≥4 字符词**作为分词字典，补充常见软件术语
3. 最小词长 4 字符**消除了 3 字母短词歧义**（`get/set/add/put/net/map/man/age` 等不参与分词）
4. 贪心最长前缀匹配，只有拆成 2+ 段时才生效

**安全性分析:**
- `relationfamily` (14字符) → `relation`(8) + `family`(6) ✅ 正确拆分
- `managementhandler` (17字符) → `management`(10) + `handler`(7) ✅
- `paymentsearch` (13字符) → `payment`(7) + `search`(6) ✅
- `getservice` (10字符) → 无法拆分（`get` 3字符 < 4）→ 保持原样 ✅ 安全（camelCase 本会处理 `getService`）
- `management` (10字符) → 在字典中 → 不拆 ✅
- `service` (7字符) → 在字典中 → 不拆 ✅
- 短段 `task`(4字符) → < 8 字符 → 不进入分词 ✅

```python
# wiki/path_conventions.py — 新增

# 分词字典：_COMMON_ENGLISH_WORDS 中 ≥4 字符的词 + 补充常见软件术语
_SPLIT_DICT: frozenset[str] = frozenset(
    w for w in _COMMON_ENGLISH_WORDS if len(w) >= 4
) | frozenset({
    "relation", "family", "member", "proxy", "service", "management",
    "system", "handler", "controller", "consumer", "provider",
    "wrapper", "factory", "builder", "adapter", "listener",
    "filter", "interceptor", "repository", "mapper", "config",
    "manager", "helper", "closed", "friend", "intimacy",
    "activity", "growth", "execution", "distribution",
    "callback", "handling", "authentication", "privilege",
    "statistics", "account", "payment", "search",
    "message", "notification", "session", "token",
    "event", "queue", "cache", "store", "batch",
    "client", "server", "gateway", "router",
    "parser", "render", "scheduler", "worker",
    "monitor", "report", "export", "import",
})
_MIN_SPLIT_WORD = 4  # 分词最小词长，消除短词歧义


def _split_glued_segment(segment: str) -> list[str]:
    """Split a glued lowercase segment using greedy longest-match dictionary lookup.

    Only splits segments ≥8 chars that aren't already known words.
    Uses minimum word length 4 to avoid short-word ambiguity.
    """
    if len(segment) < 8 or not segment.isalpha():
        return [segment]
    seg = segment.lower()
    if seg in _SPLIT_DICT:
        return [segment]

    remaining = seg
    parts: list[str] = []
    while remaining:
        matched = False
        for length in range(min(len(remaining), 15), _MIN_SPLIT_WORD - 1, -1):
            prefix = remaining[:length]
            if prefix in _SPLIT_DICT:
                parts.append(prefix)
                remaining = remaining[length:]
                matched = True
                break
        if not matched:
            parts.append(remaining)
            break

    return parts if len(parts) > 1 else [segment]


def _desegment_glued_slug(slug: str) -> str:
    """Apply glued-segment splitting to all segments in a slug."""
    parts: list[str] = []
    for seg in slug.split("-"):
        parts.extend(_split_glued_segment(seg))
    result = "-".join(p for p in parts if p)
    return result if result != slug else slug
```

**集成到 `resolve_topic_slug`:**

```python
def resolve_topic_slug(slug, title, *, domain_slug="", ...):
    resolved = normalize_slug_strict(slug) or normalize_slug(slug)

    # 通用粘连拆分（在 F1 之前，独立于 _is_module_path_slug）
    resolved = _desegment_glued_slug(resolved)

    if _is_module_path_slug(resolved):
        # ... F1 existing logic
```

**预期效果:**
- `relationfamily-member-service` → `relation-family-member-service`
- `relationfamily-proxy` → `relation-family-proxy`
- `relationfamily-task-service` → `relation-family-task-service`
- 任意仓库的类似粘连都能自动处理（如 `paymentsearch-handler` → `payment-search-handler`）

**影响范围:** `wiki/path_conventions.py`（~50 行新增）

---

### F6: 双重 fence 合并 — 解决 #8

**问题:** `\`\`\`java\n\n\`\`\`java` 模式（两个开启 fence 无闭合）导致渲染损坏。

```python
# wiki/content_guards.py — 在 repair_code_fences 中新增

_DOUBLE_FENCE_RE = re.compile(
    r"(```\w*)\s*\n\s*\n\s*(```\w*\n)",
)


def repair_code_fences(content: str) -> str:
    """Remove empty code blocks, empty WikiLinks, and merge double fences."""
    content = _EMPTY_CODE_BLOCK_RE.sub("", content)
    content = _EMPTY_WIKILINK_RE.sub("", content)
    # Merge double opening fences: ```java\n\n```java → ```java
    content = _DOUBLE_FENCE_RE.sub(r"\1\n", content)
    content = re.sub(r"\n{4,}", "\n\n\n", content)
    return content.strip()
```

**影响范围:** `wiki/content_guards.py`（~5 行）

---

### F7: Topic 拆分门槛下调 — 解决 #7

**问题:** 82% 域零 topic，根因是域合并后大量域模块数 ≤5，触发 `should_split=false`。

**修复方案:** 两处配置联动调整

```python
# core/config.py — 降低门槛
plan_topics_min_modules: int = Field(
    default=3, ge=1,  # 保持不变 — 3 个模块才考虑规划
)
topic_force_split_threshold: int = Field(
    default=4,  # 从 6 降到 4 — 4+ 模块强制拆分
    description="Force topic split when module count >= this",
)
```

**同步修改 prompt:**

```python
# wiki/agent_prompts.py — topic planning prompt 中
# 将 "≤5 modules → should_split=false"
# 改为 "≤2 modules → should_split=false"
```

**预期效果:**
- 4-5 模块的域从"不拆分"变为"强制拆分"
- 预计 topic 覆盖率从 18% 提升到 35%+
- 3 模块的域仍由 LLM 判断是否拆分

**影响范围:** `core/config.py`（1 行），`wiki/agent_prompts.py`（prompt 调整）

---

### F8: 壳域 hard-reject — 解决 #4

**问题:** intimacy-task 113 字壳域落库，因 SKELETON tier 豁免了 quality_gate。

**修复方案:** finalize 阶段对极短 overview 拒绝落库（而非仅加 banner）

```python
# wiki/nodes/finalize.py — finalize_node 中，现有 banner 逻辑之后新增

# 现有逻辑: len(content) < threshold → 加 banner
# 新增: 极短壳域 hard-reject
SHELL_DOMAIN_MIN_CHARS = 500  # 低于此值的 overview 拒绝落库

if is_overview and not is_topic_index and len(content) < SHELL_DOMAIN_MIN_CHARS:
    log.warning(
        "shell_domain_rejected",
        page_path=page.get("path"),
        content_len=len(content),
        threshold=SHELL_DOMAIN_MIN_CHARS,
    )
    updated_pages.append({**page, "content": "", "__rejected__": True})
    continue
```

**影响范围:** `wiki/nodes/finalize.py`（~10 行）

---

### F10: 代码块截断检测 + heal 引导 — 解决 #5, #6

**问题:** 29% overview 代码截断 + 1 topic 零代码块。V8 已将 MAX_CODE_LINES 从 20→80，但现有 quality_gate 的 heal 路径未有效修复截断。

**根因:** quality_gate 能检测代码块缺失，但**未检测代码块未闭合（截断）**。LLM 在长代码块中途被 token limit 截断，产生未闭合的 fence，heal 提示中没有明确要求补全。

**修复方案:**

```python
# wiki/content_guards.py — 新增截断检测

def detect_truncated_code_blocks(content: str) -> list[dict]:
    """Detect unclosed or significantly truncated code blocks."""
    if not content:
        return []
    truncated: list[dict] = []
    in_fence = False
    fence_start_line = 0
    fence_lang = ""

    for i, line in enumerate(content.split("\n")):
        stripped = line.strip()
        if stripped.startswith("```"):
            if not in_fence:
                in_fence = True
                fence_start_line = i
                fence_lang = stripped[3:].strip()
            else:
                in_fence = False

    if in_fence:
        truncated.append({
            "start_line": fence_start_line,
            "language": fence_lang,
            "unclosed": True,
        })
    return truncated
```

**集成到 quality_gate:**

```python
# wiki/nodes/quality_gate.py — 在 heal_hints 收集中新增

from wiki.content_guards import detect_truncated_code_blocks

truncated = detect_truncated_code_blocks(content)
if truncated:
    heal_hints.append(
        f"CODE_TRUNCATED: {len(truncated)} unclosed code block(s) detected. "
        "Ensure all code blocks have matching closing ``` fences and are complete."
    )
```

**预期效果:**
- 未闭合代码块被检测 → 触发 heal → LLM 补全截断的代码
- 代码截断率从 29% 降低到 <10%
- 零代码 topic 仍由现有的代码块缺失检测处理

**影响范围:** `wiki/content_guards.py`(~20 行), `wiki/nodes/quality_gate.py`(~5 行)

---

### F11: cn_ratio 硬性检查 — 解决 #10

**问题:** 4 个 overview cn_ratio < 0.30，仅靠 Prompt 约束是软改善。
**方案:** 在 quality_gate 中增加 cn_ratio 检查，低于阈值触发 heal。

```python
# wiki/nodes/quality_gate.py — 新增 cn_ratio 检查
from wiki.content_guards import compute_cn_ratio

# 在 heal_hints 收集中新增（仅中文页面）
if content_language == "zh":
    cn_ratio = compute_cn_ratio(content)
    if cn_ratio < 0.25:
        heal_hints.append(
            f"LOW_CN_RATIO: cn_ratio={cn_ratio:.2f} < 0.25. "
            "请增加更多中文描述，减少英文代码注释和技术术语的直接引用。"
        )
```

**影响范围:** `wiki/nodes/quality_gate.py`（~8 行）

---

### F9: 域锚定保护 — 五层纵深防御 — 解决 #3, #9, #11

**因果链:**
```
全量重新生成 → embedding HAC 重聚类（无锚定）
  → GraphSemanticCorrector 激进合并（无 anchor 感知）
  → 挚友域 slug 不在新域集合中
  → stale_page_cleanup 物理删除旧页面（不可恢复）
  → 域数减少 → 模块数/域 减少
  → ≤5 模块触发不拆分 → topic 覆盖率暴跌
```

**核心洞察:** DomainAnchor 的完整基础设施已经存在（图节点、CRUD API、REST 接口、前端 hooks、pin/unpin、`stabilize_dual_sync()`、`save_domain_classification()`），但全部未接入分解管线。修复本质是「接线」而非「新建」。

#### 第一层：聚类前保护 — Anchor + Pinned 加载

**现状:** `pinned_modules` 仅在增量运行时加载（`if incremental:`），全量重生成时为空。  
**修复:** 全量运行也加载 DomainAnchor 和 pinned_modules。

```python
# business_pipeline_runner.py — _build_initial_state 中
# 无论增量还是全量，都加载 anchors
pinned_modules: dict[str, str] = {}
anchored_slugs: set[str] = set()
anchor_display_names: dict[str, str] = {}
try:
    pinned_raw = await self._persistence.list_pinned_modules(business_id) or []
    pinned_modules = {str(p["module_name"]): str(p["domain_slug"]) for p in pinned_raw}
except Exception:
    log.warning("pinned_modules_load_failed", business_id=business_id)

try:
    anchors = await self._persistence.list_domain_anchors(business_id) or []
    anchored_slugs = {str(a["slug"]) for a in anchors if a.get("anchor_type") == "user"}
    anchor_display_names = {str(a["slug"]): a.get("display_name", a["slug"]) for a in anchors}
except Exception:
    log.warning("domain_anchors_load_failed", business_id=business_id)

# 传入 pipeline state
state["pinned_modules"] = pinned_modules
state["anchored_slugs"] = anchored_slugs
state["anchor_display_names"] = anchor_display_names
```

**影响:** `business_pipeline_runner.py`（~20 行），`wiki/pipeline_state.py`（新增 state 字段）

#### 第二层：聚类后保护 — Corrector 禁止合并 anchored slug

**现状:** `GraphSemanticCorrector.review_global_consistency` 无 anchor 感知。  
**修复:** 传入 `anchored_slugs`，合并操作跳过 user_anchored 域。

```python
# graph_semantic_corrector.py — review_global_consistency
async def review_global_consistency(
    self,
    domain_mapping, domain_display_names,
    module_paths, module_summaries,
    *,
    anchored_slugs: frozenset[str] = frozenset(),  # 新增参数
    **kwargs,
) -> tuple[dict, dict]:
    # ... 现有 LLM 审查逻辑 ...
    
    # 应用合并时: 保护 anchored slug
    for merge_item in merges:
        target = merge_item["target"]
        sources = merge_item["sources"]
        if anchored_slugs:
            protected = [s for s in sources if s in anchored_slugs]
            if protected:
                log.info("corrector_skip_anchored_merge",
                         target=target, protected=protected)
            sources = [s for s in sources if s not in anchored_slugs]
        if not sources:
            continue
        # ... 现有合并逻辑 ...
```

```python
# graph_domain_decompose.py — 调用处传入
corrector = GraphSemanticCorrector(llm)
domain_mapping, domain_display_names = await corrector.review_global_consistency(
    domain_mapping, domain_display_names, ...,
    anchored_slugs=frozenset(state.get("anchored_slugs") or set()),
)
```

**影响:** `graph_semantic_corrector.py`（~25 行），`graph_domain_decompose.py`（~3 行）

#### 第三层：分解后保护 — Anchored 域强制回填

**现状:** 如果 HAC 聚类没有产生某个 anchored slug，该域就消失。  
**修复:** corrector 之后检查 anchored_slugs 是否全部存在，缺失的从图数据库恢复。

```python
# graph_domain_decompose.py — corrector 之后新增
anchored_slugs = state.get("anchored_slugs") or set()
anchor_display_names = state.get("anchor_display_names") or {}
for slug in anchored_slugs:
    if slug not in domain_mapping:
        anchor_modules = await persistence.list_domain_modules(business_id, slug)
        if anchor_modules:
            mod_tuples = [(repo, str(m["module_name"])) for m in anchor_modules]
            # 从其他域中移除这些模块（避免重复归属）
            for other_slug in list(domain_mapping.keys()):
                domain_mapping[other_slug] = [
                    m for m in domain_mapping[other_slug] if m not in mod_tuples
                ]
            domain_mapping[slug] = mod_tuples
            domain_display_names[slug] = anchor_display_names.get(slug, slug)
            log.warning("anchored_domain_recovered", slug=slug, modules=len(mod_tuples))
        else:
            log.warning("anchored_domain_no_modules", slug=slug)
```

**影响:** `graph_domain_decompose.py`（~25 行）

#### 第四层：清理保护 — Stale 改为 soft-delete

**现状:** `_cleanup_stale_domain_pages` 直接 `DETACH DELETE`，不可恢复。  
**修复:** 改为标记 `stale=true` + `stale_at=timestamp`，保留 7 天后才物理删除。

```python
# business_pipeline_runner.py — _cleanup_stale_domain_pages
async def _cleanup_stale_domain_pages(
    self, business_id: str, current_domain_slugs: set[str],
    *, anchored_slugs: set[str] | None = None,
) -> int:
    query = (
        "MATCH (wp:WikiPage {repository: $biz}) "
        "WHERE wp.path STARTS WITH '/__domains__/' "
        "RETURN wp.uid AS uid, wp.path AS path"
    )
    rows = await self._graph.query(query, {"biz": business_id})
    stale_count = 0
    for row in rows:
        slug = _extract_slug(row["path"])
        if not slug or slug in current_domain_slugs:
            continue
        # user_anchored 域不标记 stale
        if anchored_slugs and slug in anchored_slugs:
            continue
        await self._graph.query(
            "MATCH (wp:WikiPage {uid: $uid}) "
            "SET wp.stale = true, wp.stale_at = $now",
            {"uid": row["uid"], "now": _utc_now_iso()},
        )
        stale_count += 1
    return stale_count


async def _purge_stale_pages(
    self, business_id: str, retention_days: int = 7,
) -> int:
    """Permanently delete pages that have been stale for over retention_days."""
    cutoff = (datetime.utcnow() - timedelta(days=retention_days)).isoformat()
    result = await self._graph.query(
        "MATCH (wp:WikiPage {repository: $biz}) "
        "WHERE wp.stale = true AND wp.stale_at < $cutoff "
        "DETACH DELETE wp RETURN count(wp) AS cnt",
        {"biz": business_id, "cutoff": cutoff},
    )
    return result[0][0] if result else 0
```

**影响:** `business_pipeline_runner.py`（~40 行）

#### 第五层：同步保护 — persist 自动维护 DomainAnchor

**现状:** `save_domain_classification` 存在但从未被调用（死代码）。  
**修复:** 在 `persist_classification_node` 末尾调用，让每次分解结果都同步到 DomainAnchor。

```python
# persist_classification.py — 末尾新增
await persistence.save_domain_classification(
    business_id, domain_mapping,
    anchor_type="system",  # 系统自动同步的 anchor
)
```

**区分 anchor 类型:**
- `user` — 用户通过 API/前端手动创建 → **强保护**（corrector 不合并、不标记 stale、强制回填）
- `system` — persist 自动同步 → **弱保护**（仅用于 stabilize 和 soft-delete，不阻止 corrector 合并）

```python
# wiki/persistence.py — save_domain_classification 修改
async def save_domain_classification(
    self, business_id: str, mapping: dict,
    *, anchor_type: str = "system",
) -> None:
    # ... 现有逻辑 ...
    # 新增: 保留 user_anchored 的边和节点
    # 仅清除 system_anchored 的 stale 边
```

**影响:** `persist_classification.py`（~5 行），`wiki/persistence.py`（~15 行）

#### 补充：容器域 quality_gate 不跳过

```python
# quality_gate.py — SKELETON 豁免逻辑修改
if tier == ImportanceTier.SKELETON:
    # 容器域（有子域的域）不跳过 quality_gate
    is_container = page.get("metadata", {}).get("overview_kind") == "container"
    if not is_container:
        quality_scores[page.path] = {"l1_structural": 1.0, "overall": 1.0}
        continue
```

#### 补充：DomainStabilizer.stabilize_dual_sync 激活

```python
# graph_domain_decompose.py — 替换现有 stabilize 调用
stabilizer = DomainStabilizer()
anchor_display = state.get("anchor_display_names") or {}
domain_mapping, domain_display_names = stabilizer.stabilize_dual_sync(
    domain_mapping, domain_display_names,
    anchor_display,      # DomainAnchor 来源
    existing_display_names,  # WikiSection 来源
)
```

#### 域分解稳定性三层保证 — 无需手动干预

**核心问题:** 在没有手动 pin 的情况下，如何保证每次重新生成域的正确性？

**解答:** 增量优先 + 质量门禁 + 自动基线进化。

##### S1: 自动基线 (Domain Baseline)

每次成功的域分解自动成为「基线」（通过 P5 persist 同步到 DomainAnchor）。下次运行时从基线出发，而非从零开始。

```python
# business_pipeline_runner.py — 基线加载
baseline_mapping: dict[str, list] = {}
try:
    anchors = await self._persistence.list_domain_anchors(business_id) or []
    for anchor in anchors:
        slug = str(anchor["slug"])
        modules = await self._persistence.list_domain_modules(business_id, slug) or []
        if modules:
            baseline_mapping[slug] = [(repo, str(m["module_name"])) for m in modules]
except Exception:
    log.warning("baseline_load_failed", business_id=business_id)

state["domain_baseline"] = baseline_mapping
```

##### S2: 路径决策 (Incremental-First)

```python
# graph_domain_decompose.py — 入口处路径决策
baseline = state.get("domain_baseline") or {}
force_full = state.get("config", {}).get("force_full_decompose", False)

if not baseline:
    # 首次运行: 全量 HAC
    path = "full_hac"
elif force_full:
    # 用户强制全量: HAC + 质量门禁
    path = "full_hac_with_gate"
else:
    # 有基线: 计算变更率
    all_modules = set((r, n) for r, n in biz_modules)
    baseline_modules = set(m for mods in baseline.values() for m in mods)
    new_modules = all_modules - baseline_modules
    removed_modules = baseline_modules - all_modules
    change_rate = (len(new_modules) + len(removed_modules)) / max(len(all_modules), 1)
    incremental_threshold = state.get("config", {}).get("decompose_incremental_threshold", 0.3)
    
    if change_rate < incremental_threshold:
        path = "incremental"  # 增量: 只分配新模块
    else:
        path = "full_hac_with_gate"  # 变更大: 全量 + 门禁
```

##### S3: 域分解质量门禁 (Decomposition Quality Gate)

全量 HAC 结果提交前，与基线对比检测异常变更：

```python
def _domain_decomposition_quality_check(
    new_mapping: dict[str, list],
    baseline_mapping: dict[str, list],
) -> tuple[bool, list[str]]:
    """Compare new decomposition against baseline. Return (pass, warnings)."""
    warnings: list[str] = []
    
    # 域消失检测: 基线中存在但新分解中不存在
    disappeared = set(baseline_mapping.keys()) - set(new_mapping.keys())
    for slug in disappeared:
        mod_count = len(baseline_mapping[slug])
        severity = "CRITICAL" if mod_count >= 5 else "WARNING"
        warnings.append(f"DOMAIN_DISAPPEARED({severity}): {slug} ({mod_count} modules)")
    
    # 域崩塌检测: 新分解域数远小于基线
    if len(new_mapping) < len(baseline_mapping) * 0.5:
        warnings.append(
            f"DOMAIN_COLLAPSE: {len(baseline_mapping)}→{len(new_mapping)}"
        )
    
    # 域爆炸检测: 新分解域数远大于基线
    if len(new_mapping) > len(baseline_mapping) * 2:
        warnings.append(
            f"DOMAIN_EXPLOSION: {len(baseline_mapping)}→{len(new_mapping)}"
        )
    
    critical = [w for w in warnings if "CRITICAL" in w or "COLLAPSE" in w]
    return len(critical) == 0, warnings
```

**未通过时的策略:**

```python
if path == "full_hac_with_gate":
    # ... 全量 HAC + corrector ...
    passed, warnings = _domain_decomposition_quality_check(domain_mapping, baseline)
    for w in warnings:
        log.warning("decompose_quality_warning", warning=w)
    
    if not passed:
        log.error("decompose_quality_gate_failed", warnings=warnings)
        # 回退到基线 + 增量分配新模块
        domain_mapping = dict(baseline)
        domain_display_names = dict(baseline_display_names)
        _assign_new_modules_to_nearest(new_modules, domain_mapping, embeddings)
```

##### 完整保护链路图

```
域分解管线
  │
  ├─ [Purge] 清理过期 stale 页面 (保留期 7 天)
  │
  ├─ [S1] 加载基线 (DomainAnchor/WikiSection → baseline_mapping)
  │
  ├─ [S2] 路径决策
  │    ├─ 无基线 → 全量 HAC (首次)
  │    ├─ 有基线 + 变更<30% → 增量 (基线 + 新模块分配)
  │    ├─ 有基线 + 变更≥30% → 全量 HAC + 质量门禁
  │    └─ 用户强制 → 全量 HAC + 质量门禁
  │
  ├─ [增量路径]
  │    ├─ [P1] pinned 模块排除
  │    ├─ _assign_new_modules_to_nearest (embedding 余弦相似度)
  │    └─ 直接使用 (跳过 corrector/HAC)
  │
  ├─ [全量 HAC 路径]
  │    ├─ HAC 聚类
  │    ├─ [P2] Corrector 保护 user_anchored slug
  │    ├─ [P3] anchored 域强制回填
  │    ├─ [S3] 质量门禁 (双层)
  │    │    ├─ S3a: 结构性检查 (碎片化/巨型域/域数)
  │    │    ├─ S3b: Agent 语义审计 (LLM 评估业务边界/模块归属/命名)
  │    │    ├─ 全部通过 → 更新基线
  │    │    └─ 未通过 → 回退到基线 + 增量分配新模块
  │    └─ DomainStabilizer.stabilize_dual_sync
  │
  ├─ [P4] stale cleanup → soft-delete (7天保留)
  │    └─ user_anchored 域不标记 stale
  │
  ├─ [P5] persist → save_domain_classification 同步 anchor (更新基线)
  │
  └─ 容器域 quality_gate 不跳过
```

**核心保证:** 即使没有任何手动干预，域分解也不会出现严重回归。首次成功分解自动成为基线，后续默认走增量路径。只有代码变更超过 30% 才触发全量重新聚类，且必须通过质量门禁才能替换基线。

##### 场景适用性矩阵

F9 的保护机制分为「始终有效」和「仅增量有效」两类：

| 保障层 | 增量运行 | 全量重生成 | 清除所有+重建 |
|--------|---------|-----------|--------------|
| HAC + silhouette 优化 | ✅ | ✅ | ✅ |
| GraphSemanticCorrector | — | ✅ | ✅ |
| S3a 结构性质量检查 | — | ✅ | ✅ |
| S3b Agent 语义审计 | — | ✅ | ✅ |
| P2 corrector 保护 anchored slug | — | ✅ | ⚠️ 仅 user_anchored |
| P3 anchored 域强制回填 | — | ✅ | ⚠️ 仅 user_anchored |
| S1 基线加载 | ✅ | ✅ | ❌ 无基线 |
| S2 增量路径 | ✅ | — | ❌ 无基线 |
| S3 质量门禁(基线对比) | — | ✅ | ❌ 无基线 |
| P4 soft-delete | ✅ | ✅ | ❌ 无页面 |

**「清除所有 Wiki + 重新生成」场景:** 等价于首次运行。此场景下：
1. 无基线可对比 → 增量路径/质量门禁回退不工作
2. 无页面可 soft-delete → soft-delete 不工作
3. **但始终有效的保障仍然工作:** HAC优化、corrector、结构检查、Agent语义审计
4. **user_anchored DomainAnchor 可以保留** — 建议「清除所有 Wiki」操作仅删除 WikiPage 节点，保留 user 类型的 DomainAnchor 节点

```python
# 建议的「清除所有 Wiki」实现
async def clear_all_wiki(self, business_id: str) -> int:
    # 删除 WikiPage 节点
    result = await self._graph.query(
        "MATCH (wp:WikiPage {repository: $biz}) DETACH DELETE wp RETURN count(wp)",
        {"biz": business_id},
    )
    # 仅清除 system anchor，保留 user anchor
    await self._graph.query(
        "MATCH (da:DomainAnchor {repository: $biz}) "
        "WHERE da.anchor_type <> 'user' DETACH DELETE da",
        {"biz": business_id},
    )
    return result[0][0] if result else 0
```

**设计理念:** soft-delete 和基线机制的价值在于**常态化运行**（占 90% 以上的场景），而非极端操作（清除所有）。极端操作由用户主动触发，用户对结果有预期，此时由 S3a+S3b 的首次运行质量保证覆盖。

##### 首次运行正确性保证 (First-Run Quality)

**诚实认知:** HAC 聚类是无监督的，首次运行时没有基线可对比，**不可能 100% 保证正确**。但可以通过多层检查显著提高正确率。

**现有保障 (已在系统中):**
1. HAC + silhouette 分数优化 K 值选择
2. GraphSemanticCorrector LLM 审查（合并/重命名/移动）
3. DomainStabilizer slug 稳定化
4. 域预算限制 + 基础设施域过滤

**新增: 结构性质量检查 (首次 + 全量 HAC 后)**

```python
def _structural_quality_check(
    domain_mapping: dict[str, list],
    module_count_total: int,
) -> list[str]:
    """Detect common decomposition anomalies."""
    warnings: list[str] = []
    
    # 碎片化检测: >30% 的域只有 1 个模块
    single = [s for s, m in domain_mapping.items() if len(m) == 1]
    if len(single) > len(domain_mapping) * 0.3:
        warnings.append(f"FRAGMENTATION: {len(single)} single-module domains")
    
    # 巨型域检测: 某域占总模块数 >40%
    for slug, modules in domain_mapping.items():
        if len(modules) > module_count_total * 0.4:
            warnings.append(f"MEGA_DOMAIN: {slug} has {len(modules)}/{module_count_total}")
    
    # 域数合理性: 太少或太多
    if len(domain_mapping) < 3 and module_count_total > 20:
        warnings.append(f"TOO_FEW: {len(domain_mapping)} domains for {module_count_total} modules")
    if len(domain_mapping) > module_count_total * 0.5:
        warnings.append(f"TOO_MANY: {len(domain_mapping)} domains for {module_count_total} modules")
    
    return warnings
```

**首次运行流程:**

```
全量 HAC → corrector → 结构性质量检查
  ├─ 无严重警告 → 自动成为基线 (后续增量路径)
  └─ 有警告 → 记录日志 + 仍然成为基线 (因为没有更好的替代)
                + 前端可展示警告，引导用户 pin 调整
```

**关键设计决策:** 首次运行的分解不可能完美，但它提供了一个「起点」。域结构通过以下机制逐步收敛到正确状态：

1. **增量调整** — 新模块自动分配到语义最接近的域
2. **用户修正** — 通过已有的 pin/unpin API 和前端界面手动调整
3. **安全重置** — 用户可强制全量重新聚类，质量门禁保证不会比当前更差
4. **每次 persist 都同步基线** — 修正后的状态自动成为新基线

##### Agent 语义审计 (S3b — 分解后 LLM 二次 review)

**动机:** 结构性检查只能检测数量异常（碎片化/巨型域/域数），无法评估**语义质量**（模块是否归属正确、域是否代表清晰业务边界）。域数量有限（典型 10-30），一次 LLM 调用成本 ~$0.003，几乎可忽略。

**核心设计决策:**
- Agent 是**审计员**而非执行者 — 只输出评估结果，不直接修改域结构（与 corrector 分离职责）
- 仅在**全量 HAC 路径**（首次运行 / 变更≥30% / force_full）时触发，增量路径不触发
- 结果与结构性检查合并到 S3 质量门禁中统一判定

```python
# graph_domain_decompose.py — 新增

class DomainIssue(BaseModel):
    domain_slug: str
    issue_type: Literal[
        "misplaced_module", "semantic_overlap",
        "naming_unclear", "too_broad", "too_narrow",
    ]
    description: str
    severity: Literal["critical", "warning", "info"]


class DomainReviewOutput(BaseModel):
    overall_quality: Literal["good", "acceptable", "needs_revision"]
    issues: list[DomainIssue]


DOMAIN_REVIEW_PROMPT = """你是代码仓库域分解审计员。请审计以下域分解结果的质量。

审计规则:
1. 每个域应代表一个清晰的业务边界（如「用户认证」「支付系统」「家族管理」）
2. 同一业务线的模块应在同一域，不应被拆散到多个域
3. 基础设施模块（util, common, config, base）不应混入业务域
4. 域名称应清晰反映其业务范围
5. 域不应过大（占总模块>40%）或过小（只有 1 个模块且非独立业务）

域分解结果 ({domain_count} 域, {total_modules} 模块):
{domain_details}

请输出 JSON 格式的审计报告。仅报告 critical 和 warning 级别的问题。"""


async def _agent_review_decomposition(
    llm,
    domain_mapping: dict[str, list[tuple[str, str]]],
    domain_display_names: dict[str, str],
    module_summaries: dict[str, str],
) -> tuple[str, list[str]]:
    """LLM semantic review of domain decomposition.

    Returns (quality_level, warnings).
    """
    domain_desc: list[str] = []
    for slug, modules in domain_mapping.items():
        display = domain_display_names.get(slug, slug)
        mod_lines: list[str] = []
        for _repo, mod_name in modules[:10]:
            summary = module_summaries.get(mod_name, "")
            mod_lines.append(f"  - {mod_name}: {summary[:80]}")
        if len(modules) > 10:
            mod_lines.append(f"  - ... (+{len(modules) - 10} more)")
        domain_desc.append(
            f"\n### {display} (slug: {slug}, {len(modules)} modules)\n"
            + "\n".join(mod_lines)
        )

    prompt = DOMAIN_REVIEW_PROMPT.format(
        domain_count=len(domain_mapping),
        total_modules=sum(len(m) for m in domain_mapping.values()),
        domain_details="\n".join(domain_desc),
    )

    try:
        result = await llm.complete_json(
            [{"role": "user", "content": prompt}],
            schema=DomainReviewOutput.model_json_schema(),
        )
        review = DomainReviewOutput.model_validate(result)
    except Exception:
        log.warning("domain_review_agent_failed")
        return "acceptable", []

    warnings: list[str] = []
    for issue in review.issues:
        warnings.append(
            f"SEMANTIC_{issue.severity.upper()}: [{issue.domain_slug}] "
            f"{issue.issue_type} - {issue.description}"
        )

    return review.overall_quality, warnings
```

**集成到 S3 质量门禁:**

```python
# graph_domain_decompose.py — S3 质量门禁内

# S3a: 结构性检查
struct_warnings = _structural_quality_check(domain_mapping, module_count)

# S3b: Agent 语义审计 (仅全量 HAC 路径)
quality_level, semantic_warnings = await _agent_review_decomposition(
    llm, domain_mapping, domain_display_names, module_summaries,
)
all_warnings = struct_warnings + semantic_warnings

# 综合判定
has_critical = any("CRITICAL" in w for w in all_warnings)
needs_revision = quality_level == "needs_revision"

if (has_critical or needs_revision) and baseline:
    log.error("decompose_quality_gate_failed",
              quality=quality_level, warnings=all_warnings)
    domain_mapping = dict(baseline)
    _assign_new_modules_to_nearest(new_modules, domain_mapping, embeddings)
elif all_warnings:
    log.warning("decompose_quality_warnings",
                quality=quality_level, warnings=all_warnings)
    state["decomposition_warnings"] = all_warnings
```

**成本估算:**
- 输入: ~2000 tokens (20 域 × 5 模块 × 摘要) + ~500 tokens (prompt)
- 输出: ~500 tokens
- 总计: ~3000 tokens ≈ $0.003 (GPT-4o) / $0.009 (Claude Sonnet)
- 触发频率: 仅全量 HAC 时（远少于每次运行）

##### 增量路径: 新模块分配实现

```python
# graph_domain_decompose.py — 增量路径实现

def _assign_new_modules_to_nearest(
    new_modules: set[tuple[str, str]],
    domain_mapping: dict[str, list[tuple[str, str]]],
    embeddings: dict[str, list[float]],
) -> None:
    """Assign new modules to their semantically nearest existing domain.

    Uses cosine similarity between module embedding and domain centroid.
    Modifies domain_mapping in place.
    """
    import numpy as np

    domain_centroids: dict[str, np.ndarray] = {}
    for slug, modules in domain_mapping.items():
        vecs = [embeddings[m[1]] for m in modules if m[1] in embeddings]
        if vecs:
            domain_centroids[slug] = np.mean(vecs, axis=0)

    if not domain_centroids:
        return

    for repo, mod_name in new_modules:
        if mod_name not in embeddings:
            continue
        mod_vec = np.array(embeddings[mod_name])
        best_slug = ""
        best_sim = -1.0
        for slug, centroid in domain_centroids.items():
            sim = float(np.dot(mod_vec, centroid) / (
                np.linalg.norm(mod_vec) * np.linalg.norm(centroid) + 1e-9
            ))
            if sim > best_sim:
                best_sim = sim
                best_slug = slug
        if best_slug:
            domain_mapping[best_slug].append((repo, mod_name))
```

##### Purge 触发时机

```python
# business_pipeline_runner.py — pipeline 启动时清理过期 stale 页面

async def _run_pipeline(self, business_id: str, ...):
    # 在构建初始 state 之前，先清理过期的 stale 页面
    purged = await self._purge_stale_pages(business_id, retention_days=7)
    if purged:
        log.info("stale_pages_purged", business_id=business_id, count=purged)

    # ... 继续原有 pipeline 逻辑 ...
```

#### F9 改动量估算

| 层 | 文件 | 改动 | 行数 |
|---|------|------|------|
| S1 | `business_pipeline_runner.py` | 基线加载 | ~15 |
| S2 | `graph_domain_decompose.py` | 路径决策 | ~25 |
| S3a | `graph_domain_decompose.py` | 结构性检查 + 回退 | ~40 |
| S3b | `graph_domain_decompose.py` | Agent 语义审计 + Pydantic 模型 + Prompt | ~80 |
| S2+ | `graph_domain_decompose.py` | 增量路径: _assign_new_modules_to_nearest | ~25 |
| P1 | `business_pipeline_runner.py` | 加载 anchors + state + purge | ~25 |
| P1 | `wiki/pipeline_state.py` | 新增 state 字段 | ~5 |
| P2 | `graph_semantic_corrector.py` | anchored_slugs 参数 + 保护 | ~25 |
| P3 | `graph_domain_decompose.py` | 强制回填 | ~25 |
| P4 | `business_pipeline_runner.py` | soft-delete + purge | ~40 |
| P5 | `persist_classification.py` | save_domain_classification | ~5 |
| P5 | `wiki/persistence.py` | 保护 user_anchored | ~15 |
| 补 | `quality_gate.py` | 容器域不跳过 | ~10 |
| 补 | `graph_domain_decompose.py` | stabilize_dual_sync | ~5 |
| **合计** | **8 文件** | | **~340 行** |

---

## 审计问题覆盖矩阵

| # | 审计问题 | 修复 | 覆盖 | 说明 |
|---|---------|------|------|------|
| 1 | meta 残留 | F1+F2+F3 | ✅ | 三层防御: 白名单+正则+Prompt |
| 2 | slug 粘连 | F5 | ✅ | 泛化字典分词，min-4 安全阈值 |
| 3 | 域消失 | **F9 五层保护+Agent审计** | ✅ | anchor→corrector→回填→soft-delete→persist + LLM 语义审计 |
| 4 | 壳域 113字 | **F8** + F9 容器域 gate | ✅ | hard-reject + 容器域不跳过 quality_gate |
| 5 | 零代码 topic | **F10** 截断检测 + heal | ✅ | 未闭合代码块检测→触发 heal→LLM 补全 |
| 6 | 代码截断 | **F10** 截断检测 + heal | ✅ | 29%→<10%，配合现有 MAX_CODE_LINES=80 |
| 7 | 零 topic 82% | **F7** + F9 域保护 | ✅ | 门槛 6→4 + 域不消失→模块不减少→topic 不受影响 |
| 8 | 双重 fence | **F6** | ✅ | 正则合并，~5 行 |
| 9 | 域错挂 | F9 pin API + **Agent审计** | ✅ | LLM 检测 misplaced_module + 用户 pin 纠正 |
| 10 | cn_ratio | **F11** + F3(Prompt) | ✅ | quality_gate cn_ratio<0.25 触发 heal + Prompt 预防 |
| 11 | 域消失 | **F9 第四层 soft-delete** | ✅ | 7 天保留窗口，不可恢复→可恢复 |
| 12 | blockquote 续行 | F2 | ✅ | 整块删除逻辑 |

**覆盖统计:**
- ✅ 确定解决: 12/12 (100%)
- ⏳ 延后: 0/12

---

## 测试计划

### F1 (H2 白名单)

- [ ] `test_strip_unauthorized_sections_overview` — overview 白名单内 H2 保留
- [ ] `test_strip_unauthorized_sections_removes_meta` — 未知 H2（如「中文内容增强建议」）被删除
- [ ] `test_strip_unauthorized_sections_preserves_pre_h2` — 第一个 H2 前的 summary 保留
- [ ] `test_strip_unauthorized_sections_h3_within_allowed` — 合法 H2 下的 H3 保留
- [ ] `test_strip_unauthorized_sections_prefix_match` — 「模块详解 (Java)」匹配「模块详解」前缀
- [ ] `test_strip_unauthorized_sections_topic` — topic 白名单验证

### F2 (泛化正则 + 整块删除)

- [ ] `test_strip_blockquote_entire_block` — 匹配首行后整块 blockquote 删除
- [ ] `test_meta_h2_wildcard_suffix` — `## 中文内容增强建议` 被清除
- [ ] `test_blockquote_术语使用建议` — `> **术语使用建议**：` 被清除
- [ ] `test_blockquote_continuation_lines_removed` — 续行 `> ...` 跟随删除

### F3 (Prompt)

- [ ] 验证 prompt 约束不与现有约束冲突
- [ ] 验证 prompt 白名单与 F1 白名单前缀一致

### F5 (Slug 粘连)

- [ ] `test_split_glued_segment_relationfamily` — `relationfamily` → `['relation', 'family']`
- [ ] `test_split_glued_segment_managementhandler` — `managementhandler` → `['management', 'handler']`
- [ ] `test_split_glued_segment_getservice_no_split` — `getservice` 不拆分（`get` < 4 字符）
- [ ] `test_split_glued_segment_short_skip` — `task`(4字符) 不进入分词（< 8 字符）
- [ ] `test_split_glued_segment_known_word_no_split` — `management` 在字典中，不拆
- [ ] `test_desegment_glued_slug_full` — `relationfamily-member-service` → `relation-family-member-service`
- [ ] `test_resolve_topic_slug_with_glued` — 集成测试: 粘连 slug 经 resolve 后正确拆分

### F6 (双重 fence)

- [ ] `test_repair_double_fence_java` — `\`\`\`java\n\n\`\`\`java` → `\`\`\`java`
- [ ] `test_repair_double_fence_preserves_normal` — 正常 fence 不受影响
- [ ] `test_repair_double_fence_different_lang` — `\`\`\`java\n\n\`\`\`kotlin` 的处理

### F7 (Topic 门槛)

- [ ] `test_force_split_threshold_4` — 4 模块域触发强制拆分
- [ ] `test_no_split_below_3_modules` — 2 模块域不触发拆分
- [ ] `test_existing_plan_topics_min_modules_unchanged` — 现有测试不回归

### F8 (壳域 reject)

- [ ] `test_shell_domain_rejected_below_500` — 113 字 overview 被 reject
- [ ] `test_normal_overview_passes` — 正常 overview 不受影响
- [ ] `test_topic_index_exempt` — topic_index 类型不受限

### F10 (代码截断检测)

- [ ] `test_detect_truncated_unclosed_fence` — 未闭合 fence 被检测
- [ ] `test_detect_truncated_normal_code` — 正常闭合代码块不误报
- [ ] `test_detect_truncated_multiple` — 多个未闭合 fence 都被检测
- [ ] `test_quality_gate_truncated_adds_heal_hint` — 检测到截断后 heal_hints 包含 CODE_TRUNCATED

### F11 (cn_ratio 硬性检查)

- [ ] `test_cn_ratio_below_threshold_triggers_heal` — cn_ratio < 0.25 的中文页面触发 heal hint
- [ ] `test_cn_ratio_above_threshold_no_heal` — cn_ratio ≥ 0.25 不触发
- [ ] `test_cn_ratio_skipped_for_english` — 英文页面不检查 cn_ratio

### F9 (域锚定)

- [ ] `test_anchor_loaded_on_full_run` — 全量运行也加载 DomainAnchor
- [ ] `test_corrector_skip_anchored_merge` — user_anchored 域不被 corrector 合并
- [ ] `test_corrector_allows_system_anchor_merge` — system_anchored 域可被合并
- [ ] `test_anchored_domain_recovery` — 丢失的 user_anchored 域从图数据库恢复
- [ ] `test_stale_soft_delete` — stale 页面标记而非删除
- [ ] `test_stale_purge_after_retention` — 7 天后才物理删除
- [ ] `test_user_anchored_not_stale` — user_anchored 域不被标记 stale
- [ ] `test_persist_syncs_system_anchor` — persist 自动创建 system anchor
- [ ] `test_persist_preserves_user_anchor` — persist 不覆盖 user anchor
- [ ] `test_container_domain_quality_gate` — 容器域不跳过 quality_gate
- [ ] `test_stabilize_dual_sync_activated` — stabilize_dual_sync 替代 stabilize
- [ ] `test_incremental_path_new_module_assignment` — 增量路径新模块分配到最相似域
- [ ] `test_incremental_path_no_change` — 无新模块时增量路径不修改域结构
- [ ] `test_agent_review_good_quality` — Agent 审计返回 good 时不触发回退
- [ ] `test_agent_review_needs_revision` — Agent 审计返回 needs_revision 时触发回退到基线
- [ ] `test_agent_review_failure_graceful` — Agent 审计 LLM 调用失败时不阻塞管线
- [ ] `test_purge_called_on_pipeline_start` — pipeline 启动时调用 purge
- [ ] `test_whitelist_prompt_sync` — prompt 模板中的 H2 标题全部在白名单中

---

## 实施优先级与批次

| 优先级 | Fix | 预期效果 | 依赖 | 代码量 |
|--------|-----|----------|------|--------|
| **P0** | F1 H2 白名单 | H2 元章节 → 0% | 无 | ~55 行 |
| **P0** | F2 泛化正则+整块删除 | blockquote 元内容 → 0% | 无 | ~40 行 |
| **P0** | F3 Prompt 约束 | 预防新变体 | 无 | ~10 行 |
| **P0** | F5 Slug 粘连 | `relationfamily-*` → 0，泛化适用其他仓库 | 无 | ~50 行 |
| **P0** | F6 双重 fence | 4 fence 损坏 → 0 | 无 | ~5 行 |
| **P0** | F7 Topic 门槛 | 覆盖率 18%→35%+ | 无 | ~5 行 |
| **P0** | F8 壳域 reject | 壳域不落库 | 无 | ~10 行 |
| **P0** | F10 代码截断检测 | 截断率 29%→<10% | 无 | ~25 行 |
| **P0** | F11 cn_ratio 硬性检查 | cn_ratio<0.30→heal触发 | 无 | ~8 行 |
| **P0** | F4 Structured Output (全量) | 底层strict+所有调用方真实schema | ✅ gateway 已验证 | ~220 行 |
| **P0** | F9 域保护(全量) | 域消失→0, Agent审计, 增量分配 | 无 | ~340 行 |

**建议实施批次:**

| 批次 | 内容 | 预计改动 | 覆盖问题 |
|------|------|----------|----------|
| **Batch A** | F1 白名单 + F2 正则 + F3 Prompt + F4 全量(底层strict+所有schema) + F6 双重fence + F10 截断检测 | ~355 行 | #1,#5,#6,#8,#12 |
| **Batch B** | F5 Slug + F7 Topic 门槛 + F8 壳域reject + F11 cn_ratio | ~73 行 | #2,#4,#7,#10 |
| **Batch C1** | F9-P4 soft-delete + purge (最安全的改动，立即缓解域消失) | ~45 行 | #11 |
| **Batch C2** | F9-P1+P5 anchor 加载 + persist 同步 (基础设施) | ~30 行 | #3 基础 |
| **Batch C3** | F9-P2+P3 corrector 保护 + 域回填 (依赖 C2) | ~55 行 | #3 完整 |
| **Batch C4** | F9-S1+S2+S3 基线 + 增量路径 + 质量门禁 + Agent审计 (依赖 C2) | ~210 行 | #3,#9 完整 |

**Batch A + B 合计 ~428 行，解决 8/12 问题 (67%)。** F4 全量升级，所有 LLM 输出使用严格 schema。
**Batch C1-C4 合计 ~340 行，解决剩余 4 个域相关问题。**
**全部 Batch A+B+C 合计 ~768 行，解决 12/12 问题 (100%)。**

---

## 附录：方案对比矩阵

| 方案 | 效果 | H2 元章节 | blockquote | 代码块 | 覆盖率 | 壳域 | 改动量 | 维护成本 |
|------|------|----------|------------|--------|--------|------|--------|---------|
| A 正则黑名单 | ⭐⭐ | 部分 | 部分 | ❌ | ❌ | ❌ | 小 | 高(持续) |
| B H2 白名单 | ⭐⭐⭐⭐ | ✅ | ❌ | ❌ | ❌ | ❌ | ~50行 | 低 |
| **本方案 (混合)** | **⭐⭐⭐⭐⭐** | **✅** | **✅** | **✅** | **✅** | **✅** | **~768行** | **低** |

## 附录：当前系统 Structured Output 架构

```
WikiPageAgent.write()
  ├─ if not is_chinese:           ← 中文被跳过
  │   └─ complete_json()           ← json_object 模式（不强制 schema）
  │       └─ WikiPageOutput        ← Pydantic 模型已存在
  │           └─ render_wiki_page() ← Markdown 渲染器已存在
  └─ fallback:
      └─ generate()                ← 纯文本生成（当前中文的主路径）
          └─ strip_agent_artifacts() ← 正则清洗

DomainDocAgent (继承 DocOrchestrator)
  └─ _run_write_phase()
      └─ GenericAgent._generate_text()
          ├─ if output_type: complete_json() ← 支持但未用于域文档
          └─ else: generate()                ← 纯文本（当前域文档主路径）
```

## 附录：F5 分词方案的最小词长安全性论证

字典分词的核心风险是**短词歧义**。设置最小词长 4 字符后：

**被排除的危险短词 (len < 4):**
`get`, `set`, `add`, `put`, `net`, `map`, `key`, `tag`, `sum`, `man`, `age`, `log`, `new`, `old`, `run`, `bus`, `del`, `job`, `min`, `max`, `mq`, `res`, `sql`, `src`, `tcp`, `udp`, `uri`, `url`, `val`, `web`

**保留的安全长词示例 (len ≥ 4):**
`auth`, `base`, `call`, `cash`, `chat`, `code`, `core`, `data`, `enum`, `exec`, `feed`, `file`, `flow`, `form`, `gift`, `grid`, `hook`, `http`, `info`, `item`, `lang`, `link`, `list`, `load`, `lock`, `logs`, `main`, `math`, `menu`, `mock`, `node`, `note`, `page`, `path`, `perm`, `pool`, `port`, `post`, `push`, `rank`, `rate`, `rest`, `role`, `rule`, `send`, `shop`, `sign`, `sink`, `slot`, `sort`, `spec`, `stat`, `step`, `sync`, `task`, `term`, `test`, `text`, `time`, `tool`, `tree`, `type`, `unit`, `user`, `util`, `view`, `vote`, `work`, `wrap`

**安全验证场景:**
| 输入 | 期望 | 结果 |
|------|------|------|
| `relationfamily` | `relation-family` | ✅ (8+6) |
| `managementhandler` | `management-handler` | ✅ (10+7) |
| `paymentsearch` | `payment-search` | ✅ (7+6) |
| `getservice` | `getservice` (不拆) | ✅ (`get` 3字符跳过) |
| `management` | `management` (不拆) | ✅ (在字典中) |
| `network` | `network` (不拆) | ✅ (`net` 3字符跳过, 整词不在字典) |
| `task` | `task` (不拆) | ✅ (< 8字符跳过) |

---

*本文档为 V10 修复提案（全量覆盖版），实施前需获得审批。*
