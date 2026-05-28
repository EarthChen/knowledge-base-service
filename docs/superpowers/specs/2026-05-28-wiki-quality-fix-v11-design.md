# Wiki Quality Fix V11 Design Spec (Revised)

**Date:** 2026-05-28
**Status:** Proposal (Awaiting Approval)
**Audit Base:** V25 (2026-05-28, `data/wiki-audit-v25.json`)
**Supersedes:** V7/V8/V9 specs (deleted), extends V10 design (retained as reference)
**Revision:** R2 — 纳入根治性分析 + 包路径感知聚类 + DomainAnchor 重新定位

---

## 1. Background & Goals

### V10 修复效果验证

| V10 Fix | 部署状态 | V25 实测效果 |
|---------|---------|-------------|
| F1 H2白名单 | ✅ 已部署 | ✅ Meta H2: 2→**0** |
| F2 Blockquote清洗 | ✅ 已部署 | ✅ Blockquote残留: →0 |
| F3 Prompt严禁元章节 | ✅ 已部署 | ✅ 英文模板/建议: →0 |
| F4 JSON Schema+strict | ✅ 已部署 | ✅ 结构化输出生效，无用输出消除 |
| F5 Slug粘连(字典分词) | ⚠ 部分 | ⚠ `relationfamily`已消失，新增 dedup 重复段 bug |
| F6 双重fence合并 | ✅ 已部署 | ⚠ 24%→14% 略改善 |
| F7 Topic门槛下调 | ❌ 未部署 | ❌ 82%→91% 恶化 |
| F8 壳域hard-reject | ✅ 已部署(finalize) | ❌ tree_linker bypass → 1→4 恶化 |
| F9 域锚定保护 | ❌ 未部署 | ❌ 无保护 |
| F11 cn_ratio硬检查 | ❌ 仅topic | ❌ overview无门禁 |

**结论:** JSON Schema 组合拳 (F1-F4) 彻底根治了 meta 残留。但 F7-F11 未部署或被架构性绕过。

### V25 Current State

| Metric | Value | Target |
|--------|-------|--------|
| Topic coverage | 9% (2/22 domains) | ≥40% |
| Shell domains (<200 chars) | 4 | 0 |
| Slug repeated segments | 2 | 0 |
| Misplaced domains | 2 | 0 |
| Low cn_ratio pages (<0.25) | 6 | 0 |
| Code-heavy overviews (cn<0.15) | 1 (relation-service) | 0 |
| Composite score | 5.6/10 | ≥7.5 |

### Root Causes (Code-Level)

| Problem | Root Cause | Code Location |
|---------|-----------|---------------|
| Topic coverage 9% | Prompt "≤5→no split" + mechanical needs ≥8 modules | `agent_prompts.py:314` + `domain_doc_agent.py:666` |
| 4 shell domains | tree_linker persists after finalize rejects | `tree_linker.py:775-814` |
| Slug repetition | dedup semantic suffix has no uniqueness check | `graph_domain_decompose.py:678-688` |
| Misplaced domains | HAC 纯 embedding 相似度 + 无包路径约束 | `graph_domain_decompose.py` clustering |
| No overview cn gate | Intentional exclusion in 3 code paths | `quality_gate.py:281`, `finalize.py:457`, `heal.py:62` |
| Infra modules mixed in | `infrastructure_slug_keywords` 不完整 | `config.py:333` |

### 设计原则

每个修复必须满足**三层纵深防御**：

| 层 | 作用 | 具体手段 |
|-----|------|---------|
| **预防层** | 从源头阻止坏数据产生 | Prompt约束 / Schema约束 / 聚类约束 |
| **检测层** | 发现并修复已产生的问题 | quality_gate / content_guards / heal |
| **兜底层** | 确保坏数据不落库 | finalize hard-reject / tree_linker也经finalize |

---

## 2. Fix Design (F1–F7, Revised)

### F1: Topic Coverage Recovery + 硬性保证

**Problem:** 91% domains have zero topics. Triple threshold (min_modules=3 + LLM ≤5 + mechanical needs ≥8) blocks 4-7 module domains.

**三层防御设计:**

