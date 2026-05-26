# Wiki 质量修复 v2 — 完整设计文档

**Created:** 2026-05-26
**Status:** Batch 1-2 ✅ 已完成 | Batch 2.5 待实施 | Batch 3-4 延后
**Scope:** 全链路语言统一 + 产物清理 + Topic 拆分优化 + 域命名改善 + Stale 清理修复
**Estimated Changes:** ~450 行代码，~15 文件

---

## 1. 背景与问题

### 1.1 审计数据（dev 环境，business_id=ultron）

| 指标 | 值 |
|------|-----|
| 活跃页面 | 79（27 overview + 52 topic） |
| WikiSection | 27 |
| Overview 英文主导 | 13/27 (48.1%) |
| Topic 英文主导 | 8/52 (15.4%) |
| 产物泄漏页面 | 9/79 (11.4%) |
| 幻觉页面 | 3/79 (com/xxx/) |
| 空域（仅 overview 无 topic） | 6/14 根域 |
| Topic 重复（domain-01） | 18 topics / 8 modules |
| Topic 错挂（closed-friend） | 17 topics 挂根域而非子域 |

### 1.2 根因分析 — 8 个代码断裂点

| ID | 断裂点 | 位置 | 影响 |
|----|--------|------|------|
| A | API 默认 `language="en"` vs settings 默认 `wiki_content_language="简体中文"` | `wiki_models.py` / `config.py` | 两套配置未映射 |
| B | 域命名 `GraphDomainNamer` 硬编码中文，无 language 参数 | `graph_domain_namer.py` | 命名规则与 language 矛盾 |
| C | `compose` 读 `wiki_content_language` 忽略 `state.language` | `domain_compose.py:29-40` | compose 与 API 意图脱节 |
| D | Explore 系统 prompt 固定中文 | `agent_prompts.py` | 低影响，不阻塞 write |
| E | Topic planner prompt 英文主体 | `agent_prompts.py` | `get_topic_planner_prompt` 已有 language 参数 |
| F | Write user prompt 永远中文 vs system prompt 随 language 变 | `page_agent.py:817-838` | 混合语言 LLM 输出 |
| G | `_inject_dependency_diagram` 硬编码 `## Architecture`；`_maybe_split` 混合 `章节导航`/`Untitled` | `domain_compose.py` / `domain_doc_agent.py` | 注入固定语言片段 |
| H | Guardrail 只检测不修复 | `domain_doc_agent.py:787-847` | 语言问题不阻断 |

---

## 2. 设计方案

### 2.1 核心原则

1. **统一枚举** — 引入 `ContentLanguage` 枚举替代自由文本
2. **全链路传递** — 从 API → orchestrator → decompose → compose → agent → finalize 一致传递
3. **末端加固** — finalize 作为最后防线清理所有产物泄漏
4. **最小侵入** — 不改变 LangGraph 图结构，只在节点内部修改

### 2.2 统一语言枚举

**文件:** `core/config.py`（新增枚举）

```python
from enum import StrEnum

class ContentLanguage(StrEnum):
    ZH_CN = "zh-CN"
    EN = "en"

    @classmethod
    def from_any(cls, value: str) -> "ContentLanguage":
        """Map legacy values to enum."""
        normalized = (value or "").strip().lower()
        if "中文" in value or normalized in ("zh", "zh-cn", "zh_cn", "chinese"):
            return cls.ZH_CN
        return cls.EN

    @property
    def display_label(self) -> str:
        return "简体中文" if self == self.ZH_CN else "English"

    @property
    def is_chinese(self) -> bool:
        return self == self.ZH_CN
```

**影响面:**
- `AppWikiFlags.wiki_content_language` 类型从 `str` 改为 `ContentLanguage`（默认 `ZH_CN`）
- `BusinessWikiGenerateBody.language` 默认改为 `"zh-CN"`
- `WikiConfig.language` 保持 `"en"/"zh"` 兼容（`__post_init__` 映射到枚举）

---

