# Wiki Quality Fix V12 Design Spec

**Date:** 2026-05-28
**Status:** Proposal (Awaiting Approval)
**Audit Base:** V26 (2026-05-28, `data/wiki-audit-latest.json`) — V11 全量部署后首次多维审计
**Supersedes:** V11 design (retained as reference, execution completed)

---

## 1. Background & Goals

### V11 修复效果验证（V26 审计）

| V11 Fix | 部署状态 | V26 实测效果 |
|---------|---------|-------------|
| F1 Topic Coverage (prompt≤2 + chunk=3 + force_override) | ✅ 已部署 | ✅ 覆盖率 9%→**76.5%** (13/17 域有 topic) |
| F2 Slug Repeated Segment (dedup + segment cleanup) | ✅ 已部署 | ✅ 重复段 2→**0** |
| F3 Overview cn_ratio Gate (heal 0.20 + reject 0.15) | ✅ 已部署 | ✅ 低cn页 6→**0** |
| F4 tree_linker Shell Gate (sanitize + 长度校验) | ✅ 已部署 | ⚠ 壳域 4→**3**（减少1但未消除） |
| F5-R Enhanced Corrector (包层次+跨域调用+JSON Schema) | ✅ 已部署 | ❌ 错挂域 2→**2**（data-type-mapping、task-execution-framework 仍错挂） |
| F6 Code Overload Detection | ✅ 已部署 | ✅ 代码堆叠极端case→**0** |
| F7-R DomainAnchor (可选增量保护) | ✅ 已部署 | N/A（首次生成无 anchor） |

**结论：** V11 在 Topic 覆盖率和 cn_ratio 门禁上取得重大突破（覆盖率从 9%→76.5%）。但暴露了一批 V11 未预见的**结构性问题**，需 V12 治理。

### V26 Current State

| Metric | V25 (V11前) | V26 (V11后) | Target |
|--------|-------------|-------------|--------|
| Total pages | 30 | **50** | — |
| Topic coverage | 9% (2/22) | **76.5%** (13/17) | ≥90% |
| Shell domains | 4 | **3** | 0 |
| Slug repeated segments | 2 | **0** ✅ | 0 |
| Misplaced infra domains | 2 | **2** ❌ | 0 |
| Low cn_ratio pages | 6 | **0** ✅ | 0 |
| Garbage slug | 1 | **1** ❌ | 0 |
| **Part N mechanical naming** | N/A | **22/33 (66.7%)** | <15% |
| **Stub topics (23 chars)** | 0 | **2** | 0 |
| **Duplicate titles** | 1 | **2 组** | 0 |
| **H2 trailing spaces** | 0 | **3 topics** | 0 |
| **Code truncation** | 3/22 | **≥6/50** | 0 |
| **Missing "## 概述"** | 0 | **4 topics** | 0 |
| **Max tree depth** | 4 | **4** | ≤3 |
| **Domains without topics** | 20 (91%) | **4 (23.5%)** | 0 |

### V12 设计原则

延续 V11 三层纵深防御原则，V12 聚焦于**内容质量提升**和**导航体验优化**：

| 层 | V11 侧重 | V12 侧重 |
|----|---------|---------|
| **预防层** | Prompt约束/Schema约束 | **命名约束/模板多样化/代码量控制** |
| **检测层** | quality_gate/content_guards | **标题唯一性/代码块闭合/H2格式** |
| **兜底层** | finalize hard-reject | **stub消除/壳域折叠/infra重分类** |

---

## 2. Fix Design (F1–F11)

### F1: Topic 语义化命名（消除 Part N）

**Problem:** `_build_mechanical_topic_split` 使用 `title = f"{display_name} - Part {i+1}"` 生成无语义标题。22/33 (66.7%) topics 使用 Part N 命名，用户无法从目录区分 topic 内容。

**Root Cause:** `domain_doc_agent.py` 的机械拆分路径直接编号，不尝试从模块内容提取语义标题。

**三层防御设计:**

| 层 | 手段 | 效果 |
|----|------|------|
| 预防 | 机械拆分时用模块簇首个模块的 `display_name` 或 `description[:30]` 作标题 | 源头避免 Part N |
| 检测 | `quality_gate` 检测标题是否匹配 `r"- Part \d+"` 并标记为 heal hint | 触发重命名 |
| 兜底 | `finalize` 阶段对 Part N 标题做 fallback：用页面内首个 H2 后第一句话生成标题摘要 | 保证不落库 Part N |

**Changes:**

| File | Change |
|------|--------|
| `wiki/domain_doc_agent.py` | `_build_mechanical_topic_split`: 用模块簇语义生成标题替代 Part N |
| `wiki/nodes/quality_gate.py` | 检测 Part N 标题模式 |
| `wiki/nodes/finalize.py` | Part N fallback：提取首段内容生成摘要标题 |

**Code (预防层 — 语义标题):**
```python
# domain_doc_agent.py: _build_mechanical_topic_split 内
# Before: title = f"{display_name} - Part {i+1}"
# After:
def _extract_chunk_title(modules: list[dict], display_name: str, idx: int) -> str:
    """Extract a semantic title from a module chunk."""
    if len(modules) == 1:
        mod_name = modules[0].get("display_name", modules[0].get("name", ""))
        if mod_name and mod_name != display_name:
            return mod_name
    # Use the most descriptive module name in the chunk
    best = max(modules, key=lambda m: len(m.get("display_name", m.get("name", ""))))
    candidate = best.get("display_name", best.get("name", ""))
    if candidate and candidate != display_name:
        return candidate
    return f"{display_name} - Part {idx + 1}"
```