| 层 | 手段 | 效果 |
|----|------|------|
| 预防 | Prompt "≤2 modules → no split" (降低LLM拒绝率) | 3-5模块域进入LLM规划 |
| 预防 | chunk_size 5→3 (mechanical fallback降低门槛) | 4+模块域至少产出1 topic |
| **兜底** | **LLM返回should_split=false时，若modules≥3则强制覆盖** | **硬性保证** |

**Changes:**

| File | Change |
|------|--------|
| `wiki/agent_prompts.py` | SYSTEM_TOPIC_PLANNER: "≤5 modules → should_split=false" → "≤2 modules" |
| `wiki/domain_doc_agent.py` | `_build_mechanical_topic_split`: `chunk_size = 5` → `chunk_size = 3` |
| `wiki/domain_doc_agent.py` | Plan result校验: LLM返回no-split且modules≥3时强制override |

**Code (硬性保证):**
```python
# domain_doc_agent.py: plan_topics 返回后的校验层
plan = await self._plan_topics_llm(modules, domain_slug, ...)
if not plan.should_split and len(modules) >= 3:
    plan.should_split = True
    log.info("topic_force_override", domain=domain_slug, modules=len(modules),
             reason="modules>=3 requires at least 1 topic")
```

**根治度:** 95%。≥3模块的域硬性保证有topic，不依赖LLM判断。

**Expected:** Coverage 9% → 40%+ (所有3+模块域产生topics)。

**Tests:**
- Update `test_plan_topics_force_split_at_default_threshold_six` to verify 4-module domain splits
- New: `test_topic_force_override_when_modules_gte_3`
- New: `test_no_override_when_modules_lt_3`

---

### F2: Slug Repeated Segment Fix + 域名质量校验

**Problem:** `_dedup_parallel_naming_results` semantic suffix branch appends without checking if `new_slug` already exists in `seen`. Additionally, garbage module names like `ultronult` pass through as slugs.

**三层防御设计:**

| 层 | 手段 | 效果 |
|----|------|------|
| 预防 | 域命名时检测纯模块名 slug 并触发 LLM 重命名 | 源头避免垃圾 slug |
| 检测 | dedup 加 uniqueness loop + segment 查重 | 消除重复段 |
| 兜底 | `_dedupe_slug_segments` 作最终清洗 | 任何漏网重复段被清理 |

**Changes:**

| File | Change |
|------|--------|
| `wiki/nodes/graph_domain_decompose.py` | Add uniqueness loop + segment dedup check |
| `wiki/nodes/graph_domain_decompose.py` | Add slug quality validation in naming results |

**Code (uniqueness + segment dedup):**
```python
# In _dedup_parallel_naming_results, after new_slug = f"{slug}-{suffix}"
counter = 0
base_new = new_slug
while new_slug in seen:
    counter += 1
    new_slug = f"{base_new}-{counter}"

# Final cleanup pass on all slugs:
def _dedupe_slug_segments(slug: str) -> str:
    """Remove consecutive repeated segments: a-b-b → a-b"""
    parts = slug.split("-")
    result = [parts[0]]
    i = 1
    while i < len(parts):
        for seg_len in range(1, (len(parts) - i) // 1 + 1):
            if i + seg_len <= len(parts) and parts[i:i+seg_len] == result[-seg_len:]:
                i += seg_len
                break
        else:
            result.append(parts[i])
            i += 1
    return "-".join(result)
```

**Code (slug quality validation):**
```python
# In naming results post-processing:
_GARBAGE_SLUG_PATTERN = re.compile(r"^[a-z]{2,}[A-Z]|^[a-z]+\d{3,}")

def _is_low_quality_slug(slug: str) -> bool:
    """Detect module-name-like slugs lacking business semantics."""
    parts = slug.split("-")
    return any(_GARBAGE_SLUG_PATTERN.match(p) for p in parts) or len(slug) < 4
```

**根治度:** 95%。重复段彻底消除，垃圾slug检测覆盖已知模式。

**Tests:**
- New: `test_dedup_semantic_suffix_uniqueness`
- New: `test_dedupe_slug_segments`
- New: `test_garbage_slug_detection`

---

### F3: Overview cn_ratio Gate

**Problem:** `quality_gate` and `finalize` explicitly skip cn_ratio checks for `domain_overview`. relation-service (13846 chars, cn=10%) publishes freely.

**三层防御设计:**

