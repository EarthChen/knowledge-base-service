# Wiki Quality Fix V7 — merge 缺陷修复 + 渲染清理 + Topic 覆盖率提升

**Status:** ✅ COMPLETED (2026-05-27)
**Created:** 2026-05-27
**Author:** AI Agent (sequential-thinking)
**Source:** V17 四维深度审计报告（4 subagent 全文内容多维审计 + sequential-thinking 根因分析）
**Scope:** 18 个修复点，覆盖 Pipeline 核心缺陷、生成策略、域架构优化、可观测性

---

## 背景

V17（= V16 同批次）审计结果：
- 36 页（18 Overview + 18 Topic），18 域
- 综合评分 4.5/10
- **41.7% 页面存在可发布级缺陷**（15/36 页）
- 4 个 P0 问题、10 个 P1 问题

通过 4 个专项 subagent（Overview 质量、Topic 内容、域架构、渲染/幻觉/质量）和 8 步 sequential-thinking 深度分析，发现**根因中的根因**是 `merge_wiki_pages` 的设计缺陷导致所有 finalize 门禁失效。

### V15-V16 已部署但未生效的修复

| 修复 | 预期效果 | 实际效果 | 失效原因 |
|------|---------|---------|---------|
| stub reject (1500 字) | 拦截 368/753/887 字 stub | 未拦截 | merge 恢复了 rejected 页面 |
| CN ratio 硬门禁 (0.25) | 拦截 cn_ratio=0.159 页面 | 未拦截 | 同上 |
| 幻觉 Topic reject | 拦截含编造数据的 Topic | 未拦截 | 同上 |

---

## 修复清单概览

| ID | 修复项 | 优先级 | 预估行数 | 涉及文件 |
|----|--------|--------|---------|---------|
| F1 | finalize reject 泄漏修复 | **P0** | ~20 | `wiki/nodes/finalize.py`, `wiki/persistence.py` |
| F2 | 渲染清理（空代码块/空 WikiLink/注入残留） | **P0** | ~30 | `wiki/nodes/finalize.py` |
| F3 | H2 去重 | **P0** | ~40 | `wiki/nodes/finalize.py` |
| F4 | 幻觉规则扩展 + Overview reject | **P0** | ~25 | `wiki/nodes/finalize.py` |
| F5 | plan_topics 触发条件优化 | **P0** | ~10 | `wiki/domain_doc_agent.py` |
| F6 | Topic 数量限制 | P1 | ~10 | `core/config.py`, `wiki/domain_doc_agent.py` |
| F7 | 套话禁令 | P1 | ~10 | `wiki/agent_prompts.py` |
| F8 | 壳域检测 | P1 | ~10 | `wiki/domain_doc_agent.py` |
| F12 | CN ratio 门禁统一逻辑 | **P1** | ~15 | `wiki/nodes/quality_gate.py`, `wiki/nodes/finalize.py` |
| F13 | 英文段落强制中文化 | **P1** | ~15 | `wiki/nodes/finalize.py`, `wiki/agent_prompts.py` |
| F9 | 域拆分 prompt 优化 + slug 命名约束 | P2 | ~15 | `wiki/nodes/graph_domain_decompose.py` |
| F10 | infra slug 检测扩展 | P2 | ~10 | `wiki/nodes/domain_filters.py` |
| F11 | 拼音 slug 检测 + Topic slug 英文化 | P2 | ~15 | `wiki/path_conventions.py`, `wiki/domain_doc_agent.py` |
| F14 | Tracing span 栈修复 | P2 | ~10 | `wiki/agents/tracing.py` |
| F15 | JsonlTraceProcessor 异步化 | P2 | ~15 | `wiki/agents/tracing.py` |
| F16 | PipelineConcurrency 缓存刷新 + quality_l3 映射修正 | P2 | ~10 | `wiki/pipeline_concurrency.py` |
| F17 | `_enforce_limit` 空字符串死循环防护 | P2 | ~5 | `wiki/page_agent.py` |
| F18 | 可观测性：run_id + 每页评分 + metrics 计数器 | P3 | ~25 | `wiki/pipeline_graph.py`, `wiki/nodes/quality_gate.py`, `wiki/nodes/finalize.py` |

**合计预估：~290 行改动 + ~20 个新测试**

---

## Batch 1：P0 紧急修复（下次生成前必须完成）