**Expected:** Part N 占比 66.7% → <15%。

**Tests:**
- New: `test_mechanical_split_uses_module_name_not_part_n`
- New: `test_quality_gate_detects_part_n_title`
- New: `test_finalize_rewrites_part_n_fallback`

---

### F2: Stub Topic 消除门禁

**Problem:** 2 个 topic 仅 23 字符（`> ⚠️ 本域文档待完善，内容可能不完整。`），完全不可用。

**Root Cause:** `domain_doc_agent.py` 在 Agent 生成失败或超时时写入 placeholder，但 `quality_gate` 和 `finalize` 未拦截。

**三层防御设计:**

| 层 | 手段 | 效果 |
|----|------|------|
| 预防 | Agent 超时/失败时不写入 placeholder，改为 skip | 源头不产生 stub |
| 检测 | quality_gate 检测 `content_length < 500` 的 topic | 标记为 reject 候选 |
| 兜底 | finalize hard-reject `content_length < 200` 的任何页面 | 不落库 |

**Changes:**

| File | Change |
|------|--------|
| `wiki/domain_doc_agent.py` | Agent 失败时 skip 而非写 placeholder |
| `wiki/nodes/quality_gate.py` | 增加 `min_content_length` 检查 (topic: 500, overview: 1000) |
| `wiki/nodes/finalize.py` | hard-reject < 200 chars 的任何页面 |

**Code (finalize hard-reject):**
```python
# finalize.py: 在现有校验逻辑前
_MIN_PAGE_CHARS = 200

content_stripped = content.strip()
if len(content_stripped) < _MIN_PAGE_CHARS:
    log.warning("page_too_short_rejected", path=path, chars=len(content_stripped))
    updated_pages.append({**page, "content": "", "__rejected__": True})
    continue
```

**Expected:** Stub topics 2 → 0。

**Tests:**
- New: `test_stub_topic_rejected_by_finalize`
- New: `test_agent_failure_does_not_produce_placeholder`

---

### F3: 全局标题唯一性门禁

**Problem:** "挚友关系管理" 出现在 2 个不同域的 topic；"用户资料与状态" 既作 overview 标题又作 topic 标题。侧栏导航无法区分。

**Root Cause:** `tree_linker` 和 `finalize` 无全局标题去重逻辑。

**三层防御设计:**

| 层 | 手段 | 效果 |
|----|------|------|
| 预防 | topic 生成 prompt 中注入同域已有 topic 标题列表，要求不重复 | Agent 层面避免 |
| 检测 | finalize 全局标题去重：`business_id` 范围内所有页面标题必须唯一 | 自动追加域名后缀消歧 |
| 兜底 | tree_linker 写入前校验标题唯一性 | 不落库重复标题 |

**Changes:**

| File | Change |
|------|--------|
| `wiki/nodes/finalize.py` | 全局标题去重：重复标题追加 `（{domain_display_name}）` 后缀 |
| `wiki/tree_linker.py` | 写入前校验标题唯一 |

**Code (finalize 去重):**
```python
# finalize.py: 在 persist 前
def _deduplicate_titles(pages: list[dict]) -> list[dict]:
    """Ensure all page titles within a business are unique."""
    title_count: dict[str, list[int]] = {}
    for i, p in enumerate(pages):
        title = p.get("title", "")
        title_count.setdefault(title, []).append(i)

    for title, indices in title_count.items():
        if len(indices) <= 1:
            continue
        for idx in indices:
            p = pages[idx]
            domain = p.get("business_domain", "") or _extract_domain_from_path(p.get("path", ""))
            if domain:
                pages[idx] = {**p, "title": f"{title}（{domain}）"}
    return pages
```

**Expected:** Duplicate titles 2 组 → 0。

**Tests:**
- New: `test_finalize_deduplicates_titles`
- New: `test_finalize_appends_domain_suffix_for_duplicates`

---

### F4: H2 格式清洗（尾随空格 + 缺失概述）

**Problem:** 3 个 topic 的 H2 后有多余空格（`## 概述  `）；4 个 topic 缺少 `## 概述` 节。

**Root Cause:** LLM 生成的 Markdown 未经 H2 格式规范化。

**Changes:**

| File | Change |
|------|--------|
| `wiki/content_guards.py` | 新增 `strip_h2_trailing_whitespace` + 在 `sanitize_content` 中调用 |
| `wiki/nodes/quality_gate.py` | 检测缺少 `## 概述` 的 topic 并标记 heal hint |

**Code (H2 清洗):**
```python
# content_guards.py
import re

def strip_h2_trailing_whitespace(content: str) -> str:
    """Remove trailing whitespace from H2 headings: '## 概述  ' → '## 概述'"""
    return re.sub(r"^(## .+?)\s+$", r"\1", content, flags=re.MULTILINE)
```

**Expected:** H2 trailing spaces 3 → 0; Missing 概述 4 → heal 触发。

**Tests:**
- New: `test_strip_h2_trailing_whitespace`
- New: `test_missing_overview_section_detected`

---

### F5: 代码块闭合检测与修复