| 层 | 手段 | 效果 |
|----|------|------|
| 预防 | Prompt中加"代码块总数不超过5个，每块不超过20行" | Agent从源头控制代码量 |
| 检测 | quality_gate overview cn heal trigger (0.20) | 触发重写 |
| 兜底 | finalize overview cn hard-reject (0.15) | 极端case不落库 |

**Changes:**

| File | Change |
|------|--------|
| `wiki/agent_prompts.py` | SYSTEM_OVERVIEW_WRITER 追加代码量约束 |
| `wiki/nodes/quality_gate.py` | Add overview cn_ratio heal trigger (threshold 0.20) |
| `wiki/nodes/finalize.py` | Add overview cn_ratio hard-reject (threshold 0.15) |
| `wiki/nodes/heal.py` | Remove early return for non-topic pages (cn_ratio path) |

**Code (Prompt预防):**
```python
# wiki/agent_prompts.py — SYSTEM_OVERVIEW_WRITER 追加
"""
- 代码块总数不超过 5 个，每个代码块不超过 20 行
- 代码仅用于辅助说明核心逻辑，必须有中文说明包裹
- 禁止将方法签名列表作为代码块输出
"""
```

**Code (quality_gate.py):**
```python
if page_type == "domain_overview" and _is_chinese_lang(effective_lang):
    cn_ratio = _check_cn_ratio(page_dict)
    if cn_ratio < 0.20:
        content_issues.append(f"overview_low_cn_ratio: cn={cn_ratio:.3f} < 0.20")
```

**Code (finalize.py):**
```python
if is_overview and not is_topic_index and _is_chinese_lang(content_language):
    cn_ratio = compute_cn_ratio(content)
    if cn_ratio < 0.15:
        log.warning("overview_cn_ratio_rejected", path=path, cn_ratio=cn_ratio)
        updated_pages.append({**page, "content": "", "__rejected__": True})
        continue
```

**根治度:** 95%。Prompt预防 + 检测heal + 兜底reject 三层覆盖。

**Tests:**
- Update `test_low_cn_ratio_overview_not_rejected` → `test_low_cn_ratio_overview_rejected_below_015`
- New: `test_overview_cn_ratio_heal_triggered`

---

### F4: tree_linker Shell Domain Gate (经 finalize 管道)

**Problem:** tree_linker writes shell overviews (118-157 chars) to graph after finalize rejects them, bypassing all quality gates.

**三层防御设计:**

| 层 | 手段 | 效果 |
|----|------|------|
| 预防 | tree_linker生成内容质量提升(未来迭代) | — |
| 检测 | tree_linker生成后必须经`_sanitize_published_content` | H2白名单+strip生效 |
| 兜底 | sanitize后<200字则不写入 | 壳域不落库 |

**Changes:**

| File | Change |
|------|--------|
| `wiki/tree_linker.py` | 生成后走sanitize管道 + 长度校验 |

**Code:**
```python
# tree_linker.py: 在 persist_pages_to_graph 调用前
from wiki.nodes.finalize import _sanitize_published_content
from wiki.content_guards import strip_h1_title

_TREE_LINKER_MIN_OVERVIEW_CHARS = 200

overview_pages_filtered = []
for p in overview_pages:
    content = p.get("content", "")
    content = strip_h1_title(content)
    content = _sanitize_published_content(content, page_type="domain_overview")
    if len(content.strip()) >= _TREE_LINKER_MIN_OVERVIEW_CHARS:
        overview_pages_filtered.append({**p, "content": content})
    else:
        log.info("tree_linker_shell_filtered", slug=p.get("slug"), chars=len(content))

if overview_pages_filtered:
    await self._persistence.persist_pages_to_graph(overview_pages_filtered, ...)
```

**与原方案区别:** 不仅仅过滤<500字，而是**让tree_linker生成的内容也经过与管线相同的sanitize**。这确保H2白名单、cn_ratio逻辑等所有质量规则对tree_linker同样生效。

**根治度:** 98%。tree_linker不再是质量门禁的"旁路"。

**Tests:**
- New: `test_tree_linker_content_passes_sanitize`
- New: `test_tree_linker_filters_short_after_sanitize`
- New: `test_tree_linker_strips_h1`

---

### F5-R: 增强 GraphSemanticCorrector 上下文 + 兜底规则 (Revised)