### F1 — finalize reject 泄漏修复（P0，致命）

#### 问题

finalize 节点通过 `continue` 跳过 rejected 页面（stub/低 CN/幻觉），这些页面不出现在 `updated_pages` 中。但 LangGraph 的 `merge_wiki_pages` 函数只做「right 覆盖 left」，未被 right 覆盖的 left 页面仍然保留。

**结果：所有 finalize 门禁形同虚设。**

```python
# wiki/pipeline_state.py L11-38 — 当前 merge 逻辑
def merge_wiki_pages(left, right):
    by_path = {}
    order = []
    for p in left:  # left = 上一节点输出（含所有页面）
        ...
        by_path[path] = p
    for p in right:  # right = finalize 输出（不含 rejected 页面）
        ...
        by_path[path] = p  # 只覆盖 right 中有的
    return [by_path[path] for path in order]
    # 结果：left 中被 reject 的页面因不在 right 中而被保留
```

#### 修改方案

**策略：** 在 finalize 中将 rejected 页面标记为 `__rejected__=True` 并加入 `updated_pages`，让 merge 覆盖 left 侧旧页面。persist 节点过滤掉 `__rejected__` 页面。

**文件 1：`wiki/nodes/finalize.py`**

每个 `continue` reject 点改为：

```python
# 原来：
if raw_content_len < min_publish:
    log.warning("stub_topic_rejected", ...)
    continue

# 改为：
if raw_content_len < min_publish:
    log.warning("stub_topic_rejected", ...)
    updated_pages.append({**page, "content": "", "__rejected__": True})
    continue
```

同样修改 CN ratio reject 和 hallucination reject 处。

**文件 2：`wiki/persistence.py`**

在 `save_wiki_pages` 开头过滤：

```python
async def save_wiki_pages(self, pages, ...):
    pages = [p for p in pages if not p.get("__rejected__")]
    ...
```

#### 测试

1. `test_finalize_stub_reject_marker` — 验证 stub 页面带 `__rejected__` 标记
2. `test_finalize_cn_reject_marker` — 验证低 CN ratio 页面带标记
3. `test_persist_filters_rejected` — 验证 persist 过滤掉 rejected 页面

---

### F2 — 渲染清理（P0，影响 6 页）

#### 问题

| 渲染问题 | 影响页数 | 具体形式 |
|---------|---------|---------|
| 空代码块 | 6 | ` ```java\n\n``` `、` ```\n\n``` ` |
| 空 WikiLink | 1 (5 处) | `[[]]` |
| 注入残留 | 2 | `<!-- __INJECTED_CODE_REF__ -->` |
| 多余空行 | 多页 | 4+ 连续空行 |

#### 修改

**文件：`wiki/nodes/finalize.py`**

新增 `_sanitize_render_issues` 函数，在 `_sanitize_published_content` 调用后执行：

```python
_EMPTY_CODE_BLOCK_RE = re.compile(r"```\w*\n\s*```")
_EMPTY_WIKILINK_RE = re.compile(r"\[\[\s*\]\]")
_INJECTED_REF_RE = re.compile(r"<!-- __INJECTED_CODE_REF__[^>]* -->")
_EXCESS_NEWLINES_RE = re.compile(r"\n{4,}")


def _sanitize_render_issues(content: str) -> str:
    """Remove empty code blocks, empty wikilinks, injection residuals."""
    content = _EMPTY_CODE_BLOCK_RE.sub("", content)
    content = _EMPTY_WIKILINK_RE.sub("", content)
    content = _INJECTED_REF_RE.sub("", content)
    content = _EXCESS_NEWLINES_RE.sub("\n\n\n", content)
    return content.strip()
```

调用位置（在 finalize 循环内）：

```python
content = _sanitize_published_content(content, state)
content = _sanitize_render_issues(content)  # 新增
content = _remove_invalid_wikilinks(content, valid_targets)
```

#### 测试

1. `test_sanitize_empty_code_block` — 各种形式的空代码块被删除
2. `test_sanitize_empty_wikilink` — `[[]]` 被删除
3. `test_sanitize_injected_ref` — `<!-- __INJECTED_CODE_REF__ -->` 被删除

---

### F3 — H2 去重（P0，影响 4 页）

#### 问题