## 3. Batch 1 — P0 即时修复

### Task 1.1 — Finalize 产物清理增强

**文件:** `wiki/nodes/finalize.py`

在 `_sanitize_published_content` 中增加 5 类清理：

| 清理项 | 正则/逻辑 | 测试 |
|--------|----------|------|
| ✅/⚠️/❌ 质量清单表格 | 检测含 emoji 的 Markdown 表格块（表头+分隔+数据行），整段移除 | `test_quality_checklist_tables_removed` |
| `com/xxx/` 占位符路径 | 复用 `_FAKE_SOURCE_RE`，含该模式的代码块或行移除 | `test_fake_source_paths_removed` |
| `<think>` 标签 | `re.sub(r'<think>.*?</think>', '', content, re.DOTALL)` | `test_thinking_tags_removed` |
| CONTEXT_GAP 增强 | 引入 `context_gap.cleanup_context_gaps()` 全量模式 | `test_context_gap_full_cleanup` |
| wikilink valid_targets 扩展 | 增加 `{slug}/{title}` 格式 + normalize 匹配 | `test_wikilink_domain_title_format` |

**实现细节:**

```python
def _strip_quality_checklist_tables(content: str) -> str:
    """Remove markdown tables containing quality-check emoji (✅⚠️❌)."""
    lines = content.split("\n")
    result, in_table, table_has_emoji = [], False, False
    for line in lines:
        is_table_line = line.strip().startswith("|")
        if is_table_line:
            if not in_table:
                in_table, table_has_emoji = True, False
                table_buf = []
            table_buf.append(line)
            if any(e in line for e in ("✅", "⚠️", "❌")):
                table_has_emoji = True
        else:
            if in_table:
                in_table = False
                if not table_has_emoji:
                    result.extend(table_buf)
            result.append(line)
    if in_table and not table_has_emoji:
        result.extend(table_buf)
    return "\n".join(result)
```

### Task 1.2 — 语言配置统一

**文件:** `wiki/pipeline_orchestrator.py`

```python
from core.config import ContentLanguage

# 在 initial_state 构建时：
language_raw = (config_overrides or {}).get("language", "zh-CN")
content_language = ContentLanguage.from_any(language_raw)
initial_state["content_language"] = content_language
initial_state["language"] = content_language.value  # 兼容
```

**文件:** `wiki/nodes/domain_compose.py`

修改 `_resolve_content_language_for_compose`：

```python
def _resolve_content_language_for_compose(state, config) -> ContentLanguage:
    # 优先读 state（从 orchestrator 写入）
    cl = state.get("content_language")
    if isinstance(cl, ContentLanguage):
        return cl
    # 回退到 state.language（兼容）
    lang = state.get("language")
    if lang:
        return ContentLanguage.from_any(lang)
    # 最终回退到 settings
    return ContentLanguage.from_any(get_settings().wiki.wiki_content_language)
```

**文件:** `api/models/wiki_models.py`

```python
class BusinessWikiGenerateBody(BaseModel):
    language: str = Field(default="zh-CN", pattern="^(en|zh|zh-CN)$")
```

### Task 1.3 — Compose 语言解析对齐

与 Task 1.2 合并，确保 `_resolve_content_language_for_compose` 和 decompose 的 `_resolve_content_language` 读同一个 state key。

---

## 4. Batch 2 — P1 下次生成生效

### Task 2.1 — 后处理语言参数化

**文件:** `wiki/nodes/domain_compose.py`

```python
def _inject_dependency_diagram(content: str, modules: list, *, language: ContentLanguage) -> str:
    ...
    heading = "## 架构" if language.is_chinese else "## Architecture"
    return f"{content.rstrip()}\n\n{heading}\n\n```mermaid\n{diagram}\n```\n"

def _build_layer_summary(layers: dict, *, language: ContentLanguage) -> str:
    prefix = "本域架构层分布：" if language.is_chinese else "Architecture layers in this domain:"
    ...
```

调用处传入 `content_language`。