> **Revision Note:** 原F5使用硬编码规则"打地鼠"，原方案中的包路径距离修正存在"同包=同业务"假设不普适的问题（如层次包项目、大泥球项目）。
> 修正为：**不改变 HAC 聚类逻辑，而是增强已有 LLM 纠错环节(GraphSemanticCorrector)的上下文**，让 LLM 综合包结构+调用关系+模块描述做出判断。

**Problem:** HAC聚类仅使用embedding相似度。`GraphSemanticCorrector`(已有LLM纠错步骤)上下文不足，无法发现 family-task 错挂 intimacy、data-type-conversion 混入业务域等问题。

**设计原则:** HAC做粗分(批量、确定性)，LLM做精调(语义理解)。不替代HAC，只增强LLM的判断依据。

**三层防御设计:**

| 层 | 手段 | 效果 |
|----|------|------|
| **检测** | **增强 GraphSemanticCorrector prompt 上下文** | **LLM综合判断域归属** |
| 辅助 | infra keyword 标记(供LLM参考) | 提示工具类身份 |
| 兜底 | `_review_subdomain_placement` 规则 + auto-reparent | 最后防线 |

**Changes:**

| File | Change |
|------|--------|
| `wiki/graph_semantic_corrector.py` | 增强 prompt + 升级为 `complete_json` + JSON Schema |
| `wiki/nodes/graph_domain_decompose.py` | 构建包层次树和调用关系摘要传给 corrector |
| `wiki/llm_schemas.py` | 新增 `DomainReviewOutput` schema |
| `core/config.py` | 扩充 `infrastructure_slug_keywords` |

**Code (构建丰富上下文):**
```python
# graph_domain_decompose.py: 为 corrector 准备额外上下文

def _build_package_tree(module_paths: dict[str, str]) -> str:
    """Build a human-readable package tree for LLM context."""
    from collections import defaultdict
    tree: dict[str, list[str]] = defaultdict(list)
    for compound_key, path in module_paths.items():
        pkg_parts = _extract_package_from_path(path)
        prefix = ".".join(pkg_parts[:4]) if len(pkg_parts) >= 4 else ".".join(pkg_parts)
        module_name = compound_key.split(":", 1)[-1] if ":" in compound_key else compound_key
        tree[prefix].append(module_name)
    
    lines = []
    for pkg, modules in sorted(tree.items()):
        lines.append(f"  {pkg}/ ({len(modules)} modules)")
        for m in modules[:5]:
            lines.append(f"    - {m}")
        if len(modules) > 5:
            lines.append(f"    ... +{len(modules)-5} more")
    return "\n".join(lines)


def _build_cross_domain_edges_summary(
    edges: list[tuple], domain_mapping: dict, top_n: int = 15
) -> str:
    """Summarize top cross-domain call relationships."""
    cross_edges = []
    for (r1, m1), (r2, m2), weight in edges:
        d1 = domain_mapping.get((r1, m1))
        d2 = domain_mapping.get((r2, m2))
        if d1 and d2 and d1 != d2:
            cross_edges.append((m1, m2, d1, d2, weight))
    cross_edges.sort(key=lambda x: -x[4])
    
    lines = []
    for caller, callee, dom_a, dom_b, w in cross_edges[:top_n]:
        lines.append(f"  {caller}({dom_a}) → {callee}({dom_b}) [{w}次]")
    return "\n".join(lines) if lines else "  (无显著跨域调用)"
```

**Code (增强 corrector prompt):**
```python
# graph_semantic_corrector.py: 在 review_global_consistency 的 prompt 中追加

enhanced_context = f"""
## 包层次结构 (帮助判断模块的组织归属):
{package_tree}

## 高频跨域调用 (被多域调用的模块可能是基础设施):
{cross_domain_edges}

## 审查指引:
1. 检查每个域内的模块是否业务上相关。如果某模块的包路径与同域其他模块明显不同，考虑移出。
2. 如果某模块被 3 个以上域频繁调用，它可能是基础设施/工具类，应独立为 infra 域。
3. 明确业务归属的模块(如包路径含 family/intimacy/relation 等)不应与其他业务线混淆。
4. converter/mapper/handler 类型模块，如果仅服务于特定业务则保留，如果跨域共用则归 infra。
"""
```