**Problem:** ≥6 个页面存在截断的 Java 代码块（未闭合的 ` ``` `）。

**Root Cause:** LLM 生成的内容在 token limit 截断时可能中断代码块。`repair_code_fences` 仅处理双重 fence，未检测未闭合的 fence。

**三层防御设计:**

| 层 | 手段 | 效果 |
|----|------|------|
| 预防 | Prompt 约束代码块最大行数（已有 V11 F3 的 20 行限制） | 减少截断概率 |
| 检测 | content_guards 新增 `detect_unclosed_code_blocks` | 发现未闭合 |
| 兜底 | `repair_code_fences` 增加自动闭合：截断代码块追加 ` ``` ` | 修复 |

**Changes:**

| File | Change |
|------|--------|
| `wiki/content_guards.py` | 新增 `detect_unclosed_code_blocks` + `repair_unclosed_code_blocks` |
| `wiki/nodes/quality_gate.py` | 调用检测函数标记 heal hint |

**Code:**
```python
# content_guards.py
def detect_unclosed_code_blocks(content: str) -> bool:
    """Detect if content has unclosed fenced code blocks."""
    fence_count = len(re.findall(r"^```", content, re.MULTILINE))
    return fence_count % 2 != 0

def repair_unclosed_code_blocks(content: str) -> str:
    """Close unclosed fenced code blocks by appending closing fence."""
    if not detect_unclosed_code_blocks(content):
        return content
    return content.rstrip() + "\n```\n"
```

**Expected:** Code truncation ≥6 → 0。

**Tests:**
- New: `test_detect_unclosed_code_blocks`
- New: `test_repair_unclosed_code_blocks`

---

### F6: 壳域折叠增强 + Infra 重分类

**Problem:**
1. 3 个壳域（挚友关系、家族关系、家族广场）无 overview/topic，仅作容器，增加树深度到 4 层
2. data-type-mapping 挂在 family-task 下、task-execution-framework 挂在 family-square 下（基础设施错挂业务域）

**Root Cause:**
- `_collapse_empty_shells` 仅折叠「0 模块 + 单子节点」的壳域，对多子节点壳域不处理
- `infrastructure_slug_keywords` 不含 `type-mapping`、`data-source` 等关键词（V11 扩充不足）
- HAC 语义相似度将 TypeHandler/TaskExecutor 与家族模块聚类

**三层防御设计:**

| 层 | 手段 | 效果 |
|----|------|------|
| 预防 | 扩充 `infrastructure_slug_keywords` 覆盖 type-mapping、data-source、type-handler | 聚类时标记 infra |
| 检测 | `_collapse_empty_shells` 增强：多子节点壳域也折叠（子节点提升到父级） | 消除壳域 |
| 兜底 | `_review_subdomain_placement` 增加 infra→business 错挂规则 | 自动 reparent 到 root |

**Changes:**

| File | Change |
|------|--------|
| `core/config.py` | 扩充 `infrastructure_slug_keywords` |
| `wiki/nodes/graph_domain_decompose.py` | `_collapse_empty_shells` 增强：折叠多子节点壳域 |
| `wiki/nodes/graph_domain_decompose.py` | `_review_subdomain_placement` 增加 infra 错挂检测 |

**Code (_collapse_empty_shells 增强):**
```python
# graph_domain_decompose.py
def _collapse_empty_shells_v2(tree: dict, sections: list) -> dict:
    """Collapse shell sections that have no overview/modules, regardless of child count.
    
    A shell section is one where:
    - section_type == "business_domain"
    - No direct WikiPage children (only WikiSection children)
    - No overview page
    """
    shells_to_collapse = []
    for section in sections:
        if section.get("section_type") != "business_domain":
            continue
        has_pages = any(
            edge["parent_uid"] == section["uid"] and edge["child_type"] == "WikiPage"
            for edge in tree.get("edges", [])
        )
        if not has_pages:
            shells_to_collapse.append(section["uid"])
    
    for shell_uid in shells_to_collapse:
        _reparent_children_to_grandparent(tree, shell_uid)
    
    return tree
```

**Code (infra slug keywords 扩充):**
```python
# core/config.py — infrastructure_slug_keywords
infrastructure_slug_keywords: list[str] = Field(default=[
    # ... existing ...
    "type-mapping", "data-source", "type-handler", "type-conversion",
    "datasource", "serializer", "deserializer",
    "mybatis", "interceptor", "aspect",
])
```

**Expected:** Shell sections 3 → 0; Tree depth 4 → ≤3; Infra misplacement 2 → 0。

**Tests:**
- New: `test_collapse_multi_child_shell_sections`
- New: `test_infra_slug_detected_type_mapping`
- New: `test_infra_not_nested_under_business_domain`

---

### F7: Garbage Slug 修复

**Problem:** `family-square-back-door-serv-family-at-grou` 是截断的模块名拼接，完全不可读。

**Root Cause:** LLM 域命名直接使用了模块全名拼接并被 slug 长度限制截断。

**三层防御设计:**

| 层 | 手段 | 效果 |
|----|------|------|
| 预防 | 域命名 prompt 增加约束：slug 最大 5 个 segment，总长 ≤40 字符 | 防止过长 slug |
| 检测 | `_is_low_quality_slug` 增强：检测连续无分隔符字符串 >20 字符 | 标记垃圾 slug |
| 兜底 | 低质量 slug 触发 LLM 重命名 | 自动修复 |

**Changes:**

| File | Change |
|------|--------|
| `wiki/nodes/graph_domain_decompose.py` | slug 长度检查 + 自动触发 LLM 重命名 |
| `wiki/agent_prompts.py` | 域命名 prompt 增加 slug 长度约束 |

**Code (slug 质量检测增强):**
```python
# graph_domain_decompose.py
_MAX_SLUG_SEGMENTS = 5
_MAX_SLUG_LENGTH = 40