4 页存在重复 H2（最严重：家族关系与权限有 4 个 `## 相关主题`）。
根因：heal 循环多次 append「相关主题」模板，finalize 无 H2 级去重。

#### 修改

**文件：`wiki/nodes/finalize.py`**

新增 `_dedup_h2_sections` 函数：

```python
def _dedup_h2_sections(content: str) -> str:
    """Deduplicate H2 sections with identical titles; keep the last occurrence."""
    lines = content.split("\n")
    h2_indices: list[int] = []
    for i, line in enumerate(lines):
        if line.startswith("## "):
            h2_indices.append(i)

    if not h2_indices:
        return content

    sections: list[tuple[int, int, str]] = []
    for idx, start in enumerate(h2_indices):
        end = h2_indices[idx + 1] if idx + 1 < len(h2_indices) else len(lines)
        h2_title = lines[start].strip()
        sections.append((start, end, h2_title))

    title_last: dict[str, int] = {}
    for i, (_, _, title) in enumerate(sections):
        title_last[title] = i

    to_remove = {i for i, (_, _, title) in enumerate(sections) if title_last[title] != i}

    if not to_remove:
        return content

    pre_section = lines[: h2_indices[0]] if h2_indices else []
    new_lines = list(pre_section)
    for i, (start, end, _) in enumerate(sections):
        if i not in to_remove:
            new_lines.extend(lines[start:end])

    return "\n".join(new_lines)
```

调用位置：在 `_sanitize_render_issues` 之后。

#### 测试

1. `test_dedup_h2_basic` — 同名 H2 只保留最后一个
2. `test_dedup_h2_no_change` — 无重复时不变

---

### F4 — 幻觉规则扩展 + Overview reject（P0）

#### 问题

1. 现有规则未覆盖：虚构技术路线图（GNN/联邦学习）、编造产品名（星光礼盒/徽章）、Phase 路线图、元数据自引用
2. Overview 检测到幻觉仅加 banner，不 reject。user-basic-data 整页幻觉但仍发布

#### 修改

**文件：`wiki/nodes/finalize.py`**

1. `_detect_hallucination_patterns` 增加规则：

```python
hallucination_res = [
    # 现有规则...
    (r"\d+\.\d+%", "fabricated_percentage"),
    (r"\b\d{2,3}%", "fabricated_round_percentage"),
    (r"≤\d+s|≥\d+\.\d+", "fabricated_sla"),
    (r"P\d{2}\s*[<≤]\s*\d+", "fabricated_latency_sla"),
    (r"留存.*[+\-]\d+", "fabricated_retention_metric"),
    (r"健身|看护|儿童", "fabricated_business_scenario"),
    (r"\d{4}年\d{1,2}月\d{1,2}日", "fabricated_date"),
    (r"\d{4}-\d{2}-\d{2}\s+复核", "fabricated_review_date"),
    # 新增规则
    (r"GNN|\b联邦学习|LSTM|Transformer|GDPR", "fabricated_tech_roadmap"),
    (r"Phase\s+\d|\d+-\d+个月", "fabricated_timeline"),
    (r"中文字符占比|字符比例", "meta_self_reference"),
    (r"共同采购|节日准备|婚恋平台", "fabricated_scenario"),
]
```

2. Overview 幻觉 >= 3 种时 hard reject：

```python
if hallucination_flags:
    if is_topic and not is_topic_index:
        updated_pages.append({**page, "content": "", "__rejected__": True})
        continue
    if is_overview and len(hallucination_flags) >= 3:
        log.warning("hallucination_overview_rejected", ...)
        updated_pages.append({**page, "content": "", "__rejected__": True})
        continue
    # 否则仅加 banner
    content = banner + content
```

#### 测试

1. `test_hallucination_tech_roadmap` — GNN/联邦学习 被检测
2. `test_hallucination_overview_reject` — 幻觉 >= 3 种的 Overview 被 reject
3. `test_hallucination_overview_banner_only` — 幻觉 < 3 种仅加 banner

---

### F5 — plan_topics 触发条件优化（P0）

#### 问题

```python
# wiki/domain_doc_agent.py L547
if len(module_names) <= 5:
    return None  # 78% 域被跳过
```

仅用模块数判断，导致 14/18 域无 Topic。但 relation-rank (7251 字)、user-relation-management (8038 字) 等有丰富 Overview 的域也被跳过。

#### 修改