**Code (升级为 JSON Schema 输出):**
```python
# wiki/llm_schemas.py — 新增
class DomainReviewAction(BaseModel):
    """A single corrective action for domain placement."""
    action: Literal["move", "merge", "rename", "create_infra"]
    module_slug: str = ""
    from_domain: str = ""
    to_domain: str = ""
    reasoning: str

class DomainReviewOutput(BaseModel):
    """Structured output for domain global consistency review."""
    actions: list[DomainReviewAction] = Field(default_factory=list)
    summary: str = ""

# graph_semantic_corrector.py — 升级调用方式:
from wiki.llm_schemas import DomainReviewOutput

async def review_global_consistency(self, ...):
    # ... build prompt with enhanced_context ...
    messages = [
        {"role": "system", "content": SYSTEM_JSON_ONLY},
        {"role": "user", "content": prompt},
    ]
    result = await self._llm.complete_json(
        messages, DomainReviewOutput.model_json_schema()
    )
    review = DomainReviewOutput.model_validate(result)
    # 结构确定，无需 parse_json_robust_sync
```

**JSON Schema 升级的价值:**
- 输出结构确定性: 不再依赖 `parse_json_robust_sync` 的 fallback
- Action 类型枚举: LLM 只能返回 move/merge/rename/create_infra
- 与 V10 F4 方向一致: 全面消除 `generate()` + 手动解析的脆弱模式

**Code (兜底规则 + auto-reparent 保留):**
```python
# _review_subdomain_placement 保留作为兜底:
_PARENT_CHILD_SLUG_MISMATCHES = [
    (("intimacy", "relation", "亲密"), ("user-behavior", "behavior-stat", "用户行为")),
    (("intimacy", "亲密"), ("family", "家族")),
    (("intimacy", "relation", "亲密", "关系"), ("type-conversion", "typehandler", "datasource", "数据转换")),
]

# Upgrade: warning → auto-reparent
for w in warnings:
    _reparent_to_root(domain_tree, w["child_slug"])
```

**infrastructure_slug_keywords additions:**
```python
infrastructure_slug_keywords: list[str] = Field(default=[
    ...,  # existing
    "conversion", "mapping", "type-handler", "type-conversion",
    "datasource", "data-source", "serializer", "deserializer",
])
```

**根治度:** 90%。LLM综合包结构+调用关系+语义描述判断，比任何单一程序化信号都准确。

**为什么这比包路径距离修正更好:**
- 不假设"同包=同业务"（LLM自己判断包结构含义）
- 适用于任何语言和包组织风格
- 利用已有的 GraphSemanticCorrector 调用，零额外 LLM 成本
- 调用关系提供模块亲疏的客观证据

**未来迭代方向（超出V11范围）:**
- Wiki-First Domain Assignment: 先生成每个模块的摘要 → 基于摘要内容重新聚类
- 二次聚类: wiki生成后，基于wiki内容的语义相似度验证/修正域归属

**Tests:**
- New: `test_corrector_receives_package_tree`
- New: `test_corrector_receives_cross_domain_edges`
- New: `test_corrector_moves_infra_module_out`
- New: `test_placement_auto_reparent`

---

### F6: Overview Code Overload Detection

**Problem:** relation-service has 13846 chars with cn=10%, essentially a code dump.

**Changes:**

| File | Change |
|------|--------|
| `wiki/nodes/quality_gate.py` | Add code overload detection for overviews |

**Code:**
```python
if page_type == "domain_overview":
    code_blocks = re.findall(r"^```", page_content, re.MULTILINE)
    code_block_count = len(code_blocks) // 2
    if code_block_count > 5 and cn_ratio < 0.20:
        content_issues.append("overview_code_overload: too many code blocks with low prose ratio")