def _is_low_quality_slug(slug: str) -> bool:
    """Detect garbage slugs: too long, truncated, or lacking business semantics."""
    parts = slug.split("-")
    if len(parts) > _MAX_SLUG_SEGMENTS:
        return True
    if len(slug) > _MAX_SLUG_LENGTH:
        return True
    if any(len(p) > 15 for p in parts):
        return True
    if re.search(r"[a-z]{3,}[A-Z]", slug):
        return True
    return False
```

**Expected:** Garbage slug 1 → 0。

**Tests:**
- New: `test_long_slug_detected_as_low_quality`
- New: `test_truncated_slug_triggers_rename`

---

### F8: Topic 覆盖率提升至 90%+

**Problem:** 4 个域（es-user-search, im-system-message, prize-distribution, user-relation-management）仍无 topic。

**Root Cause:** 这些域模块数可能 <3（V11 F1 force_override 门槛），或模块被 infra 过滤。

**三层防御设计:**

| 层 | 手段 | 效果 |
|----|------|------|
| 预防 | `plan_topics_min_modules` 从 3 降至 **2** | 2 模块域也进入规划 |
| 检测 | quality_gate 检测域级覆盖率：有 overview 但无 topic 的域标记 warning | 审计可见 |
| 兜底 | `force_override` 门槛从 ≥3 降至 **≥2** | 2 模块域也保证 topic |

**Changes:**

| File | Change |
|------|--------|
| `wiki/domain_doc_agent.py` | `plan_topics_min_modules` 3→2; force_override ≥3→≥2 |
| `wiki/nodes/quality_gate.py` | 域级覆盖率 warning |

**Expected:** Domains without topics 4 → 0; Coverage 76.5% → ≥90%。

**Tests:**
- Update: `test_topic_force_override_when_modules_gte_3` → include 2-module case
- New: `test_2_module_domain_gets_topic`

---

## 3. Implementation Plan

### Phase 1: Content Quality (F1 + F2 + F4 + F5) — ~120 lines diff

| Step | Fix | Estimated Lines | 三层覆盖 |
|------|-----|-----------------|-----------|
| 1.1 | F1: 机械拆分语义标题 | 25 lines | **预防** |
| 1.2 | F1: quality_gate Part N 检测 | 8 lines | 检测 |
| 1.3 | F1: finalize Part N fallback | 15 lines | 兜底 |
| 1.4 | F2: stub 消除 — agent skip + finalize reject | 15 lines | 预防+兜底 |
| 1.5 | F4: H2 trailing whitespace strip | 5 lines | 检测 |
| 1.6 | F4: 缺失概述检测 | 8 lines | 检测 |
| 1.7 | F5: 代码块闭合检测 + 修复 | 20 lines | 检测+兜底 |
| 1.8 | Tests for F1/F2/F4/F5 | ~60 lines | — |

**Verification:** Run tests → deploy → regenerate wiki → `scripts/audit_wiki_data.py`

### Phase 2: Navigation & Structure (F3 + F6 + F7 + F8 + F9 + F10) — ~200 lines diff

| Step | Fix | Estimated Lines | 三层覆盖 |
|------|-----|-----------------|-----------|
| 2.1 | F3: finalize 全局标题去重 | 25 lines | 检测 |
| 2.2 | F3: tree_linker 标题唯一校验 | 10 lines | 兜底 |
| 2.3 | F6: 壳域折叠增强 | 30 lines | 兜底 |
| 2.4 | F6: infra slug keywords 扩充 | 5 lines | 预防 |
| 2.5 | F6: infra 错挂 reparent 规则 | 15 lines | 兜底 |
| 2.6 | F7: slug 长度/质量检测增强 | 15 lines | 检测 |
| 2.7 | F8: min_modules 3→2 + force_override 门槛降低 | 5 lines | 预防+兜底 |
| 2.8 | F9: wikilink 白名单注入 + finalize 增强 | 25 lines | 预防+兜底 |
| 2.9 | F10: 主题聚合接入管线 | 15 lines | 检测 |
| 2.10 | Tests for F3/F6/F7/F8/F9/F10 | ~100 lines | — |

**Verification:** Run tests → deploy → regenerate wiki → audit

### Phase 3: 大域上下文溢出修复 (F11) — ~180 lines diff

| Step | Fix | Estimated Lines | 三层覆盖 |
|------|-----|-----------------|-----------|
| 3.1 | F11a: `_filter_baseline_for_topic()` 智能过滤 | 35 lines | **预防** |
| 3.2 | F11b: `WorkingMemory.slice_for_modules()` 模块切片 | 30 lines | **预防** |
| 3.3 | F11c: Overview baseline 上限 8K→16K | 5 lines | **预防** |
| 3.4 | F11d: 大域 Explore 自适应扩容 + config flags | 20 lines | 检测 |
| 3.5 | F11e: Per-topic 薄 Memory 检测 + 补充探索 | 15 lines | 兜底 |
| 3.6 | F11: `_write_with_outline` 集成 baseline 过滤 + memory 切片 | 15 lines | 预防 |
| 3.7 | Tests for F11 | ~60 lines | — |

**Verification:** 选取大域（50+ 模块）单域重新生成 → 对比 topic 代码片段数量和质量

---

## 4. Verification Criteria

Post-deployment audit targets (via `scripts/audit_wiki_data.py`):

| Metric | V26 Baseline | Phase 1 | Phase 2 |
|--------|--------------|---------|---------|
| Part N naming | 66.7% (22/33) | **<15%** | <15% |
| Stub topics | 2 | **0** | 0 |
| Duplicate titles | 2 组 | 2 | **0** |
| H2 trailing spaces | 3 | **0** | 0 |
| Code truncation | ≥6 | **0** | 0 |
| Missing 概述 | 4 | **≤1** | ≤1 |
| Shell sections | 3 | 3 | **0** |
| Tree depth | 4 | 4 | **≤3** |
| Infra misplacement | 2 | 2 | **0** |
| Garbage slugs | 1 | 1 | **0** |
| Domains without topics | 4 | 4 | **0** |
| Topic coverage | 76.5% | 76.5% | **≥90%** |
| Dangling wikilinks | ≥1 | ≤1 | **0** |
| Separate family L1 domains | 2 | 2 | **1 (Hub)** |
| L1 domain count | 14 | 14 | **10-12** |
| **大域 topic 代码片段均匀度** | 首/末 topic 差 3x | — | **差异 <1.5x** |
| **Topic 薄 Memory 触发率** | N/A | N/A | **<10%** |

**综合评分目标:** V26 5.5/10 → Phase 1 ≥6.5 → Phase 2 ≥7.5 → Phase 3 ≥8.0

---

## 5. Risk Matrix

| Fix | Risk | Mitigation |
|-----|------|-----------|
| F1 语义标题 | 模块名本身无业务语义时标题仍不理想 | Fallback 保留 Part N 并在 quality_gate 标记 |
| F2 stub 消除 | Agent 频繁失败导致 topic 缺失 | 仅 skip placeholder，不阻止重试 |
| F3 标题去重 | 追加域名后缀可能使标题过长 | 仅在重复时追加，且截断到 50 字符 |
| F5 代码块修复 | 自动闭合可能引入不完整代码展示 | 仅追加 ` ``` `，不修改已有内容 |
| F6 壳域折叠 | 折叠后子域丢失分组语义 | 仅折叠无内容壳域，保留有 overview 的分组 |
| F7 slug 重命名 | LLM 重命名可能引入新的质量问题 | 经 _is_low_quality_slug 二次校验 |
| F8 min_modules=2 | 2 模块域的 topic 可能过于碎片 | quality_gate min_chars 仍然活跃 |
| F11 Memory 切片 | 模块名前缀匹配可能遗漏变体命名 | fallback 检查 entry 全文是否包含模块名 |
| F11 补充探索 | 补充探索增加 LLM 成本和延迟 | 仅在 <2000 chars 时触发，且限制 2 轮 |
| F11 Explore 扩容 | 大域超时风险 | domain_agent_timeout_sec=600s 足够；扩容有上限 cap |

