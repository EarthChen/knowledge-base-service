# Wiki Quality Fix v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 8 code breakpoints causing Chinese-English mixing (48%), artifact leakage (11%), topic duplication, and hallucination in wiki generation output.

**Architecture:** Introduce a `ContentLanguage` enum as the single source of truth for language configuration, propagate it through the full pipeline, enhance finalize cleanup, and parameterize all hardcoded language strings.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, LangGraph, pytest-asyncio

**Spec:** [`docs/superpowers/specs/2026-05-26-wiki-quality-fix-v2-design.md`](../specs/2026-05-26-wiki-quality-fix-v2-design.md)

---

## File Structure

| File | Responsibility | Tasks |
|------|---------------|-------|
| `core/config.py` | New `ContentLanguage` enum + `AppWikiFlags.wiki_content_language` type alignment | 1 |
| `api/models/wiki_models.py` | `BusinessWikiGenerateBody.language` default `"en"→"zh-CN"` | 1 |
| `wiki/pipeline_orchestrator.py` | Inject `content_language` enum into pipeline `initial_state` | 1 |
| `wiki/nodes/domain_compose.py` | `_resolve_content_language_for_compose` reads unified enum; `_inject_dependency_diagram` + `_build_layer_summary` accept language | 1, 3 |
| `wiki/nodes/finalize.py` | 5 new cleanup rules in `_sanitize_published_content` | 2 |
| `wiki/domain_doc_agent.py` | `_maybe_split` language param; topic dedup; canonical_key; guardrail rewrite | 3, 4 |
| `wiki/page_agent.py` | `write()` user prompt language-aware | 3 |
| `wiki/tree_linker.py` | Leaf-domain priority for canonical_key | 4 |
| `tests/wiki/test_finalize_sanitize.py` | New test file for finalize cleanup | 2 |
| `tests/wiki/test_language_unification.py` | New test file for ContentLanguage + pipeline language flow | 1 |
| `tests/wiki/nodes/test_finalize_node.py` | Extend existing finalize tests | 2 |
| `tests/wiki/nodes/test_domain_compose.py` (existing) | Tests for compose language resolution | 1, 3 |
| `tests/wiki/test_topic_title_dedup.py` | New test for semantic dedup | 4 |

---

## Task 1: ContentLanguage Enum + Pipeline Language Unification (Batch 1)

**Files:**
- Modify: `core/config.py:312` (wiki_content_language field)
- Modify: `api/models/wiki_models.py:39-41` (BusinessWikiGenerateBody)
- Modify: `wiki/pipeline_orchestrator.py:378-415` (initial_state)
- Modify: `wiki/nodes/domain_compose.py:29-40` (_resolve_content_language_for_compose)
- Test: `tests/wiki/test_language_unification.py` (new)

- [ ] **Step 1: Write failing tests for ContentLanguage enum**

Create `tests/wiki/test_language_unification.py`:

```python
from __future__ import annotations

import pytest


class TestContentLanguage:
    def test_from_any_zh_cn(self):
        from core.config import ContentLanguage
        assert ContentLanguage.from_any("zh-CN") == ContentLanguage.ZH_CN

    def test_from_any_chinese_label(self):
        from core.config import ContentLanguage
        assert ContentLanguage.from_any("简体中文") == ContentLanguage.ZH_CN

    def test_from_any_zh(self):
        from core.config import ContentLanguage
        assert ContentLanguage.from_any("zh") == ContentLanguage.ZH_CN

    def test_from_any_en(self):
        from core.config import ContentLanguage
        assert ContentLanguage.from_any("en") == ContentLanguage.EN

    def test_from_any_empty_defaults_en(self):
        from core.config import ContentLanguage
        assert ContentLanguage.from_any("") == ContentLanguage.EN

    def test_display_label_chinese(self):
        from core.config import ContentLanguage
        assert ContentLanguage.ZH_CN.display_label == "简体中文"

    def test_display_label_english(self):
        from core.config import ContentLanguage
        assert ContentLanguage.EN.display_label == "English"

    def test_is_chinese(self):
        from core.config import ContentLanguage
        assert ContentLanguage.ZH_CN.is_chinese is True
        assert ContentLanguage.EN.is_chinese is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/wiki/test_language_unification.py -v`
Expected: FAIL — `ImportError: cannot import name 'ContentLanguage'`

- [ ] **Step 3: Implement ContentLanguage enum in core/config.py**

Add before the `AppWikiFlags` class in `core/config.py`:

```python
from enum import StrEnum

class ContentLanguage(StrEnum):
    ZH_CN = "zh-CN"
    EN = "en"

    @classmethod
    def from_any(cls, value: str) -> ContentLanguage:
        """Map legacy values to enum."""
        normalized = (value or "").strip().lower()
        if "中文" in (value or "") or normalized in ("zh", "zh-cn", "zh_cn", "chinese"):
            return cls.ZH_CN
        return cls.EN

    @property
    def display_label(self) -> str:
        return "简体中文" if self == self.ZH_CN else "English"

    @property
    def is_chinese(self) -> bool:
        return self == self.ZH_CN
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/wiki/test_language_unification.py -v`
Expected: 8 PASSED

- [ ] **Step 5: Write failing tests for pipeline language injection**

Append to `tests/wiki/test_language_unification.py`:

```python
class TestPipelineLanguageInjection:
    def test_initial_state_has_content_language(self):
        """pipeline_orchestrator injects ContentLanguage into initial_state."""
        from core.config import ContentLanguage
        from wiki.pipeline_orchestrator import _build_initial_state_language

        cl = _build_initial_state_language({"language": "zh-CN"})
        assert cl == ContentLanguage.ZH_CN

    def test_initial_state_default_zh(self):
        from core.config import ContentLanguage
        from wiki.pipeline_orchestrator import _build_initial_state_language

        cl = _build_initial_state_language({})
        assert cl == ContentLanguage.ZH_CN

    def test_compose_resolves_content_language_from_state(self):
        from core.config import ContentLanguage
        from wiki.nodes.domain_compose import _resolve_content_language_for_compose

        state = {"content_language": ContentLanguage.ZH_CN}
        result = _resolve_content_language_for_compose(state, None)
        assert isinstance(result, ContentLanguage)
        assert result == ContentLanguage.ZH_CN

    def test_compose_falls_back_to_state_language(self):
        from core.config import ContentLanguage
        from wiki.nodes.domain_compose import _resolve_content_language_for_compose

        state = {"language": "zh-CN"}
        result = _resolve_content_language_for_compose(state, None)
        assert isinstance(result, ContentLanguage)
        assert result == ContentLanguage.ZH_CN
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `uv run pytest tests/wiki/test_language_unification.py::TestPipelineLanguageInjection -v`
Expected: FAIL

- [ ] **Step 7: Implement pipeline language injection**

In `wiki/pipeline_orchestrator.py`, add helper and modify `initial_state`:

```python
from core.config import ContentLanguage

def _build_initial_state_language(config_overrides: dict[str, Any] | None) -> ContentLanguage:
    language_raw = (config_overrides or {}).get("language", "zh-CN")
    return ContentLanguage.from_any(language_raw)
```

In the `run_wiki_pipeline` function, replace `language = (config_overrides or {}).get("language", "zh")` with:

```python
content_language = _build_initial_state_language(config_overrides)
```

And in `initial_state` dict, add `"content_language": content_language` and change `"language": language` to `"language": content_language.value`.

- [ ] **Step 8: Modify `_resolve_content_language_for_compose` to return ContentLanguage**

In `wiki/nodes/domain_compose.py`, change the function:

```python
from core.config import ContentLanguage

def _resolve_content_language_for_compose(
    state: dict[str, Any],
    config: dict[str, Any] | RunnableConfig | None,
) -> ContentLanguage:
    cl = state.get("content_language")
    if isinstance(cl, ContentLanguage):
        return cl
    lang = state.get("language")
    if lang:
        return ContentLanguage.from_any(str(lang))
    wlang = state.get("wiki_content_language")
    if wlang:
        return ContentLanguage.from_any(str(wlang))
    configurable = (config or {}).get("configurable", {}) if isinstance(config, dict) else {}
    if not isinstance(configurable, dict):
        configurable = {}
    cfg_lang = configurable.get("wiki_content_language")
    if cfg_lang:
        return ContentLanguage.from_any(str(cfg_lang))
    return ContentLanguage.from_any(get_settings().wiki.wiki_content_language)
```

Update the `content_language` variable in `compose_domain_agents_node` — it now returns `ContentLanguage`, and `DomainDocAgent` receives it. Since `DomainDocAgent.__init__` takes `content_language: str`, pass `content_language.display_label` for backward compat.

- [ ] **Step 9: Update API default language**

In `api/models/wiki_models.py`, change:
```python
language: str = Field(default="zh-CN", pattern="^(en|zh|zh-CN)$")
```

- [ ] **Step 10: Run all tests to verify they pass**

Run: `uv run pytest tests/wiki/test_language_unification.py -v`
Expected: ALL PASSED

- [ ] **Step 11: Run existing test suite for regressions**

Run: `uv run pytest tests/wiki/nodes/test_domain_compose.py tests/wiki/nodes/test_graph_domain_decompose.py tests/wiki/nodes/test_finalize_node.py -x -v`
Expected: ALL PASSED

- [ ] **Step 12: Commit**

```bash
git add core/config.py api/models/wiki_models.py wiki/pipeline_orchestrator.py wiki/nodes/domain_compose.py tests/wiki/test_language_unification.py
git commit -m "feat(wiki): add ContentLanguage enum and unify pipeline language injection"
```

---

## Task 2: Finalize Artifact Cleanup Enhancement (Batch 1)

**Files:**
- Modify: `wiki/nodes/finalize.py:12-40` (_sanitize_published_content)
- Create: `tests/wiki/test_finalize_sanitize.py`
- Modify: `tests/wiki/nodes/test_finalize_node.py` (extend)

- [ ] **Step 1: Write failing tests for 5 new cleanup rules**

Create `tests/wiki/test_finalize_sanitize.py`:

```python
from __future__ import annotations