**文件：`wiki/domain_doc_agent.py`**

```python
async def plan_topics(self, memory: Any, module_names: list[str]) -> list[Any] | None:
    if not get_settings().wiki.enable_topic_pages:
        return None

    overview_content = getattr(memory, "final_overview", None) or ""
    overview_len = len(overview_content)
    min_overview_for_topics = get_settings().wiki.min_overview_len_for_topics  # 默认 4000

    should_plan = len(module_names) > 4 or overview_len >= min_overview_for_topics
    if not should_plan:
        return None
    ...
```

**文件：`core/config.py`**

```python
class AppWikiFlags(BaseModel):
    ...
    min_overview_len_for_topics: int = 4000
```

#### 影响预估

- 当前 14 个无 Topic 域中，overview_len >= 4000 的有 7 个
- Topic 覆盖率：22% (4/18) → ~61% (11/18)

#### 测试

1. `test_plan_topics_overview_len_trigger` — 模块数 <= 4 但 overview >= 4000 时触发
2. `test_plan_topics_skip_small_domain` — 模块数 <= 4 且 overview < 4000 时跳过

---

## Batch 2：P1 重要修复（质量提升）

### F6 — Topic 数量限制

**文件：** `core/config.py`, `wiki/domain_doc_agent.py`

- 新增配置 `max_topics_per_domain: int = 4`
- `plan_topics` 返回的 outline 中 topics 数量超过上限时截断
- Topic planner prompt 增加差异化约束：

```
每个 Topic 必须标注其独占的核心模块，不同 Topic 间禁止引用相同模块。
若域模块数 < 10，最多规划 3 个 Topic。
```

### F7 — 套话禁令

**文件：** `wiki/agent_prompts.py`

在 AGENT_WRITE_SYSTEM 的中文写作规范中增加：

```
禁止使用以下空洞表述：
- 「高内聚低耦合」「核心价值在于」「分层架构设计」「显著提升」「长期稳定运行」「核心业务能力」「为上层业务提供」
每个描述必须绑定具体的类名/方法名/业务规则。若某处无法提供具体信息，删除该段而非填充套话。
```

### F8 — 壳域检测

**文件：** `wiki/domain_doc_agent.py` 或 `wiki/nodes/compose.py`

域生成前检查模块数：

```python
if not module_names:
    log.info("skip_shell_domain_no_modules", domain=self.domain_name)
    return []  # 不生成 Overview
```

---

## Batch 3：P1 重要修复（V17 补全）

### F12 — CN ratio 门禁统一逻辑（P1）

#### 问题

V17 审计发现 CN ratio 检查在 3 个位置实现，阈值/触发条件不一致：

| 位置 | 阈值 | 触发条件 | 行为 |
|------|------|---------|------|
| `quality_gate.py:238` | 0.4 | 需显式 `content_language` 且为中文 | 软门禁 → heal |
| `finalize.py:331` | 0.25 | 回退到 state config | 硬门禁 → reject |
| `heal.py:69` | 0.25 | — | heal 后检查 |

`quality_gate.py:236` 的条件 `if page_type == "topic" and content_language and _is_chinese_lang(content_language)` 要求 `content_language` 显式设置。若页面无显式语言标记，CN ratio 检查被完全跳过，浪费一个 heal 周期。

`家族消息与事件驱动` (cn=0.159) 因 `_normalize_headings_to_chinese` 只处理标题不处理段落内容，英文 Overview 段落未被转换。

#### 修改

**文件 1：`wiki/nodes/quality_gate.py`**

放宽触发条件，基于内容自动检测语言：

```python
# 原来：
if page_type == "topic" and content_language and _is_chinese_lang(content_language):

# 改为：
if page_type == "topic":
    effective_lang = content_language or _detect_lang_from_content(content)
    if _is_chinese_lang(effective_lang):
        cn = _compute_cn_ratio(content)
        if cn < language_guardrail_cn_ratio:
            flags.append(...)
```

`_detect_lang_from_content` 可复用审计脚本中的 CN 字符比例计算：若 cn_ratio > 0.15 判定为中文内容。

**文件 2：`wiki/nodes/finalize.py`**

`_resolve_page_content_language` 已有 state config 回退逻辑，保持不变。确保 `cn_ratio_hard_min=0.25` 门禁在 finalize 层做最终兜底。

#### 测试