### Task 2.2 — `_maybe_split` + Topic Scope 语言化

**文件:** `wiki/domain_doc_agent.py`

```python
def _maybe_split(content, domain_slug, display, *, topic_split_done=False, language=ContentLanguage.ZH_CN):
    ...
    nav_heading = "## 章节导航" if language.is_chinese else "## Section Navigation"
    fallback_title = "未命名" if language.is_chinese else "Untitled"
    ...
```

Topic scope 上下文（`_write_with_outline`）：

```python
if self.content_language.is_chinese:
    topic_context = f"你正在撰写「{topic.title}」章节。仅关注以下模块：{topic_module_list}\n描述：{topic.description}"
else:
    topic_context = f"You are writing the \"{topic.title}\" section. Focus ONLY on these modules: {topic_module_list}\nDescription: {topic.description}"
```

### Task 2.3 — Write User Prompt 语言化

**文件:** `wiki/page_agent.py`

```python
async def write(self, ...):
    if self.content_language.is_chinese:
        user_prompt = f"## 任务\n基于以下探索结果，为业务域「{domain_name}」生成一篇完整的 Wiki 页面。\n\n..."
    else:
        user_prompt = f"## Task\nBased on the exploration results below, generate a complete Wiki page for the \"{domain_name}\" business domain.\n\n..."
```

### Task 2.4 — Guardrail 驱动重写

**文件:** `wiki/domain_doc_agent.py` （单体 write 循环内，L787-847 附近）

```python
guardrail_result = await self._output_guardrail.evaluate(content, {...})
if not guardrail_result.passed:
    language_issue = any(c.name == "language_consistency" and not c.passed for c in guardrail_result.checks)
    if language_issue and iteration < max_iterations:
        # 追加语言修正 hint 到下次 write
        heal_hints.append(f"上次输出语言不一致（目标：{self.content_language.display_label}），请用目标语言重写全文。")
        continue
```

**Topic split 路径也调用 guardrail:**

```python
# _write_with_outline 中每个 topic write 后：
topic_guardrail = await self._output_guardrail.evaluate(topic_content, {...})
if not topic_guardrail.passed:
    log.warning("topic_guardrail_failed", topic=topic.title, checks=...)
```

### Task 2.5 — Topic 标题语义去重

**文件:** `wiki/domain_doc_agent.py`

增强 `_dedup_topic_titles`：

```python
def _dedup_topic_titles(topics: list[TopicPlan]) -> list[TopicPlan]:
    """Deduplicate topic titles by exact match AND keyword overlap."""
    result = []
    seen_keywords: list[set[str]] = []
    for topic in topics:
        keywords = set(jieba.lcut(topic.title)) - STOP_WORDS  # 或简单的字符 n-gram
        # 检查与已有 topic 的关键词重叠率
        is_dup = False
        for i, existing_kw in enumerate(seen_keywords):
            overlap = len(keywords & existing_kw) / max(len(keywords | existing_kw), 1)
            if overlap >= 0.6:
                # 合并模块到已有 topic
                result[i].modules = list(set(result[i].modules) | set(topic.modules))
                is_dup = True
                break
        if not is_dup:
            result.append(topic)
            seen_keywords.append(keywords)
    return result
```

**注意:** 不引入 jieba 依赖，使用简单的 CJK 字符 bigram 匹配：

```python
def _extract_keywords(title: str) -> set[str]:
    chars = [c for c in title if '\u4e00' <= c <= '\u9fff']
    return {chars[i] + chars[i+1] for i in range(len(chars)-1)} if len(chars) >= 2 else set(chars)
```

### Task 2.6 — Topic Canonical Key + `_maybe_split` 上限

**文件:** `wiki/domain_doc_agent.py`

`_write_with_outline` 生成的 topic page 增加 `canonical_key`：

```python
child_pages.append({
    "path": topic_path,
    "page_type": "topic",
    "canonical_key": self.domain_slug,  # 新增
    ...
})
```

`_maybe_split` 增加 topic 数量上限：