```

**与F3的关系:** F3的Prompt预防控制Agent从源头不过度引用代码；F6作为检测层，发现漏网的代码堆叠并触发heal。

**Tests:**
- New: `test_overview_code_overload_heal`

---

### F7-R: DomainAnchor 可选增量保护 (Revised)

> **Revision Note:** 原设计将DomainAnchor作为必需的"首次生成保护"。用户指出清空重生时不存在已知域。
> 修正为: DomainAnchor仅用于**增量更新**场景（已有wiki后再次生成时保护已确认的域不消失）。

**Problem:** 域全量重聚类时业务线可能消失（如挚友60模块的域被合并到其他域）。

**适用场景:**
- ❌ 首次生成 / 清空重生 → F5-R(增强Corrector上下文)提供保护
- ✅ 增量更新 / 新模块加入后重新聚类 → DomainAnchor保护已确认域

**Changes:**

| File | Change |
|------|--------|
| `wiki/nodes/graph_domain_decompose.py` | Load anchors (if exist) + protect in corrector |
| `wiki/graph_semantic_corrector.py` | Add anchor constraint |

**Integration (简化版 — 仅增量保护):**
```python
async def _decompose_domains(state, ...):
    anchor_service = state.get("anchor_service")
    anchored_slugs = set()
    if anchor_service:
        anchors = await anchor_service.get_anchors(state["business_id"])
        anchored_slugs = {a.slug for a in anchors}
    
    # ... normal clustering ...
    
    # Post-clustering: verify anchored domains survived
    if anchored_slugs:
        new_slugs = {r["slug"] for r in communities_named}
        missing = anchored_slugs - new_slugs
        for slug in missing:
            log.warning("anchored_domain_missing", slug=slug)
            preserved = await _recover_anchored_domain(slug, store, business_id)
            if preserved:
                communities_named.append(preserved)
```

**Corrector constraint (仅当有anchors时生效):**
```python
if anchored_slugs:
    constraint = f"\nCRITICAL: Never merge or rename: {', '.join(sorted(anchored_slugs))}"
    prompt += constraint