---

## 6. Design Decisions Record

| Decision | Chosen | Alternative | Rationale |
|----------|--------|-------------|-----------|
| Part N 消除策略 | 模块簇语义标题 + fallback | LLM 重命名所有 Part N | 低成本且保留 fallback |
| Stub 消除 | finalize hard-reject < 200 | Agent 重试直到成功 | 简单可靠，不增加 LLM 成本 |
| 标题去重 | finalize 追加域名后缀 | 要求 Agent 生成唯一标题 | Agent 不感知全局标题 |
| 壳域折叠 | 多子节点壳域也折叠 | 为壳域生成 hub overview | 减少复杂度，hub 是 V13+ |
| Infra 重分类 | slug keywords + reparent | 改 HAC 聚类算法 | 风险低，与 V11 F5-R 一致 |
| Topic 门槛 | min_modules 3→2 | 所有域强制 topic | 平衡覆盖率与质量 |
| 大域上下文策略 | 零成本过滤优先 + 按需补充探索 | per-topic 独立全量 explore | 零成本过滤解决 80% 问题；全量 explore 成本 4-8x |
| Memory 切片粒度 | 按 topic 模块名过滤 | 按 topic 语义相关性 (embedding) | 模块名过滤准确且零 LLM 调用 |
| Baseline 上限 | overview 16K / topic 动态过滤 | 统一 32K | topic 不需要全量模块信息 |

---

## 7. 补充发现（V26 审计反馈轮）

### F9: Plan 上下文注入 + Wikilink 幻觉修复 + Schema 对齐

**Problem (三重):**
1. Topic "## 相关主题" 引用不存在的 wikilink（如 Part 5/6，实际只有 Part 1-4）
2. 各 topic 对其他 Part 的描述与实际内容不匹配（Part 4 说 Part 1 是"基础模型与数据结构设计"，实际是"互动行为触发亲密值增长"）
3. `TopicPlanOutput` schema 字段 `module_keys` 与 prompt/parser 的 `modules` 不一致，导致 plan 隐性失败

**Root Cause (代码级追踪):**
1. **Write 阶段丢失跨 topic 上下文**：`_write_with_outline` 逐个写 topic，每个 topic 只注入自身的 `scope_text`，不含 sibling topic 的标题、模块列表和描述
2. **LLM 靠猜测描述 sibling**：全域 baseline 有模块列表，但 LLM 不知道哪些模块在哪个 Part，只能编造
3. **Schema 不一致**：`TopicItem.module_keys` vs prompt/parser 的 `modules`，导致解析为空列表→plan 退化→机械 Part N
4. **前端用标题当 path**：`wikilinkParser.ts` 把标题传给 API 按 path 查，导致所有 wikilink 可能失效