```python
MAX_SPLIT_TOPICS = 8
if len(child_pages) > MAX_SPLIT_TOPICS:
    # 合并最小的相邻 sections 直到 <= MAX_SPLIT_TOPICS
    while len(merged) > MAX_SPLIT_TOPICS:
        min_idx = min(range(len(merged)-1), key=lambda i: len(merged[i]) + len(merged[i+1]))
        merged[min_idx] = merged[min_idx] + "\n" + merged.pop(min_idx + 1)
```

**文件:** `wiki/tree_linker.py`

Topic 归属优先叶子域：

```python
# build_canonical_key_maps 中，canonical_key 同时映射到叶子域名
ck = str(page.get("canonical_key") or "").strip()
if ck:
    # 优先叶子域
    if not canonical_key_to_domain.get(ck) or domain.is_leaf:
        canonical_key_to_domain[ck] = domain.name
```

---

## 5. Batch 3 — P2 中期优化

### Task 3.1 — 消除 domain-NN 匿名 slug

**文件:** `wiki/nodes/classify.py`

```python
# _ensure_ascii_keys 中：
if not ascii_slug or ascii_slug == "unnamed" or ascii_slug in result:
    # 尝试用 display_name 的拼音/transliteration
    ascii_slug = normalize_slug(updated_display.get(key, key))
    if not ascii_slug or ascii_slug in result:
        unnamed_counter += 1
        ascii_slug = f"misc-domain-{unnamed_counter:02d}"  # 至少比 domain-01 更有语义
```

### Task 3.2 — Slug 碰撞语义后缀

**文件:** `wiki/nodes/graph_domain_decompose.py`

```python
# _dedup_parallel_naming_results 中：
if slug in seen:
    counter = 2
    while f"{slug}-{counter}" in seen:
        counter += 1
    new_slug = f"{slug}-{counter}"
    result["slug"] = new_slug
```

### Task 3.3 — Overview 长度上限

**文件:** `wiki/domain_doc_agent.py`

在 `_write_with_outline` 合成 overview 后：

```python
MAX_OVERVIEW_CHARS = 3000
if len(overview_content) > MAX_OVERVIEW_CHARS:
    # 截断每个 topic 摘要，保留标题 + 首句
    ...
```

### Task 3.4 — 微型域自动合并

**文件:** `wiki/nodes/graph_domain_decompose.py`

在 `_merge_domains_by_llm` 或 `_post_merge_small_domains` 阶段：

```python
MIN_DOMAIN_MODULES = 5  # 可配置
small_domains = {k: v for k, v in domain_mapping.items() if len(v) < MIN_DOMAIN_MODULES}
# 将小域模块重新分配到最相似的大域
```

---

## 6. 文件影响矩阵

| 文件 | Batch 1 | Batch 2 | Batch 3 | 修改行数 |
|------|---------|---------|---------|---------|
| `core/config.py` | ✅ 枚举定义 | | | ~25 |
| `api/models/wiki_models.py` | ✅ 默认值 | | | ~3 |
| `wiki/pipeline_orchestrator.py` | ✅ state 写入 | | | ~10 |
| `wiki/nodes/domain_compose.py` | ✅ 语言解析 | ✅ diagram/layer | | ~40 |
| `wiki/nodes/finalize.py` | ✅ 5类清理 | | | ~80 |
| `wiki/domain_doc_agent.py` | | ✅ split/scope/guardrail/dedup/ck | ✅ overview上限 | ~100 |
| `wiki/page_agent.py` | | ✅ user prompt | | ~20 |
| `wiki/tree_linker.py` | | ✅ canonical_key | | ~15 |
| `wiki/nodes/classify.py` | | | ✅ slug命名 | ~10 |
| `wiki/nodes/graph_domain_decompose.py` | | | ✅ 碰撞/合并 | ~30 |
| `wiki/agent_prompts.py` | | (已有 language 参数) | | ~5 |
| `wiki/output_guardrail.py` | | (无改动，已有检测) | | 0 |