```

**何时创建Anchors:**
- wiki首次生成完成 → 审计通过 → 人工确认核心域 → 创建anchors
- 即: anchors是首次生成的**输出产物**，不是输入条件

**Tests:**
- New: `test_anchor_prevents_domain_merge` (增量场景)
- New: `test_no_anchor_fresh_generation_works` (首次场景无anchor也正常)

---

## 3. Implementation Plan

### Phase 1: Quick Wins (F1 + F2 + F3) — ~100 lines diff

| Step | Fix | Estimated Lines | 三层覆盖 |
|------|-----|-----------------|-----------|
| 1.1 | F1: Prompt threshold ≤5→≤2 | 2 lines | 预防 |
| 1.2 | F1: chunk_size 5→3 | 1 line | 预防 |
| 1.3 | F1: force_override (modules≥3) | 8 lines | **兜底** |
| 1.4 | F2: dedup uniqueness loop | 15 lines | 检测 |
| 1.5 | F2: _dedupe_slug_segments | 20 lines | 兜底 |
| 1.6 | F3: Prompt代码量约束 | 5 lines | **预防** |
| 1.7 | F3: quality_gate overview cn | 10 lines | 检测 |
| 1.8 | F3: finalize overview cn reject | 10 lines | 兜底 |
| 1.9 | Tests for F1/F2/F3 | ~70 lines | — |

**Verification:** Run existing tests → deploy → regenerate wiki → run audit_wiki_data.py

### Phase 2: Structural Fixes (F4 + F5-R + F6) — ~150 lines diff

| Step | Fix | Estimated Lines | 三层覆盖 |
|------|-----|-----------------|-----------|
| 2.1 | F4: tree_linker经sanitize + 长度校验 | 20 lines | 检测+兜底 |
| 2.2 | F5-R: 构建包层次树 + 跨域调用摘要 | 40 lines | **检测(LLM上下文)** |
| 2.3 | F5-R: 增强corrector prompt(审查指引) | 15 lines | **检测** |
| 2.4 | F5-R: placement规则扩展 + auto-reparent | 20 lines | 兜底 |
| 2.5 | F5-R: infra keywords扩充 | 5 lines | 辅助 |
| 2.6 | F6: code overload detection | 10 lines | 检测 |
| 2.7 | Tests for F4/F5-R/F6 | ~80 lines | — |

**Verification:** Run tests → deploy → regenerate wiki → audit

### Phase 3: Incremental Protection (F7-R) — ~80 lines diff

| Step | Fix | Estimated Lines |
|------|-----|-----------------|
| 3.1 | Load anchors (if exist) in decompose | 15 lines |
| 3.2 | Post-clustering anchor preservation | 20 lines |
| 3.3 | Corrector constraint | 10 lines |
| 3.4 | Tests | ~40 lines |

**Verification:** 首次生成 → 审计确认 → 创建anchors → 增量重生成 → verify anchored域保留

---

## 4. Verification Criteria

Post-deployment audit targets (via `scripts/audit_wiki_data.py`):

| Metric | V25 Baseline | Phase 1 | Phase 2 | Phase 3 |
|--------|--------------|---------|---------|---------|
| Topic coverage | 9% | **≥40%** | ≥40% | ≥40% |
| Shell domains | 4 | 4 | **0** | 0 |
| Slug repeated | 2 | **0** | 0 | 0 |
| Misplaced domains | 2 | 2 | **0** | 0 |
| Low cn pages (<0.25) | 6 | **≤2** | 0 | 0 |
| Code overload pages | 1 | ≤1 | **0** | 0 |
| Anchored domains lost | N/A | N/A | N/A | **0** |
| Composite score | 5.6 | ≥6.5 | ≥7.5 | **≥8.0** |

---

## 5. Risk Matrix

| Fix | Risk | Mitigation |
|-----|------|-----------|
| F1 force_override | ≥3模块域强制拆分可能产生低质量topic | quality_gate min_chars + cn_ratio 仍然活跃 |
| F2 slug dedup | 边缘case segment dedup可能过度清理 | Conservative regex + 仅清理连续重复 |
| F3 overview cn gate | 极少数合法高代码overview被误拒 | 0.15 threshold极宽松，仅捕获cn=10%级极端case |
| F4 tree_linker sanitize | 增加tree_linker与finalize的耦合 | 只导入一个公共函数，不增加循环依赖 |
| F5-R corrector增强 | LLM纠错可能过度移动模块 | 仅提供建议性审查指引，corrector已有合并/保持的保守倾向 |
| F5-R auto-reparent | 兜底规则可能误触发 | 仅对明确的已知错误模式触发，规则数量保守 |
| F6 code overload | heal后Agent可能删除有价值代码 | 组合条件(>5块 AND cn<0.20)非常严格 |
| F7-R anchor | 首次无anchor时无保护 | F5-R增强Corrector已提供基础保护 |

---

## 6. Design Decisions Record

| Decision | Chosen | Alternative | Rationale |
|----------|--------|-------------|-----------|
| Topic threshold | Prompt ≤2 + force_override ≥3 | Remove threshold entirely | 硬性保证但保留LLM对细节的判断权 |
| Mechanical chunk | size=3 | size=2 | 平衡topic数量与质量 |
| Overview cn thresholds | heal=0.20, reject=0.15 | Same as topic (0.40/0.25) | Overview合理含更多代码 |
| tree_linker gate | 经sanitize管道 | 完全移除content生成 | 保留tree_linker功能但纳入质量管控 |
| Placement fix | **增强LLM Corrector上下文** | 包路径距离修正 / 硬编码规则 | LLM综合判断优于程序化假设，适用任何包结构 |
| DomainAnchor scope | **可选增量保护** | 必需的首次保护 | 首次生成无已知域，anchor是输出不是输入 |
| 代码量控制 | Prompt预防 + quality_gate检测 | 仅后置检测 | 从源头预防优于事后修复 |

---

## 7. 根治度评估

| 问题 | V25现状 | 修复手段 | 根治度 | 剩余5%不确定性来源 |
|------|---------|---------|--------|-------------------|
| Topic覆盖率 | 9% | Prompt+chunk+force_override | **95%** | LLM生成的topic内容质量仍依赖Agent能力 |
| 壳域bypass | 4页 | tree_linker经sanitize+长度门禁 | **98%** | — |
| Slug重复段 | 2域 | while循环+段查重+质量校验 | **95%** | 全新命名模式可能出现新的edge case |
| 域错挂 | 2处 | 增强Corrector上下文+infra标记+auto-reparent | **90%** | LLM判断不总是正确，但综合信号远优于单一信号 |
| 低cn/代码堆叠 | 6页 | Prompt约束+heal+reject三层 | **95%** | LLM行为不可100%控制 |
| 域消失 | (历史) | F5-R(Corrector审查)+F7-R(增量anchor) | **88%** | 全新业务线无先验可参考 |

**综合根治度: ~93%** (从 V11 原方案的 75-80% 提升)

**剩余5%的本质:** LLM内容生成的不确定性 + 全新未见过的代码模式。这些通过持续审计+规则迭代来解决，无法100%消除。