**关键洞察:** 当前系统**已经是** plan→execute 模式（Explore → Plan → Write），问题不在缺少 plan，而在 **Write 阶段未把 plan 传递给 LLM**。类似 Codex/Copilot 的做法，需要在每个 topic 写作时注入完整 plan 作为全局蓝图。

**三层防御设计:**

| 层 | 手段 | 效果 |
|----|------|------|
| **预防** | `_write_with_outline` 注入完整 plan 表（所有 sibling 的标题+模块+描述） | LLM 知道每个 topic 的实际模块归属 |
| **预防** | 修复 `TopicItem` schema 对齐（`modules` + `description`） | 提高 LLM plan 成功率 |
| 检测 | quality_gate 对照 outline.topics 检查 wikilink 有效性 | 发现虚构链接 |
| 兜底 | finalize 增强 `_remove_invalid_wikilinks` 支持短标题变体匹配 | 清除漏网链接 |

**Changes:**

| File | Change |
|------|--------|
| `wiki/domain_doc_agent.py` | `_write_with_outline`: 注入完整 plan context |
| `wiki/domain_doc_agent.py` | 新增 `_format_full_plan_context()` helper |
| `wiki/domain_doc_agent.py` | `_parse_topic_outline`: 兼容 `module_keys` |
| `wiki/llm_schemas.py` | `TopicItem` 增加 `description` 字段，统一 `modules` |
| `wiki/nodes/finalize.py` | `_remove_invalid_wikilinks` 增强 |

**Code (核心 — 完整 Plan 上下文注入):**
```python
# domain_doc_agent.py: 新增
def _format_full_plan_context(outline: DomainTopicOutline, current: TopicPlan) -> str:
    """Format complete topic plan for injection into each topic's writing context."""
    lines = ["--- 域主题规划（全局蓝图）---"]
    for i, t in enumerate(outline.topics, 1):
        marker = " ← 当前撰写" if t.title == current.title else ""
        mods = ", ".join(t.modules[:5])
        desc = t.description or "(无描述)"
        lines.append(f"{i}. **{t.title}**{marker}")
        lines.append(f"   模块: {mods}")
        lines.append(f"   描述: {desc}")
    
    sibling_titles = [t.title for t in outline.topics if t.title != current.title]
    if sibling_titles:
        lines.append("")
        lines.append("「## 相关主题」节只允许引用以下已确认的同域主题标题，")
        lines.append("并根据上方模块列表如实描述（禁止引用或编造其他不存在的主题）：")
        for t in sibling_titles:
            lines.append(f"- {t}")
    
    return "\n".join(lines)

# _write_with_outline 内，scope_text 后追加:
plan_context = _format_full_plan_context(outline, topic)
topic_context = f"{baseline_context}\n\n{scope_text}\n\n{plan_context}" + glossary_section
```

**Code (Schema 对齐):**
```python
# wiki/llm_schemas.py — 修复 TopicItem
class TopicItem(BaseModel):
    title: str
    slug: str
    modules: list[str] = Field(default_factory=list)
    description: str = ""

# wiki/domain_doc_agent.py — _parse_topic_outline 兼容
modules = t.get("modules") or t.get("module_keys") or []
```

**Expected:**
- Wikilink 幻觉完全消除
- 相关主题描述与实际内容一致（LLM 可见每个 topic 的模块归属）
- Plan 成功率提升（schema 对齐减少隐性 parse 失败）

**Tests:**
- New: `test_write_with_outline_injects_full_plan`
- New: `test_format_full_plan_context_marks_current`
- New: `test_parse_topic_outline_accepts_module_keys`
- New: `test_topic_item_schema_has_description`
- New: `test_finalize_removes_variant_wikilinks`

---

### F10: 主题聚合接入管线（家族域合并）

**Problem:** `family-event-processing`（家族事件）和 `family-task`（家族关系）作为两个独立 L1 域存在，业务上都属于家族体系。

**Root Cause (代码级追踪):**
1. HAC 按模块 embedding 聚类，事件处理模块与任务/广场模块语义距离大，被分到不同 cluster
2. `skip_llm_merge_when_corrector_enabled=True` 跳过了 `_merge_domains_by_llm`
3. `GraphSemanticCorrector` 仅做 flat merge 不建 L1 父域，且 prompt 偏保守（"If unsure, do NOT merge"）
4. `aggregate_domains_recursive`（主题聚合）功能已实现但**未接入 LangGraph 管线**，仅在手动 `reorganize_domains()` 中使用
5. `_collapse_empty_shells` 仅折叠单子节点壳域，`family-task`（2 子节点）不折叠

**Changes:**

| File | Change |
|------|--------|
| `wiki/nodes/graph_domain_decompose.py` | Step 8 后调用 `aggregate_domains_recursive` |
| `wiki/pipeline_graph.py` | 确保聚合结果传入后续节点 |