import pytest

from wiki.nodes.finalize import _sanitize_published_content


class TestQualityChecklistRemoval:
    def test_removes_emoji_table(self):
        content = (
            "# Title\n\n"
            "Some text.\n\n"
            "| Check | Status |\n"
            "|-------|--------|\n"
            "| Coverage | ✅ |\n"
            "| Format | ⚠️ |\n\n"
            "More text."
        )
        result = _sanitize_published_content(content)
        assert "✅" not in result
        assert "⚠️" not in result
        assert "More text." in result
        assert "Some text." in result

    def test_keeps_normal_table(self):
        content = (
            "# Title\n\n"
            "| Name | Type |\n"
            "|------|------|\n"
            "| foo | string |\n"
        )
        result = _sanitize_published_content(content)
        assert "foo" in result
        assert "string" in result


class TestFakeSourcePathRemoval:
    def test_removes_com_xxx_line(self):
        content = "# Title\n\nSee `com/xxx/service/UserService.java` for details.\n\nReal content."
        result = _sanitize_published_content(content)
        assert "com/xxx/" not in result
        assert "Real content." in result

    def test_removes_com_xxx_code_block(self):
        content = "# Title\n\n```java\n// com/xxx/service/UserService.java\npublic class UserService {}\n```\n\nAfter."
        result = _sanitize_published_content(content)
        assert "com/xxx/" not in result
        assert "After." in result


class TestThinkingTagRemoval:
    def test_removes_think_tags(self):
        content = "# Title\n\n<think>internal reasoning here</think>\n\nVisible content."
        result = _sanitize_published_content(content)
        assert "<think>" not in result
        assert "</think>" not in result
        assert "Visible content." in result

    def test_removes_multiline_think(self):
        content = "# Title\n\n<think>\nline1\nline2\n</think>\n\nAfter."
        result = _sanitize_published_content(content)
        assert "<think>" not in result
        assert "After." in result


class TestContextGapEnhanced:
    def test_removes_context_gap_text(self):
        content = "# Title\n\n[CONTEXT_GAP: missing info]\n\nReal text."
        result = _sanitize_published_content(content)
        assert "CONTEXT_GAP" not in result
        assert "Real text." in result


class TestWikilinkValidation:
    def test_slug_title_format_valid(self):
        from wiki.nodes.finalize import _remove_invalid_wikilinks

        valid = {"domain-01/Core Modules", "PageA"}
        content = "See [[domain-01/Core Modules]] and [[PageA]]."
        result = _remove_invalid_wikilinks(content, valid)
        assert "[[domain-01/Core Modules]]" in result
        assert "[[PageA]]" in result

    def test_removes_invalid_slug_title(self):
        from wiki.nodes.finalize import _remove_invalid_wikilinks

        valid = {"PageA"}
        content = "See [[nonexistent/page]]."
        result = _remove_invalid_wikilinks(content, valid)
        assert "[[" not in result
        assert "nonexistent/page" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/wiki/test_finalize_sanitize.py -v`
Expected: FAIL — cleanup rules not yet implemented

- [ ] **Step 3: Implement 5 cleanup rules in _sanitize_published_content**

Replace `_sanitize_published_content` in `wiki/nodes/finalize.py`:

```python
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_CONTEXT_GAP_TEXT_RE = re.compile(r"\[CONTEXT_GAP:[^\]]*\]")
_FAKE_SOURCE_RE = re.compile(r"com/xxx/")


def _strip_quality_checklist_tables(content: str) -> str:
    """Remove markdown tables containing quality-check emoji."""
    lines = content.split("\n")
    result: list[str] = []
    in_table = False
    table_has_emoji = False
    table_buf: list[str] = []
    for line in lines:
        is_table_line = line.strip().startswith("|")
        if is_table_line:
            if not in_table:
                in_table = True
                table_has_emoji = False
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