**总计:** ~338 行

---

## 7. 测试计划

### 7.1 Batch 1 测试

| 测试 | 文件 | 验证点 |
|------|------|--------|
| `test_quality_checklist_tables_removed` | `tests/wiki/test_finalize_sanitize.py` | 含 ✅ 表格被清理 |
| `test_fake_source_paths_removed` | 同上 | `com/xxx/` 路径被清理 |
| `test_thinking_tags_removed` | 同上 | `<think>` 被清理 |
| `test_content_language_unified` | `tests/wiki/test_pipeline_orchestrator.py` | state 含 ContentLanguage 枚举 |
| `test_compose_reads_content_language` | `tests/wiki/nodes/test_domain_compose.py` | compose 使用统一枚举 |
| `test_wikilink_domain_title_format` | `tests/wiki/nodes/test_finalize_node.py` | `[[slug/title]]` 正确匹配 |

### 7.2 Batch 2 测试

| 测试 | 验证点 |
|------|--------|
| `test_diagram_heading_chinese` | 中文时输出 `## 架构` |
| `test_maybe_split_language_aware` | 中文时 `章节导航`，英文时 `Section Navigation` |
| `test_write_user_prompt_chinese` | user prompt 随语言切换 |
| `test_guardrail_triggers_rewrite` | 语言 guardrail 失败触发重写 |
| `test_topic_semantic_dedup` | 相似标题被合并 |
| `test_topic_canonical_key_set` | topic page 含 canonical_key |
| `test_maybe_split_max_topics` | sections > 8 时合并 |

### 7.3 Batch 3 测试

| 测试 | 验证点 |
|------|--------|
| `test_no_domain_nn_slug` | 不再产生 `domain-01` 式 slug |
| `test_slug_collision_counter` | 碰撞用 `-2` 而非 MD5 |
| `test_overview_length_cap` | overview ≤ 3000 chars |
| `test_small_domain_merge` | 模块 < 5 的域被合并 |

---

## 8. 验证计划

### Batch 1 验证（部署后立即）

```bash
# 1. 重跑 finalize 节点
ssh dev "curl -s -X POST -H 'Authorization: Bearer sk-admin-test' 'http://localhost:8100/api/v1/wiki/ultron/refinalize'"

# 2. 检查产物泄漏
python3 -c "
import json, re
pages = json.load(open('/tmp/wiki-all-pages-content.json'))
for p in pages:
    c = p['content']
    issues = []
    if any(e in c for e in ('✅', '⚠️', '❌')): issues.append('checklist')
    if 'com/xxx/' in c: issues.append('fake_path')
    if '<think>' in c: issues.append('think_tag')
    if issues: print(f'{p[\"title\"]}: {issues}')
# 预期: 0 个问题
"
```

### Batch 2 验证（对单域重新生成）

```bash
# 对 domain-01 重新生成，验证 topic 数量和语言
ssh dev "curl -s -X POST -H 'Authorization: Bearer sk-admin-test' \
  -H 'Content-Type: application/json' \
  -d '{\"business_id\":\"ultron\",\"language\":\"zh-CN\",\"domains\":[\"domain-01\"]}' \
  'http://localhost:8100/api/v1/wiki/generate-domain'"

# 验证: topic 数量 ≤ 10, cn_ratio ≥ 50%
```

### Batch 3 验证（全量重新生成后）

```bash
# 全量审计脚本
python3 audit_wiki_quality.py --business_id ultron --host dev
# 预期: 综合分 ≥ 75/100
```

---

## 9. 风险与回退

| 风险 | 缓解 |
|------|------|
| ContentLanguage 枚举不兼容旧数据 | `from_any` 映射所有已知格式 |
| finalize 误删有效内容 | 正则精确匹配 + 单元测试覆盖 |
| topic 去重误合并不同主题 | 关键词重叠阈值 0.6（保守） |
| API 默认值改动影响下游 | 兼容 `"en"/"zh"/"zh-CN"` 三种格式 |