**Code (管线内接入主题聚合):**
```python
# graph_domain_decompose.py: graph_driven_domain_decompose_node 内，Step 8 后
from wiki.domain_merger import aggregate_domains_recursive

if llm and len(domain_tree) > wiki_cfg.theme_aggregation_min_domains:
    domain_tree = await aggregate_domains_recursive(
        domain_tree, llm,
        min_group_size=2,
    )
    log.info("theme_aggregation_applied", l1_count=len(domain_tree))
```

**Expected:** `family-event-processing` + `family-task` → 归入 L1 Hub「家族」；L1 数量 14→10-12。

**Tests:**
- Existing: `tests/wiki/test_domain_theme_aggregation.py`（验证已有功能）
- New: `test_family_domains_aggregated_to_hub`
- New: `test_theme_aggregation_in_pipeline`

---

### F11: 大域上下文溢出修复（Topic 代码信息丢失）

**Problem:** 当域包含 50+ 模块时，overview 和 topic 页面出现代码信息丢失、内容单薄。例如"亲密度关系"域的后几个 Part 代码示例明显少于前几个。

**Root Cause (代码级追踪 — 4 个瓶颈):**

| 瓶颈 | 位置 | 限制值 | 影响 |
|------|------|--------|------|
| **baseline 硬截断** | `page_agent.write()` L844/851 | `baseline_context[:8000]` | 50 模块域的模块列表 ~5K-8K chars，scope_text 加入后被截断，后半模块不可见 |
| **Explore 轮次上限** | `config.py` L300-301 | 8 轮 × 30 调用 = 240 次 | 超过 ~80-120 模块的域无法被完全探索 |
| **WorkingMemory 上限** | `page_agent.py` L220 | `MAX_TOTAL_CHARS = 200_000` | 最多约 33 个完整代码片段 (200K / 6K per snippet) |
| **所有 topic 共享 Memory** | `_write_with_outline()` L960 | 无 per-topic 过滤 | 末尾 topic 对应的模块代码可能已被 relevance-based eviction 丢弃 |

**完整上下文传递链路:**
```
_build_baseline() → 模块清单+拓扑 (2K-10K chars)
    ↓
Explore Phase → Agent 使用工具查询代码 (max 8轮 × 30调用 = 240次)
    ↓                              ↓
    baseline_context[:8000]    WorkingMemory (max 200K chars)
    ↓                              ↓
Write Phase → baseline[:8000] + memo_section → LLM 生成页面
    ↓
Topic Write → 所有 topic 共享同一份 memory，只有 scope_text 不同
```

**三层防御设计:**

| 层 | 手段 | LLM 成本 | 效果 |
|----|------|---------|------|
| **预防 (F11a)** | Topic baseline 智能过滤：只保留当前 topic 的模块和拓扑边 | **0** | 8 模块 topic 的 baseline ~1.2K vs 原 8K 截断 |
| **预防 (F11b)** | WorkingMemory 按 topic 模块切片：code_snippets/call_chains 按模块名过滤 | **0** | 每个 topic 获得聚焦代码，不受 200K 上限压力 |
| **预防 (F11c)** | Overview 页 baseline 上限 8K→16K | **0** | 大域 overview 可见完整模块列表 |
| **检测 (F11d)** | 大域自适应 Explore 扩容：20-40 模块 +2 轮/+10 调用；40+ 模块 +4 轮/+15 调用 | **按需** | 大域获得更充分的探索预算 |
| **兜底 (F11e)** | Per-topic 薄 Memory 检测：`topic_memory._total_chars() < 2000` 时触发 2 轮补充探索 | **条件触发** | 共享探索漏掉的模块得到补救 |

**Changes:**

| File | Change |
|------|--------|
| `wiki/page_agent.py` | `WorkingMemory.slice_for_modules()` 新增方法；overview 写入时 baseline 上限 8K→16K |
| `wiki/domain_doc_agent.py` | 新增 `_filter_baseline_for_topic()`；`_write_with_outline` 使用过滤后的 baseline + 切片 memory |
| `wiki/nodes/domain_compose.py` | 大域自适应 Explore 参数缩放 |
| `core/config.py` | 新增 `explore_scale_threshold_medium=20`, `explore_scale_threshold_large=40` |

**Code (F11a — Topic Baseline 智能过滤):**
```python
# domain_doc_agent.py: 新增
def _filter_baseline_for_topic(baseline: str, topic_modules: set[str]) -> str:
    """Filter baseline to only include topic-relevant modules and edges.
    
    For a 50-module domain, a topic with 8 modules shrinks baseline from
    ~8000 chars to ~1200 chars, leaving room for scope_text and plan context.
    """
    lines = baseline.split("\n")
    result: list[str] = []
    in_module_list = False
    in_topology = False

    for line in lines:
        if line.startswith("### 模块列表"):
            in_module_list = True
            in_topology = False
            result.append(line)
            continue
        if line.startswith("### 模块依赖拓扑"):
            in_module_list = False
            in_topology = True
            result.append(line)
            continue
        if line.startswith("### ") or line.startswith("## "):
            in_module_list = False
            in_topology = False
            result.append(line)
            continue

        if in_module_list:
            if line.startswith("- **"):
                mod_name = line.split("**")[1] if "**" in line else ""
                if mod_name in topic_modules:
                    result.append(line)
            else:
                result.append(line)
        elif in_topology:
            if line.startswith("- ") and "→" in line:
                parts = line[2:].split("→")
                src = parts[0].strip()
                tgt = parts[1].strip() if len(parts) > 1 else ""
                if src in topic_modules or tgt in topic_modules:
                    result.append(line)
            else:
                result.append(line)
        else:
            result.append(line)

    return "\n".join(result)
```