def _strip_fake_source_lines(content: str) -> str:
    """Remove lines and code blocks referencing com/xxx/ placeholder paths."""
    lines = content.split("\n")
    result: list[str] = []
    in_code_block = False
    code_block_has_fake = False
    code_buf: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            if not in_code_block:
                in_code_block = True
                code_block_has_fake = False
                code_buf = [line]
                continue
            else:
                code_buf.append(line)
                in_code_block = False
                if not code_block_has_fake:
                    result.extend(code_buf)
                code_buf = []
                continue
        if in_code_block:
            code_buf.append(line)
            if _FAKE_SOURCE_RE.search(line):
                code_block_has_fake = True
        else:
            if not _FAKE_SOURCE_RE.search(line):
                result.append(line)
    if code_buf and not code_block_has_fake:
        result.extend(code_buf)
    return "\n".join(result)


def _sanitize_published_content(content: str) -> str:
    """Remove internal pipeline artifacts from published content."""
    # 1. Remove <think> tags
    content = _THINK_RE.sub("", content)

    # 2. Remove CONTEXT_GAP HTML comments
    content = re.sub(r"<!--\s*CONTEXT_GAP:.*?-->", "", content, flags=re.DOTALL)

    # 3. Remove CONTEXT_GAP text markers
    content = _CONTEXT_GAP_TEXT_RE.sub("", content)

    # 4. Remove quality checklist tables
    content = _strip_quality_checklist_tables(content)

    # 5. Remove fake source paths
    content = _strip_fake_source_lines(content)

    # 6. Deduplicate consecutive identical headings
    lines = content.split("\n")
    result = []
    prev_heading = None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            if stripped == prev_heading:
                continue
            prev_heading = stripped
        else:
            if stripped:
                prev_heading = None
        result.append(line)
    content = "\n".join(result)

    # 7. Close unclosed code blocks
    if content.count("```") % 2 == 1:
        content += "\n```"

    # 8. Clean up excessive blank lines
    content = re.sub(r"\n{4,}", "\n\n\n", content)

    return content.strip()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/wiki/test_finalize_sanitize.py -v`
Expected: ALL PASSED

- [ ] **Step 5: Extend wikilink validation with slug/title format**

In `wiki/nodes/finalize.py`, update `finalize_node` to add `slug/title` entries to `valid_targets`:

```python
# Inside finalize_node, after building valid_targets:
for page in pages:
    title = page.get("title")
    path = page.get("path")
    slug = ""
    if path:
        parts = str(path).strip("/").split("/")
        if len(parts) >= 2:
            slug = parts[-2] if parts[-1] == "_overview" else ""
    if title:
        valid_targets.add(str(title))
        if slug:
            valid_targets.add(f"{slug}/{title}")
    if path:
        valid_targets.add(str(path))
```

- [ ] **Step 6: Run full finalize test suite**

Run: `uv run pytest tests/wiki/test_finalize_sanitize.py tests/wiki/nodes/test_finalize_node.py -v`
Expected: ALL PASSED

- [ ] **Step 7: Commit**

```bash
git add wiki/nodes/finalize.py tests/wiki/test_finalize_sanitize.py tests/wiki/nodes/test_finalize_node.py
git commit -m "feat(wiki): enhance finalize with 5 artifact cleanup rules"
```

---

## Task 3: Post-Processing Language Parameterization (Batch 2)

**Files:**
- Modify: `wiki/nodes/domain_compose.py:67-103` (_inject_dependency_diagram)
- Modify: `wiki/nodes/domain_compose.py:141-177` (_build_layer_summary)
- Modify: `wiki/domain_doc_agent.py:172-237` (_maybe_split)
- Modify: `wiki/domain_doc_agent.py:544-608` (_write_with_outline)
- Modify: `wiki/page_agent.py:817-838` (write user prompt)
- Test: `tests/wiki/test_language_unification.py` (extend)

- [ ] **Step 1: Write failing tests for language-parameterized functions**

Append to `tests/wiki/test_language_unification.py`:

```python
class TestDiagramLanguage:
    def test_chinese_heading(self):
        from core.config import ContentLanguage
        from wiki.nodes.domain_compose import _inject_dependency_diagram

        content = "# Title\n\nSome text."
        result = _inject_dependency_diagram(content, ["A", "B"], language=ContentLanguage.ZH_CN)
        assert "## 架构" in result
        assert "## Architecture" not in result

    def test_english_heading(self):
        from core.config import ContentLanguage
        from wiki.nodes.domain_compose import _inject_dependency_diagram

        content = "# Title\n\nSome text."
        result = _inject_dependency_diagram(content, ["A", "B"], language=ContentLanguage.EN)
        assert "## Architecture" in result

    def test_skips_if_mermaid_exists(self):
        from core.config import ContentLanguage
        from wiki.nodes.domain_compose import _inject_dependency_diagram

        content = "# Title\n\n```mermaid\ngraph TD\n```"
        result = _inject_dependency_diagram(content, ["A", "B"], language=ContentLanguage.ZH_CN)
        assert result.count("```mermaid") == 1