---

## 10. 实施顺序

```
Week 1: Batch 1 (P0)
  Day 1: ContentLanguage 枚举 + pipeline_orchestrator 统一
  Day 2: finalize 增强（5 类清理）
  Day 3: 测试 + 部署 + 验证

Week 2: Batch 2 (P1)
  Day 1-2: 后处理语言化 + guardrail enforcement
  Day 3-4: topic 优化（去重 + canonical_key + 上限）
  Day 5: 测试 + 部署 + domain-01 验证

Week 3: Batch 3 (P2)
  Day 1-2: 域命名 + 微型域合并
  Day 3: 全量重新生成 + 审计
```

---

## 11. Batch 2.5 — 部署后发现的 P0/P1 关键修复

**Created:** 2026-05-26
**触发:** Batch 1-2 部署后重新生成 wiki 并审计，发现核心质量问题由更底层的 bug 掩盖。

### 11.1 部署后审计数据

| 指标 | Batch 1-2 前 | Batch 1-2 后 | 说明 |
|------|-------------|-------------|------|
| 总页面数 | 79 | 71 | 页面反而减少 |
| topic 页面 | 52 | 43 | 被 stale 清理误删 |
| overview 页面 | 27 | 28 | 略增 |
| domain-01 topic 数 | 18 | 18 | topic cap 未生效 |
| closed-friend topic 数 | 17 | 17 | 同上 |
| cn_ratio < 30% 页面 | — | 52% | 大量低中文占比 |
| `source://` 泄漏 | — | 42% 页面 | 新发现的产物泄漏 |
| `<!-- CODE_REF -->` 泄漏 | — | 14% 页面 | 同上 |
| 家族业务域 topic | — | 0 | 子域内容全被删除 |

### 11.2 根因深度分析

#### P0-1: Stale 清理误删 785/839 页（根中之根）

**位置:** `wiki/business_pipeline_runner.py` L806-808

**Bug:** `_cleanup_stale_domain_pages` 使用 `set(domain_mapping.keys())` 作为"当前活跃域 slug 集合"。但 `domain_mapping` 是 `graph_domain_decompose` 输出的**扁平化顶层映射**，只包含叶子域 slug（约 36 个）。而 `domain_tree` 是层级结构，包含所有中间节点和嵌套叶子域（如 `family-core-operations`、`family-chest-and-task` 等）。

**结果:** 所有路径形如 `/__domains__/{nested-slug}/...` 的页面（其 slug 不在 `domain_mapping.keys()` 中）被判定为 stale 并删除。这导致 Agent 生成的高质量内容在 stale 清理阶段被全部抹除。

**讽刺:** `cleanup_stale_domain_edges` 和 `cleanup_stale_domain_sections`（L742-749）使用了正确的 `_flatten_tree_paths(domain_tree)` 来收集全量 slug，但 `_cleanup_stale_domain_pages` 没有！

```python
# L737-749: edges/sections 使用正确的 slug 集合
all_section_names = list(domain_names)
if domain_tree:
    all_section_names.extend(self._flatten_tree_paths(domain_tree))
    all_section_names.append("__root__")
await self._persistence.cleanup_stale_domain_edges(business_id, all_section_names)
await self._persistence.cleanup_stale_domain_sections(business_id, all_section_names)

# L806-808: pages 使用错误的 slug 集合 ← BUG
stale_deleted = await self._cleanup_stale_domain_pages(
    business_id,
    set(domain_mapping.keys()),  # 只有 ~36 个顶层 slug
)
```

**修复方案:**

```python
# 新增辅助函数
def _all_tree_slugs(nodes: list[DomainNode]) -> set[str]:
    """Collect ALL domain slugs from the hierarchical tree."""
    slugs: set[str] = set()
    for node in nodes:
        if node.name.strip():
            slugs.add(node.name.strip())
        slugs.update(_all_tree_slugs(node.children))
    return slugs

# 调用处修改
all_active_slugs = set(domain_mapping.keys())
if domain_tree:
    all_active_slugs |= _all_tree_slugs(domain_tree)
stale_deleted = await self._cleanup_stale_domain_pages(business_id, all_active_slugs)
```