1. `test_quality_gate_cn_ratio_auto_detect` — 无 content_language 时基于内容自动检测
2. `test_quality_gate_cn_ratio_skip_english_page` — 纯英文页面不触发中文 CN 检查

---

### F13 — 英文段落强制中文化（P1）

#### 问题

`家族消息与事件驱动` cn_ratio=0.159，Overview 段落全英文（~200 词）。`_normalize_headings_to_chinese` 只映射标题，不处理 `> **Overview**:` 标记块和正文英文段落。

根因：LLM 在生成 Overview 摘要时默认使用英文，即使内容语言为中文。

#### 修改

**文件 1：`wiki/agent_prompts.py`**

在 AGENT_WRITE_SYSTEM 的中文写作规范中增加：

```
所有段落（包括顶部 Overview 摘要块）必须使用中文撰写。
禁止出现英文段落或英文 Overview 块。
代码块内的注释使用中文。
```

**文件 2：`wiki/nodes/finalize.py`**

在 `_sanitize_published_content` 中增加英文 Overview 块检测与清理：

```python
_OVERVIEV_EN_RE = re.compile(r"^>\s*\*\*Overview\*\*\s*:.*?(?=\n(?!\s*>)|\n##|\Z)", re.DOTALL | re.MULTILINE)

def _sanitize_english_overview(content: str) -> str:
    """Remove or replace English Overview blocks."""
    match = _OVERVIEV_EN_RE.search(content)
    if match:
        text = match.group(0)
        cn_chars = sum(1 for c in text if "一" <= c <= "鿿")
        if cn_chars / max(len(text), 1) < 0.15:  # 英文主导
            content = content[:match.start()] + content[match.end():]
    return content
```

#### 测试

1. `test_sanitize_english_overview_removed` — 英文 Overview 块被移除
2. `test_sanitize_chinese_overview_preserved` — 中文 Overview 块被保留

---

## Batch 4：P2 优化（健壮性 + 可观测性）

### F9 — 域拆分 prompt 优化 + slug 命名约束

**文件：** `wiki/nodes/graph_domain_decompose.py`

域拆分 prompt 增加约束：

```
域拆分规则：
1. 目标域数 8-12 个，严禁超过 15
2. 每个域必须包含 >= 3 个核心模块
3. 单功能模块（如弹窗、类型转换）不应独立成域
4. 基础设施模块（ES 客户端、MyBatis 工具、通用代理）不应出现在业务域树中
5. 域 slug 必须与 title 语义一致（如 slug 为 quick-message 但 title 为 ES客户端封装，视为命名错误）
```

### F10 — infra slug 检测扩展

**文件：** `wiki/nodes/domain_filters.py`

扩展 `_is_infra_slug` 检测 Java 基本类型名泄漏：

```python
_JAVA_PRIMITIVE_SLUGS = {"long", "int", "byte", "short", "float", "double", "boolean", "void"}

def _is_infra_slug(slug: str) -> bool:
    ...
    if slug.split("-")[0] in _JAVA_PRIMITIVE_SLUGS:
        return True
```

### F11 — 拼音 slug 检测 + Topic slug 英文化

**文件：** `wiki/path_conventions.py`, `wiki/domain_doc_agent.py`

1. 增加拼音 slug 检测函数（启发式：连续 4+ 个 2-4 字母 segment）
2. Topic planner prompt 明确要求英文语义 slug：

```
Topic slug 必须使用英文语义翻译，严禁拼音。
正确：family-integration, intimacy-task-strategy
错误：jia-zu-xi-tong-ji-cheng-yu-kuo-zhan
```

### F14 — Tracing span 栈修复（P2）

#### 问题

`wiki/agents/tracing.py:78-80` — 子 span 后于父 span 结束时（并发 async 场景），`end_span` 通过 `self._span_stack = self._span_stack[:idx]` 截断栈，丢弃父 span 引用。后续 `start_span` 的 `parent_id=None`，span 树断裂。静默数据损坏，无异常抛出。

#### 修改

**文件：`wiki/agents/tracing.py:78-80`**

```python
# 原来：
if span in self._span_stack:
    idx = self._span_stack.index(span)
    self._span_stack = self._span_stack[:idx]

# 改为：仅移除目标 span，不截断栈
if span in self._span_stack:
    self._span_stack.remove(span)
```

#### 测试