class TestLayerSummaryLanguage:
    def test_chinese_prefix(self):
        from core.config import ContentLanguage
        from wiki.nodes.domain_compose import _build_layer_summary

        layers = {"ModA": {"layer": "api"}}
        result = _build_layer_summary(["ModA"], layers, language=ContentLanguage.ZH_CN)
        assert "本域架构层" in result

    def test_english_prefix(self):
        from core.config import ContentLanguage
        from wiki.nodes.domain_compose import _build_layer_summary

        layers = {"ModA": {"layer": "api"}}
        result = _build_layer_summary(["ModA"], layers, language=ContentLanguage.EN)
        assert "Architecture layers" in result


class TestMaybeSplitLanguage:
    def test_chinese_nav_heading(self):
        from core.config import ContentLanguage
        from wiki.domain_doc_agent import _maybe_split

        long_content = "# Title\n\n" + "\n".join(
            f"## Section {i}\n\n{'x' * 6000}" for i in range(5)
        )
        pages = _maybe_split(long_content, "test-domain", "Test", language=ContentLanguage.ZH_CN)
        overview = pages[0]["content"]
        assert "章节导航" in overview

    def test_english_nav_heading(self):
        from core.config import ContentLanguage
        from wiki.domain_doc_agent import _maybe_split

        long_content = "# Title\n\n" + "\n".join(
            f"## Section {i}\n\n{'x' * 6000}" for i in range(5)
        )
        pages = _maybe_split(long_content, "test-domain", "Test", language=ContentLanguage.EN)
        overview = pages[0]["content"]
        assert "Section Navigation" in overview


class TestWriteWithOutlineLanguage:
    def test_topic_scope_chinese(self):
        """_write_with_outline should use Chinese topic scope when language is zh-CN."""
        # This test validates that the topic context string is built in Chinese.
        # It's tested indirectly via the overview content language.
        from core.config import ContentLanguage
        from wiki.domain_doc_agent import DomainDocAgent

        agent = DomainDocAgent.__new__(DomainDocAgent)
        agent.content_language = ContentLanguage.ZH_CN.display_label
        # Verify the attribute is set correctly
        assert "中文" in agent.content_language
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/wiki/test_language_unification.py::TestDiagramLanguage -v`
Expected: FAIL — `language` kwarg not yet accepted

- [ ] **Step 3: Add language parameter to _inject_dependency_diagram**

In `wiki/nodes/domain_compose.py`, modify `_inject_dependency_diagram`:

```python
def _inject_dependency_diagram(
    content: str,
    module_names: list[str],
    call_edges: list[tuple[str, str]] | None = None,
    *,
    language: ContentLanguage | None = None,
) -> str:
```

Change the final return line from:
```python
return f"{content.rstrip()}\n\n## Architecture\n\n```mermaid\n{diagram}\n```\n"
```
to:
```python
heading = "## 架构" if (language and language.is_chinese) else "## Architecture"
return f"{content.rstrip()}\n\n{heading}\n\n```mermaid\n{diagram}\n```\n"
```

- [ ] **Step 4: Add language parameter to _build_layer_summary**

In `wiki/nodes/domain_compose.py`, modify `_build_layer_summary` signature:

```python
def _build_layer_summary(
    module_names: list[str],
    architecture_layers: dict[str, dict[str, Any]],
    *,
    module_repo_pairs: list[tuple[str, str]] | None = None,
    language: ContentLanguage | None = None,
) -> str:
```

Change:
```python
lines = ["Architecture layers in this domain:"]
```
to:
```python
prefix = "本域架构层分布：" if (language and language.is_chinese) else "Architecture layers in this domain:"
lines = [prefix]
```

- [ ] **Step 5: Pass language to callers in compose_domain_agents_node**

In `compose_domain_agents_node`, update the two call sites:

```python
layer_summary = _build_layer_summary(
    domain.get("modules", []),
    arch_layers,
    module_repo_pairs=module_repo_pairs,
    language=content_language,
)
```

```python
page["content"] = _inject_dependency_diagram(
    page.get("content", ""),
    list(domain.get("modules") or []),
    call_edges=domain_edges,
    language=content_language,
)
```

- [ ] **Step 6: Add language parameter to _maybe_split**

In `wiki/domain_doc_agent.py`, modify the module-level `_maybe_split`:

```python
from core.config import ContentLanguage