**Code (F11b — WorkingMemory 模块切片):**
```python
# page_agent.py: WorkingMemory 新增方法
def slice_for_modules(self, modules: set[str]) -> WorkingMemory:
    """Create a filtered copy containing only entries relevant to given modules."""
    module_lower = {m.lower() for m in modules}

    def _matches(entry: str) -> bool:
        m = _MODULE_PREFIX_RE.match(entry)
        if m:
            prefix = m.group(1).strip()
            name = prefix.split(" @ ")[0].strip() if " @ " in prefix else prefix
            return name.lower() in module_lower
        entry_lower = entry.lower()
        return any(mod in entry_lower for mod in module_lower)

    sliced = WorkingMemory()
    sliced.code_snippets = [s for s in self.code_snippets if _matches(s)]
    sliced.discovered_call_chains = [
        c for c in self.discovered_call_chains
        if any(m.lower() in c.lower() for m in modules)
    ]
    sliced.discovered_implementations = [
        i for i in self.discovered_implementations
        if any(m.lower() in i.lower() for m in modules)
    ]
    sliced.discovered_callers = [
        c for c in self.discovered_callers
        if any(m.lower() in c.lower() for m in modules)
    ]
    sliced.search_findings = list(self.search_findings)
    sliced.wiki_references = list(self.wiki_references)
    sliced.relevant_modules = modules
    return sliced
```

**Code (F11c — _write_with_outline 集成):**
```python
# domain_doc_agent.py: _write_with_outline 内修改
for topic in outline.topics:
    topic_modules = set(topic.modules)
    # F11a: 过滤 baseline 到 topic 相关模块
    topic_baseline = _filter_baseline_for_topic(baseline_context, topic_modules)
    # F11b: 切片 memory 到 topic 相关代码
    topic_memory = memory.slice_for_modules(topic_modules)
    
    # F11e: 薄 Memory 检测 — 如果切片后代码不足，触发补充探索
    if topic_memory._total_chars() < 2000 and topic.modules:
        log.warning("topic_supplemental_explore_triggered",
                    topic=topic.title, chars=topic_memory._total_chars())
        supplemental = await self._page_agent.explore(
            module_names=topic.modules,
            domain_name=self.domain_name,
            baseline_context=topic_baseline,
            memory=topic_memory,
        )
        topic_memory = supplemental

    scope_text = f"--- 主题范围 ---\n..."  # existing scope_text logic
    topic_context = f"{topic_baseline}\n\n{scope_text}" + glossary_section
    topic_content = await self._page_agent.write(
        self.domain_name, topic_context, topic_memory, page_type="topic"
    )
```

**Code (F11d — 大域自适应 Explore 扩容):**
```python
# nodes/domain_compose.py: 在 create_domain_doc_agent 前
def _scale_explore_params(
    module_count: int, wiki_cfg: AppWikiFlags
) -> tuple[int, int]:
    """Scale explore rounds and tool calls for large domains."""
    base_rounds = wiki_cfg.domain_agent_explore_max_rounds
    base_calls = wiki_cfg.domain_agent_explore_max_tool_calls
    threshold_m = wiki_cfg.explore_scale_threshold_medium  # 20
    threshold_l = wiki_cfg.explore_scale_threshold_large   # 40

    if module_count > threshold_l:
        return min(base_rounds + 4, 16), min(base_calls + 15, 50)
    elif module_count > threshold_m:
        return min(base_rounds + 2, 12), min(base_calls + 10, 40)
    return base_rounds, base_calls
```

**Expected:**
- Overview 页面：完整模块可见性（16K baseline vs 原 8K）
- Topic 页面：聚焦代码上下文（不被兄弟 topic 稀释），末尾 topic 质量与首尾一致
- 大域（50+ 模块）：Explore 覆盖率 ~60%→90%+
- 小域（<20 模块）：零额外开销（所有缩放均有条件）

**Tests:**
- New: `test_filter_baseline_for_topic_keeps_relevant_modules`
- New: `test_filter_baseline_for_topic_keeps_relevant_edges`
- New: `test_working_memory_slice_for_modules`
- New: `test_slice_empty_modules_returns_empty_memory`
- New: `test_scale_explore_params_large_domain`
- New: `test_scale_explore_params_small_domain_unchanged`
- New: `test_topic_supplemental_explore_triggers_on_thin_memory`

---

## 8. 超出 V12 范围的改进方向（Future）

以下问题被四个审计子代理识别，但改动范围大或需要架构级调整，列为后续迭代：

| 问题 | 建议方向 | 原因 |
|------|---------|------|
| **模板同质化**（17 overview 相同 H2 结构） | 按域类型使用不同模板（业务域 vs 基础设施 vs 运营触点） | 需重构 prompt 体系 |
| **"是什么"多于"为什么"** | 在 prompt 中强制"业务不变量"和"设计决策"段 | 依赖 LLM 理解能力 |
| **L1 主题分组**（14→4-5个Hub） | 引入"社交关系/家族体系/用户服务/消息触达/基础能力"分类 | 需要 WikiSpace 层改造 |
| **域合并建议**（gift+prize, im+quick, dealer+profile） | 在 graph_domain_decompose 中增加业务线聚合规则 | 影响面大 |
| **Topic slug 语义化** | topic slug 用业务名替代 Java 类名 | 需改 topic 命名管线 |