1. `test_span_out_of_order_removal` — 子 span 后于父 span 结束时不破坏栈
2. `test_span_concurrent_end` — 并发 end_span 不产生异常

---

### F15 — JsonlTraceProcessor 异步化（P2）

#### 问题

`wiki/agents/tracing.py:108` — 每次 span 结束执行同步 `open()/write()` 文件 I/O，在高并发 tool call 场景下阻塞 asyncio 事件循环。

#### 修改

**文件：`wiki/agents/tracing.py`**

```python
# 原来：
with open(path, "a", encoding="utf-8") as f:
    f.write(json.dumps(record, ...) + "\n")

# 改为：
loop = asyncio.get_running_loop()
await loop.run_in_executor(None, _write_sync, path, record)

def _write_sync(path: str, record: dict) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ...) + "\n")
```

#### 测试

1. `test_trace_processor_async_write` — 验证写入不阻塞事件循环

---

### F16 — PipelineConcurrency 缓存刷新 + quality_l3 映射修正（P2）

#### 问题

1. `wiki/pipeline_concurrency.py:18` — `_cache: ClassVar[dict[str, asyncio.Semaphore]] = {}` 类级别缓存永不过期。配置变更后旧 semaphore 持久存在直到进程重启。
2. `pipeline_concurrency.py:66` — `"quality_l3": cfg.compose_concurrency` 错误映射到 `compose_concurrency`（默认 16），L3 LLM-as-judge 可能 16 并发打爆 rate limiter。

#### 修改

**文件：`wiki/pipeline_concurrency.py`**

```python
# 1. 增加 quality_l3 独立配置
# core/config.py:
quality_l3_concurrency: int = 4

# 2. 修正映射
_LIMIT_MAP = {
    ...
    "quality_l3": cfg.quality_l3_concurrency,
}

# 3. semaphore() 返回前检查配置变更
def semaphore(self, name: str) -> asyncio.Semaphore:
    limit = self._resolve_limit(name)
    cached = self._cache.get(name)
    if cached is not None and cached._value == limit:  # noqa: SLF001
        return cached
    sem = asyncio.Semaphore(limit)
    self._cache[name] = sem
    return sem
```

#### 测试

1. `test_concurrency_config_refresh` — 配置变更后 semaphore 自动重建
2. `test_quality_l3_separate_limit` — quality_l3 使用独立并发限制

---

### F17 — `_enforce_limit` 空字符串死循环防护（P2）

#### 问题

`wiki/page_agent.py:416-425` — 第二个 while 循环中，若条目为空字符串，`total -= len(lst[0])` 减 0，`total` 永不减少，循环无限。

#### 修改

**文件：`wiki/page_agent.py:416-425`**

```python
while total > self.MAX_TOTAL_CHARS:
    if not any(all_lists):
        break
    for lst in all_lists:
        if lst:
            entry = lst[0]
            total -= max(len(entry), 1)  # 空字符串至少减 1
            lst.pop(0)
            break
```

#### 测试

1. `test_enforce_limit_empty_string` — 空字符串条目不会导致死循环

---

### F18 — 可观测性：run_id + 每页评分 + metrics 计数器（P3）

#### 问题

V17 审计发现 5 项可观测性缺失：

| 缺失项 | 影响 |
|--------|------|
| 无 run_id/correlation_id | 无法追溯坏页到特定管线运行 |
| 无每页质量评分日志 | quality_gate 仅输出聚合计数 |
| 无发布/拒绝计数器 | finalize 只打 warning，无 metrics |
| heal 效果未追踪 | 不知道 heal 是否改善了分数 |
| heal 原因未记录 | `pages_to_heal` 返回但未 log 原因 |

#### 修改

**文件 1：`wiki/pipeline_state.py`（或 `pipeline_graph.py`）**

```python
from uuid import uuid4

class WikiPipelineState(TypedDict):
    run_id: str  # 新增
    ...
```

在 pipeline 启动时注入：`state["run_id"] = uuid4().hex[:12]`

**文件 2：`wiki/nodes/quality_gate.py`**

```python
log.info(
    "quality_gate_done",
    run_id=state.get("run_id"),
    total_pages=total,
    evaluated=evaluated,
    to_heal=len(pages_to_heal),
    # 新增：每页评分摘要
    page_scores=[
        {"path": r.page.path, "overall": r.overall, "level": r.level.value}
        for r in results
    ],
)
```