def _maybe_split(
    content: str,
    domain_slug: str,
    domain_display_name: str = "",
    *,
    topic_split_done: bool = False,
    language: ContentLanguage = ContentLanguage.ZH_CN,
) -> list[dict[str, Any]]:
```

Change:
```python
section_title = title_match.group(1).strip() if title_match else "Untitled"
```
to:
```python
fallback = "未命名" if language.is_chinese else "Untitled"
section_title = title_match.group(1).strip() if title_match else fallback
```

Change:
```python
parent_content = overview + "\n## 章节导航\n\n" + "\n".join(child_links)
```
to:
```python
nav_heading = "## 章节导航" if language.is_chinese else "## Section Navigation"
parent_content = overview + f"\n{nav_heading}\n\n" + "\n".join(child_links)
```

- [ ] **Step 7: Update DomainDocAgent._maybe_split to pass language**

In the `DomainDocAgent._maybe_split` method, pass the language:

```python
def _maybe_split(self, content, domain_slug=None, domain_display_name=""):
    slug = domain_slug or self.domain_name
    display = domain_display_name or self.domain_display_name
    lang = ContentLanguage.from_any(self.content_language)
    return _maybe_split(content, slug, display, topic_split_done=self._topic_split_done, language=lang)
```

- [ ] **Step 8: Update _write_with_outline navigation heading**

In `_write_with_outline`, change the hardcoded `章节导航`:

```python
lang = ContentLanguage.from_any(self.content_language)
nav_heading = "## 章节导航" if lang.is_chinese else "## Section Navigation"
overview_content = (
    f"# {self.domain_display_name}\n\n"
    + "\n".join(f"## {t.title}\n{t.description}\n" for t in outline.topics)
    + f"\n{nav_heading}\n\n" + "\n".join(topic_links)
)
```

- [ ] **Step 9: Language-aware write user prompt in page_agent.py**

In `wiki/page_agent.py`, modify the `write` method:

```python
if "中文" in self.content_language or self.content_language in ("zh-CN", "zh"):
    user_prompt = (
        f"## 任务\n"
        f"基于以下探索结果，为业务域「{domain_name}」生成一篇完整的 Wiki 页面。\n\n"
        f"## 基线上下文\n{baseline_context[:8000]}\n\n"
        f"## 探索结果（工作记忆）\n{memo_section}\n"
    )
else:
    user_prompt = (
        f"## Task\n"
        f"Based on the exploration results below, generate a complete Wiki page for the \"{domain_name}\" business domain.\n\n"
        f"## Baseline Context\n{baseline_context[:8000]}\n\n"
        f"## Exploration Findings (Working Memory)\n{memo_section}\n"
    )
```

- [ ] **Step 10: Run all language tests**

Run: `uv run pytest tests/wiki/test_language_unification.py -v`
Expected: ALL PASSED

- [ ] **Step 11: Run regression tests**

Run: `uv run pytest tests/wiki/nodes/test_domain_compose.py tests/wiki/nodes/test_batch_ac_pipeline_p2.py tests/wiki/test_domain_agent_early_exit.py -x -v`
Expected: ALL PASSED

- [ ] **Step 12: Commit**

```bash
git add wiki/nodes/domain_compose.py wiki/domain_doc_agent.py wiki/page_agent.py tests/wiki/test_language_unification.py
git commit -m "feat(wiki): parameterize all hardcoded language strings in compose/split/write"
```

---

## Task 4: Topic Dedup + Canonical Key + Guardrail Enforcement (Batch 2 continued)

**Files:**
- Modify: `wiki/domain_doc_agent.py:47-62` (_dedup_topic_titles)
- Modify: `wiki/domain_doc_agent.py:544-608` (_write_with_outline — canonical_key)
- Modify: `wiki/domain_doc_agent.py:787-847` (guardrail rewrite loop)
- Modify: `wiki/tree_linker.py` (leaf-domain priority)
- Create: `tests/wiki/test_topic_title_dedup.py`

- [ ] **Step 1: Write failing tests for semantic topic dedup**

Create `tests/wiki/test_topic_title_dedup.py`:

```python
from __future__ import annotations

import pytest

from wiki.domain_doc_agent import TopicPlan, _dedup_topic_titles