**影响:** 修复后预计 stale_deleted ≈ 0（而非 785），所有子域 Agent 内容得以保留。

#### P0-2: 容器域历史 Topic 残留（domain-01 / closed-friend）

**现象:** `domain-01` 有 18 个 topic，`closed-friend-relations` 有 17 个 topic，远超 `MAX_SPLIT_TOPICS=8`。

**根因链:**
1. `graph_domain_decompose` 将 `domain-01` 从叶子域升级为容器域（有子域、无直接模块）
2. `compose_domain_agents` **只处理叶子域**（有 modules 的域）
3. `DomainDocAgent`（topic capping + dedup 逻辑所在）**不会被调用**于容器域
4. 旧版生成的 18/17 个 topic 页面仍然存在于图数据库中
5. stale 清理按 **title 匹配**而非 **path 前缀**，不会删除容器域下的历史 topic

**修复方案:**

```python
# 在 _cleanup_stale_domain_pages 之后新增容器域 topic 清理
async def _cleanup_container_domain_topics(
    self,
    business_id: str,
    domain_tree: list[DomainNode],
) -> int:
    """Delete historical topic pages under container domains (have children, no modules)."""
    container_slugs = self._get_container_slugs(domain_tree)
    if not container_slugs or self._wiki_store is None:
        return 0
    deleted = 0
    for slug in container_slugs:
        query = (
            "MATCH (wp:WikiPage) "
            "WHERE wp.repository = $biz "
            "AND wp.path STARTS WITH $prefix "
            "AND wp.page_type = 'topic' "
            "DETACH DELETE wp "
            "RETURN count(wp) AS cnt"
        )
        result = await self._wiki_store.query(query, {
            "biz": business_id,
            "prefix": f"/__domains__/{slug}/",
        })
        cnt = (result[0]["cnt"] if result else 0)
        deleted += cnt
    return deleted

@staticmethod
def _get_container_slugs(nodes: list[DomainNode]) -> set[str]:
    slugs: set[str] = set()
    for node in nodes:
        if node.children and not node.modules:
            slugs.add(node.name.strip())
        slugs.update(BusinessPipelineRunner._get_container_slugs(node.children))
    return slugs
```

#### P0-3: 产物泄漏补全（source:// + CODE_REF）

**位置:** `wiki/nodes/finalize.py` `_sanitize_published_content`

**现象:** Batch 1 已清理 `<think>` / `com/xxx/` / quality checklist，但遗漏了：
- `source://` 协议链接（42% 页面含有）
- `<!-- CODE_REF -->` / `<!-- UNVERIFIED_CODE -->` HTML 注释（14% 页面含有）

**修复方案:**

```python
_SOURCE_PROTOCOL_RE = re.compile(r'source://[^\s)>\]]+', re.IGNORECASE)
_CODE_REF_COMMENT_RE = re.compile(
    r'<!--\s*(?:CODE_REF|UNVERIFIED_CODE)\s*:?.*?-->',
    re.DOTALL,
)

def _sanitize_published_content(content: str) -> str:
    # ... existing cleanup ...
    content = _SOURCE_PROTOCOL_RE.sub('', content)
    content = _CODE_REF_COMMENT_RE.sub('', content)
    return content
```

#### P1-1: Coverage Compound Key Bug

**位置:** `wiki/quality_report.py` `_is_module_covered`

**Bug:** 模块名可能是复合键格式 `repository|ClassName`（如 `ultron|FamilyPowerService`），但 `_is_module_covered` 只用 `rsplit(".", 1)` 分割，不处理 `|` 分隔符。导致在 content 中搜索 `ultron|FamilyPowerService`（字面量），永远匹配不到。

**影响:** quality gate 对所有复合键模块的 coverage 评分永远为 0，无法触发 re-explore。