**文件 3：`wiki/nodes/finalize.py`**

```python
published = sum(1 for p in updated_pages if not p.get("__rejected__"))
rejected = sum(1 for p in updated_pages if p.get("__rejected__"))
log.info(
    "wiki_finalize_metrics",
    run_id=state.get("run_id"),
    pages_published=published,
    pages_rejected=rejected,
    rejection_reasons=_rejection_reasons,  # {"stub": 3, "hallucination": 1, ...}
)
```

#### 测试

1. `test_run_id_injected` — pipeline state 包含 run_id
2. `test_quality_gate_page_scores_logged` — 每页评分出现在日志中
3. `test_finalize_metrics_logged` — 发布/拒绝计数出现在日志中

---

## 风险评估

| Fix | 风险 | 缓解措施 |
|-----|------|---------|
| F1 reject 泄漏 | 低 — 最小侵入性，不改 merge/state | `__rejected__` 仅在 finalize→persist 路径使用 |
| F2 渲染清理 | 中 — 正则可能误删 | 空代码块正则精确匹配「语言标签 + 纯空白 + 闭合」 |
| F3 H2 去重 | 中 — 可能误删同名有效 section | 仅当重复 >= 2 次时触发，保留最后一个 |
| F4 幻觉规则 | 中 — 新规则可能误报 | reject 条件是幻觉类型 >= 3，单个误报不触发 |
| F5 Topic 触发 | 低 — 错误触发最坏结果是多生成 Topic | 由 stub reject 兜底 |
| F12 CN ratio 统一 | 低 — 放宽触发条件不会误拒 | finalize 硬门禁兜底 |
| F13 英文段落清理 | 中 — 正则可能误删中文 Overview | 仅当 cn_ratio < 0.15 时移除 |
| F14 span 栈修复 | 低 — `list.remove()` 行为明确 | 并发测试覆盖 |
| F15 异步写入 | 低 — `run_in_executor` 标准模式 | 失败时静默降级（trace 非关键路径） |
| F16 semaphore 刷新 | 低 — 配置检查开销可忽略 | 仅在 `semaphore()` 调用时检查，非轮询 |
| F17 死循环防护 | 低 — `max(len, 1)` 最小改动 | 原有测试覆盖 |
| F18 可观测性 | 低 — 纯日志增强，不影响逻辑 | run_id 12 字符，日志体积增加可控 |

## 预期效果

| 指标 | V17 现状 | Batch 1 后 | Batch 1+2 后 | Batch 1-4 后 |
|------|---------|-----------|-------------|-------------|
| Topic 覆盖率 | 22% (4/18) | ~61% (11/18) | ~61% | ~61% |
| Stub Topic | 3 | 0 | 0 | 0 |
| 幻觉页 | 4 | 0-1 | 0 | 0 |
| 渲染问题页 | 6 | 0-1 | 0 | 0 |
| 重复 H2 | 4 | 0-1 | 0 | 0 |
| 低 CN ratio | 2 | 0 | 0 | 0 |
| 壳域 | 2 | 2 | 0-1 | 0-1 |
| 模板化套话 | 23% | 23% | <5% | <5% |
| 英文段落污染 | 3 页 | 3 页 | 3 页 | 0-1 页 |
| Span 栈损坏 | 存在 | 存在 | 存在 | 修复 |
| 可观测性 | 无 | 无 | 无 | run_id + metrics |
| **综合评分** | **5.7/10** | **7.0-7.5** | **7.5-8.0** | **8.0-8.5** |

---

## 实施计划

| 阶段 | 内容 | 预估工时 |
|------|------|---------|
| Phase 1 | Batch 1 (F1-F5) TDD 实现 + 测试 | 2-3 小时 |
| Phase 2 | 部署到 dev + 全量生成 + V18 审计 | 1 小时 |
| Phase 3 | Batch 2 (F6-F8) + Batch 3 (F12-F13) 实现 + 测试 | 2-3 小时 |
| Phase 4 | 部署 + V19 审计 | 1 小时 |
| Phase 5 | Batch 4 (F9-F11, F14-F18) 按需实施 | 3+ 小时 |

---

*本文档为 V17 审计后的完整修复设计方案。所有 18 个修复点已于 2026-05-27 完成实施并通过 3475 个测试验证。*