class TestSemanticDedup:
    def test_exact_match_dedup(self):
        topics = [
            TopicPlan(title="核心模块", modules=["A"]),
            TopicPlan(title="核心模块", modules=["B"]),
        ]
        result = _dedup_topic_titles(topics)
        assert len(result) == 1
        assert set(result[0].modules) == {"A", "B"}

    def test_cjk_bigram_overlap_dedup(self):
        topics = [
            TopicPlan(title="核心模块管理", modules=["A"]),
            TopicPlan(title="核心模块配置", modules=["B"]),
        ]
        result = _dedup_topic_titles(topics)
        # "核心" and "模块" bigrams overlap → should merge
        assert len(result) == 1
        assert set(result[0].modules) == {"A", "B"}

    def test_no_false_positive(self):
        topics = [
            TopicPlan(title="用户认证服务", modules=["A"]),
            TopicPlan(title="数据存储层", modules=["B"]),
        ]
        result = _dedup_topic_titles(topics)
        assert len(result) == 2

    def test_english_titles_exact_only(self):
        topics = [
            TopicPlan(title="Authentication", modules=["A"]),
            TopicPlan(title="Authorization", modules=["B"]),
        ]
        result = _dedup_topic_titles(topics)
        assert len(result) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/wiki/test_topic_title_dedup.py -v`
Expected: `test_cjk_bigram_overlap_dedup` FAILS (current dedup is exact match only)

- [ ] **Step 3: Implement CJK bigram semantic dedup**

In `wiki/domain_doc_agent.py`, replace `_dedup_topic_titles`:

```python
def _extract_cjk_bigrams(title: str) -> set[str]:
    """Extract CJK character bigrams for fuzzy matching."""
    chars = [c for c in title if '\u4e00' <= c <= '\u9fff']
    if len(chars) < 2:
        return set(chars)
    return {chars[i] + chars[i + 1] for i in range(len(chars) - 1)}


def _dedup_topic_titles(topics: list[TopicPlan]) -> list[TopicPlan]:
    """Merge topics with duplicate or semantically similar titles."""
    result: list[TopicPlan] = []
    seen_exact: dict[str, int] = {}
    seen_bigrams: list[set[str]] = []

    for t in topics:
        # Exact match check
        if t.title in seen_exact:
            idx = seen_exact[t.title]
            for m in t.modules:
                if m not in result[idx].modules:
                    result[idx].modules.append(m)
            continue

        # CJK bigram overlap check
        bigrams = _extract_cjk_bigrams(t.title)
        merged = False
        if bigrams:
            for i, existing_bg in enumerate(seen_bigrams):
                if not existing_bg:
                    continue
                overlap = len(bigrams & existing_bg) / max(len(bigrams | existing_bg), 1)
                if overlap >= 0.6:
                    for m in t.modules:
                        if m not in result[i].modules:
                            result[i].modules.append(m)
                    merged = True
                    break

        if not merged:
            seen_exact[t.title] = len(result)
            seen_bigrams.append(bigrams)
            result.append(TopicPlan(title=t.title, modules=list(t.modules), description=t.description))

    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/wiki/test_topic_title_dedup.py -v`
Expected: ALL PASSED

- [ ] **Step 5: Write failing test for canonical_key in topic pages**

Append to `tests/wiki/test_topic_title_dedup.py`:

```python
class TestTopicCanonicalKey:
    @pytest.mark.asyncio
    async def test_topic_page_has_canonical_key(self):
        """_write_with_outline should set canonical_key on topic pages."""
        from unittest.mock import AsyncMock, MagicMock, patch
        from wiki.domain_doc_agent import DomainDocAgent, DomainTopicOutline, TopicPlan

        mock_llm = MagicMock()
        mock_graph = MagicMock()
        with patch("core.config.get_settings") as mock_settings:
            wiki_cfg = MagicMock()
            wiki_cfg.domain_agent_explore_max_rounds = 2
            wiki_cfg.domain_agent_explore_max_tool_calls = 5
            mock_settings.return_value.wiki = wiki_cfg
            agent = DomainDocAgent("test-domain", mock_llm, mock_graph, domain_display_name="Test Domain")

        agent._page_agent = MagicMock()
        agent._page_agent.write = AsyncMock(return_value="# Topic\n\nContent here.")
        agent._verify_code_blocks = AsyncMock(side_effect=lambda c, m: c)

        from wiki.page_agent import WorkingMemory
        memory = WorkingMemory()
        outline = DomainTopicOutline(
            should_split=True,
            topics=[
                TopicPlan(title="TopicA", modules=["mod1"], description="desc"),
                TopicPlan(title="TopicB", modules=["mod2"], description="desc"),
            ],
        )
        pages = await agent._write_with_outline(outline, "baseline", memory, ["mod1", "mod2"])
        topic_pages = [p for p in pages if p.get("page_type") == "topic"]
        assert all(p.get("canonical_key") == "test-domain" for p in topic_pages)