**修复方案:**

```python
def _is_module_covered(content: str, module_name: str) -> bool:
    name = module_name.strip()
    if not name:
        return False
    # Strip compound key prefix: "repo|ClassName" → "ClassName"
    if "|" in name:
        name = name.split("|", 1)[1]
    variants = [name]
    short = name.rsplit(".", 1)[-1]
    if short and short != name:
        variants.append(short)
    # ... rest unchanged ...
```

#### P1-2: TreeLinker 内容保护

**位置:** `wiki/tree_linker.py` L626 附近

**问题:** 当 stale 清理误删页面后，TreeLinker 为缺失页面生成 static template（仅包含子域列表或模块清单），这些模板覆盖了之前 Agent 生成的丰富内容。

**防御修复:** 在生成 fallback 前检查是否已有非模板内容：

```python
# 在 fallback 模板生成前增加保护
existing_content = pages_by_entity_uid.get(page_uid, {}).get("content", "")
if len(existing_content) > 500:
    return existing_content  # 保留已有的丰富内容
```

### 11.3 修复优先级与预期效果

| Fix | 优先级 | 文件 | 预估行数 | 预期效果 |
|-----|--------|------|---------|---------|
| Stale 清理 slug 集合 | P0 | `business_pipeline_runner.py` | ~20 | 解决内容丢失的根因 |
| 容器域 topic 清理 | P0 | `business_pipeline_runner.py` | ~35 | 消除 domain-01/closed-friend 的 topic 残留 |
| 产物泄漏补全 | P0 | `finalize.py` | ~15 | 消除 42%+14% 页面的标记泄漏 |
| Coverage compound key | P1 | `quality_report.py` | ~10 | 让质量检查正常工作 |
| TreeLinker 内容保护 | P1 | `tree_linker.py` | ~10 | 防御性措施，防止未来内容覆盖 |

**总计:** ~90 行代码

### 11.4 验证计划

修复部署后重新生成 wiki，检查：

| 检查项 | 预期结果 |
|--------|---------|
| `stale_domain_tree_pages_cleaned deleted` | ≈ 0（而非 785） |
| 家族业务域（family-core-operations 等）| 有 Agent 生成的 topic 页面 |
| domain-01 topic 数 | 0（容器域无 topic） |
| closed-friend topic 数 | 0（容器域无 topic） |
| cn_ratio < 30% 页面占比 | < 15%（从 52% 大幅下降） |
| `source://` 泄漏 | 0 页面 |
| `<!-- CODE_REF -->` 泄漏 | 0 页面 |
| 总页面数 | 增加到 100+（子域内容恢复） |

---

## 12. Future: Batch 4 — DocOrchestrator 路径统一

**前置条件:** Batch 1-3 + Batch 2.5 已完成并通过验证。

**背景:** 当前 `DomainDocAgent` 存在两条生成路径：
- `generate_with_iterations()` (默认, `use_orchestrator_template=False`) — 有完整的 topic planning / guardrail / per-phase timeout
- `DocOrchestrator.generate()` (模板方法, `use_orchestrator_template=True`) — 更简洁但缺失 topic planning

经 sequential-thinking 分析，双路径不是当前质量问题的根因，但确实是需要清理的架构债务。
分析也确认 `_maybe_split` 与 `_write_with_outline` 是"主路径+降级"关系而非"双路径"——小域（模块≤5）不值得做 topic planning，机械切割是合理的降级。

**实施计划:**
1. 将 Batch 1-3 中为 `generate_with_iterations()` 添加的语言/guardrail 能力迁移到 `DocOrchestrator` 模板
2. `DomainDocAgent.generate()` override 完整流程（topic planning + timeout + guardrail）
3. 将 `use_orchestrator_template` 默认改为 `True`
4. 废弃 `generate_with_iterations()`

**估计改动:** ~250 行代码，~50 行测试修改

---

*本文档为 wiki 质量修复 v2 的设计 spec。实施前需经用户审阅批准。*