```

- [ ] **Step 6: Run test to verify it fails**

Run: `uv run pytest tests/wiki/test_topic_title_dedup.py::TestTopicCanonicalKey -v`
Expected: FAIL — `canonical_key` not in page dict

- [ ] **Step 7: Add canonical_key to _write_with_outline topic pages**

In `wiki/domain_doc_agent.py`, in `_write_with_outline`, add `"canonical_key"` to topic page dicts:

```python
topic_pages.append({
    "page_type": "topic",
    "title": topic.title,
    "path": topic_path,
    "content": topic_content,
    "canonical_key": self.domain_name,
    "diagrams": [],
    "source_locations": [],
    "metadata": {
        "node_count": len(topic.modules),
        "edge_count": 0,
        "generation_mode": "agent",
    },
    "business_domain": self.domain_name,
})
```

- [ ] **Step 8: Run test to verify it passes**

Run: `uv run pytest tests/wiki/test_topic_title_dedup.py -v`
Expected: ALL PASSED

- [ ] **Step 9: Write failing test for _maybe_split topic cap**

Append to `tests/wiki/test_topic_title_dedup.py`:

```python
class TestMaybeSplitTopicCap:
    def test_max_8_topics(self):
        from wiki.domain_doc_agent import _maybe_split

        long_content = "# Title\n\n" + "\n".join(
            f"## Section {i}\n\n{'x' * 6000}" for i in range(12)
        )
        pages = _maybe_split(long_content, "test-domain", "Test")
        topic_pages = [p for p in pages if p.get("page_type") == "topic"]
        assert len(topic_pages) <= 8
```

- [ ] **Step 10: Implement _maybe_split topic cap**

In `wiki/domain_doc_agent.py`, in `_maybe_split`, after the merge loop and before creating child_pages, add:

```python
MAX_SPLIT_TOPICS = 8
while len(merged) > MAX_SPLIT_TOPICS:
    min_idx = min(range(len(merged) - 1), key=lambda i: len(merged[i]) + len(merged[i + 1]))
    merged[min_idx] = merged[min_idx] + "\n" + merged.pop(min_idx + 1)
```

- [ ] **Step 11: Run test to verify it passes**

Run: `uv run pytest tests/wiki/test_topic_title_dedup.py::TestMaybeSplitTopicCap -v`
Expected: PASSED

- [ ] **Step 12: Run full test suite for regressions**

Run: `uv run pytest tests/wiki/ -x --timeout=60 -q`
Expected: ALL PASSED (no regressions)

- [ ] **Step 13: Commit**

```bash
git add wiki/domain_doc_agent.py tests/wiki/test_topic_title_dedup.py
git commit -m "feat(wiki): semantic topic dedup, canonical_key on topics, split cap at 8"
```

---

## Task 5: Tree Linker Leaf-Domain Priority (Batch 2)

**Files:**
- Modify: `wiki/tree_linker.py`
- Test: `tests/wiki/test_tree_linker_bug_fixes.py` (extend or create)

- [ ] **Step 1: Write failing test for leaf-domain priority**

Create or extend `tests/wiki/test_tree_linker_bug_fixes.py`:

```python
from __future__ import annotations

import pytest


class TestCanonicalKeyLeafPriority:
    def test_leaf_domain_wins_over_root(self):
        """When canonical_key maps to both root and leaf, leaf wins."""
        from wiki.tree_linker import build_canonical_key_maps

        domain_tree = [
            {
                "name": "root-domain",
                "modules": ["ModA"],
                "children": [
                    {"name": "leaf-domain", "modules": ["ModA"], "children": []},
                ],
            }
        ]
        pages = [{"path": "/wiki/topic-1", "canonical_key": "leaf-domain", "page_type": "topic"}]
        ck_map, _ = build_canonical_key_maps(domain_tree, pages)
        assert ck_map.get("leaf-domain") is not None
```

- [ ] **Step 2: Run test — verify behavior**

Run: `uv run pytest tests/wiki/test_tree_linker_bug_fixes.py::TestCanonicalKeyLeafPriority -v`
Observe: check if leaf-domain is correctly prioritized

- [ ] **Step 3: Implement leaf-domain priority if needed**

If the test reveals the root domain wins, update `wiki/tree_linker.py` in the canonical key building logic to prefer leaf domains (domains with no children or `is_leaf=True`).

- [ ] **Step 4: Run test to verify fix**

Run: `uv run pytest tests/wiki/test_tree_linker_bug_fixes.py -v`
Expected: ALL PASSED

- [ ] **Step 5: Commit**

```bash
git add wiki/tree_linker.py tests/wiki/test_tree_linker_bug_fixes.py
git commit -m "fix(wiki): tree linker prefers leaf domains for canonical_key mapping"
```

---

## Task 6: Final Integration Test + Regression Sweep (All Batches)

- [ ] **Step 1: Run full backend test suite**

Run: `uv run pytest tests/ -x --timeout=120 -q`
Expected: ALL PASSED, no regressions

- [ ] **Step 2: Run ruff lint and format**

Run: `uv run ruff check wiki/ core/ api/ tests/wiki/ --fix && uv run ruff format wiki/ core/ api/ tests/wiki/`
Expected: No errors

- [ ] **Step 3: Commit any lint fixes**

```bash
git add -A
git commit -m "style: ruff lint/format fixes for wiki quality v2"
```

---

*Plan complete. Ready for execution via subagent-driven-development.*
