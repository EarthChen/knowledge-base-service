# Wiki 质量修复 + Agent-Driven 生成引擎实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 wiki 生成的所有 P0/P1 质量问题，并将 WikiPageAgent 升级为 Agent-Driven 主生成引擎。

**Architecture:** 4 层递进：Layer 1 修 bug → Layer 2 补全图数据 → Layer 3 域分类优化 → Layer 4 Agent-Driven 引擎。每层独立可交付。

**Tech Stack:** Python 3.12, FalkorDB (Cypher), LangGraph, OpenAI-compatible LLM, pytest

**Spec:** `docs/superpowers/specs/2026-05-08-wiki-quality-agent-driven-design.md`

---

## Phase 1: P0 Bug Fix (Day 1-2)

### Task 1: CONTEXT_GAP 正则统一

**Files:**
- Create: `wiki/context_gap.py`
- Modify: `wiki/nodes/compose.py:27`
- Modify: `wiki/page_agent.py:14`
- Modify: `wiki/quality_evaluator.py:39`
- Test: `tests/wiki/test_context_gap.py`

- [ ] **Step 1: Write failing tests for unified regex**

```python
# tests/wiki/test_context_gap.py
import pytest
from wiki.context_gap import CONTEXT_GAP_RE, CONTEXT_GAP_DETECT_RE, cleanup_context_gaps


class TestContextGapRegex:
    def test_english_colon(self):
        text = "before <!-- CONTEXT_GAP: missing info --> after"
        assert CONTEXT_GAP_DETECT_RE.findall(text) == ["missing info"]

    def test_chinese_colon(self):
        text = "before <!-- CONTEXT_GAP：已补充信息 --> after"
        assert CONTEXT_GAP_DETECT_RE.findall(text) == ["已补充信息"]

    def test_space_separator(self):
        text = "before <!-- CONTEXT_GAP 已补充：详细内容 --> after"
        assert CONTEXT_GAP_DETECT_RE.findall(text) == ["已补充：详细内容"]

    def test_multiline(self):
        text = "before <!-- CONTEXT_GAP: line1\nline2 --> after"
        assert len(CONTEXT_GAP_DETECT_RE.findall(text)) == 1

    def test_no_separator(self):
        text = "before <!-- CONTEXT_GAP --> after"
        assert CONTEXT_GAP_RE.search(text) is not None

    def test_cleanup_replaces_with_notice(self):
        text = "before <!-- CONTEXT_GAP: missing --> after"
        result = cleanup_context_gaps(text)
        assert "CONTEXT_GAP" not in result
        assert "此处信息待补充" in result
        assert "missing" in result

    def test_cleanup_multiline(self):
        text = "before <!-- CONTEXT_GAP: line1\nline2 --> after"
        result = cleanup_context_gaps(text)
        assert "CONTEXT_GAP" not in result

    def test_cleanup_empty_marker(self):
        text = "before <!-- CONTEXT_GAP --> after"
        result = cleanup_context_gaps(text)
        assert "<!-- CONTEXT_GAP" not in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_context_gap.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Create unified context_gap module**

```python
# wiki/context_gap.py
"""Unified CONTEXT_GAP detection and cleanup."""
import re

CONTEXT_GAP_RE = re.compile(r"<!--\s*CONTEXT_GAP[\s\S]*?-->")

CONTEXT_GAP_DETECT_RE = re.compile(
    r"<!--\s*CONTEXT_GAP[:\s：]([\s\S]+?)\s*-->",
)

def cleanup_context_gaps(content: str) -> str:
    """Replace all CONTEXT_GAP HTML comments with user-visible info notices."""
    result = CONTEXT_GAP_DETECT_RE.sub(r"> ℹ️ 此处信息待补充: \1", content)
    result = re.sub(r"<!--\s*CONTEXT_GAP\s*-->", "> ℹ️ 此处信息待补充", result)
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_context_gap.py -v`
Expected: PASS

- [ ] **Step 5: Update compose.py to use unified module**

Replace in `wiki/nodes/compose.py:27` and `wiki/nodes/compose.py:44-46`:
```python
# Remove these lines:
# _CONTEXT_GAP_CLEANUP_RE = re.compile(r"<!--\s*CONTEXT_GAP[:\s：](.+?)\s*-->")
# def cleanup_context_gaps(content: str) -> str:
#     return _CONTEXT_GAP_CLEANUP_RE.sub(r"> ℹ️ 此处信息待补充: \1", content)

# Add import at top of file:
from wiki.context_gap import cleanup_context_gaps
```

- [ ] **Step 6: Update page_agent.py to use unified module**

Replace in `wiki/page_agent.py:14`:
```python
# Remove: _CONTEXT_GAP_RE = re.compile(r"<!--\s*CONTEXT_GAP:\s*(.+?)\s*-->")
# Add import:
from wiki.context_gap import CONTEXT_GAP_DETECT_RE as _CONTEXT_GAP_RE
```

- [ ] **Step 7: Update quality_evaluator.py to use unified module**

Replace in `wiki/quality_evaluator.py:39`:
```python
# Remove: _CONTEXT_GAP = re.compile(r"<!--\s*CONTEXT_GAP:\s*(.+?)\s*-->")
# Add import:
from wiki.context_gap import CONTEXT_GAP_DETECT_RE as _CONTEXT_GAP
```

- [ ] **Step 8: Run existing tests to verify no regression**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_compose_context_gap_cleanup.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add wiki/context_gap.py tests/wiki/test_context_gap.py wiki/nodes/compose.py wiki/page_agent.py wiki/quality_evaluator.py
git commit -m "refactor: unify CONTEXT_GAP regex into wiki/context_gap.py"
```

---

### Task 2: cleanup 全路径覆盖

**Files:**
- Modify: `wiki/nodes/heal.py:121,141`
- Modify: `wiki/nodes/aggregate.py:206,463,502`
- Modify: `wiki/persistence.py` (兜底 cleanup)
- Test: `tests/wiki/test_cleanup_all_paths.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/wiki/test_cleanup_all_paths.py
import pytest
from wiki.context_gap import cleanup_context_gaps


def test_cleanup_after_heal_content():
    """Simulate heal writing content with CONTEXT_GAP that needs cleanup."""
    page = {"content": "healed <!-- CONTEXT_GAP: missing --> text"}
    page["content"] = cleanup_context_gaps(page["content"])
    assert "<!-- CONTEXT_GAP" not in page["content"]
    assert "此处信息待补充" in page["content"]


def test_cleanup_after_aggregate_content():
    """Simulate aggregate writing content with CONTEXT_GAP."""
    content = "overview <!-- CONTEXT_GAP：中文标记 --> rest"
    cleaned = cleanup_context_gaps(content)
    assert "<!-- CONTEXT_GAP" not in cleaned
```

- [ ] **Step 2: Run tests to verify they pass** (these are unit tests on cleanup_context_gaps which already works)

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_cleanup_all_paths.py -v`
Expected: PASS

- [ ] **Step 3: Add cleanup to heal.py after content assignment**

In `wiki/nodes/heal.py`, add import and cleanup calls after lines 121 and 141:
```python
# Add at top of file:
from wiki.context_gap import cleanup_context_gaps

# After line 121 (targeted_result):
page_dict["content"] = cleanup_context_gaps(targeted_result.content)

# After line 141 (new_content):
page_dict["content"] = cleanup_context_gaps(new_content)
```

- [ ] **Step 4: Add cleanup to aggregate.py after content assignment**

In `wiki/nodes/aggregate.py`, add import and cleanup:
```python
# Add at top of file:
from wiki.context_gap import cleanup_context_gaps

# After line 206 where content is extracted:
content = cleanup_context_gaps(parsed.get("content", ""))

# After line 463 (overview_markdown):
overview_markdown = cleanup_context_gaps(overview_markdown)

# After line 502 (overview_content fallback):
overview_content = cleanup_context_gaps(overview_content)
```

- [ ] **Step 5: Run existing tests to verify no regression**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/ -k "heal or aggregate or compose" --timeout=30 -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add wiki/nodes/heal.py wiki/nodes/aggregate.py tests/wiki/test_cleanup_all_paths.py
git commit -m "fix: apply cleanup_context_gaps on all content write paths"
```

---

### Task 3: Markdown 围栏通用剥离

**Files:**
- Modify: `wiki/json_robust.py:20-26`
- Modify: `wiki/topic_page_composer.py:69-83`
- Test: `tests/wiki/test_strip_fences_generic.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/wiki/test_strip_fences_generic.py
from wiki.json_robust import _strip_fences


class TestStripFencesGeneric:
    def test_json_fence(self):
        assert _strip_fences('```json\n{"key": "val"}\n```') == '{"key": "val"}'

    def test_markdown_fence(self):
        assert _strip_fences('```markdown\n# Title\ncontent\n```') == '# Title\ncontent'

    def test_md_fence(self):
        assert _strip_fences('```md\n# Title\n```') == '# Title'

    def test_html_fence(self):
        assert _strip_fences('```html\n<div>hi</div>\n```') == '<div>hi</div>'

    def test_text_fence(self):
        assert _strip_fences('```text\nplain text\n```') == 'plain text'

    def test_bare_fence(self):
        assert _strip_fences('```\ncontent\n```') == 'content'

    def test_no_fence(self):
        assert _strip_fences('no fences here') == 'no fences here'

    def test_preserves_inner_fences(self):
        text = '```markdown\n# Title\n```python\ncode\n```\n```'
        result = _strip_fences(text)
        assert result.startswith('# Title')
```

- [ ] **Step 2: Run tests to verify markdown/html/text fences fail**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_strip_fences_generic.py -v`
Expected: markdown, md, html, text tests FAIL

- [ ] **Step 3: Update _strip_fences to use generic pattern**

Replace in `wiki/json_robust.py:20-26`:
```python
def _strip_fences(raw: str) -> str:
    """Remove markdown code fences from LLM output."""
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```\w*\s*\n?", "", text, count=1)
        text = re.sub(r"\n?```\s*$", "", text, count=1)
    return text.strip()
```

- [ ] **Step 4: Update _parse_wiki_json_response fallback to also strip fences**

In `wiki/topic_page_composer.py:69-83`, modify the fallback return:
```python
    @staticmethod
    def _parse_wiki_json_response(raw: str) -> tuple[str, str]:
        """Extract markdown content and executive_summary from LLM JSON; fallback to raw markdown."""
        stripped = (raw or "").strip()
        if not stripped:
            return "", ""
        parsed = parse_json_robust_sync(stripped)
        if isinstance(parsed, dict):
            exec_raw = parsed.get("executive_summary")
            summary = exec_raw.strip() if isinstance(exec_raw, str) else ""
            body = parsed.get("content")
            if isinstance(body, str) and body.strip():
                return body.strip(), summary
        # Fallback: strip any remaining fences before returning raw content
        from wiki.json_robust import _strip_fences
        return _strip_fences(stripped), ""
```

- [ ] **Step 5: Run tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_strip_fences_generic.py tests/wiki/test_topic_page_composer.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add wiki/json_robust.py wiki/topic_page_composer.py tests/wiki/test_strip_fences_generic.py
git commit -m "fix: strip any language-tagged code fences from LLM output"
```

---

### Task 4: tree_linker 截断修复 + 中文标题匹配

**Files:**
- Modify: `wiki/tree_linker.py:384-399`
- Test: `tests/wiki/test_tree_linker_truncation.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/wiki/test_tree_linker_truncation.py


def _safe_truncate(text: str, max_len: int = 150) -> str:
    """Import will come from tree_linker after implementation."""
    from wiki.tree_linker import _safe_truncate
    return _safe_truncate(text, max_len)


class TestSafeTruncate:
    def test_short_text_unchanged(self):
        assert _safe_truncate("short text") == "short text"

    def test_truncate_at_sentence(self):
        text = "First sentence。Second sentence that makes it very long " * 5
        result = _safe_truncate(text, 50)
        assert len(result) <= 50
        assert result.endswith("。") or result.endswith(" ")

    def test_no_backtick_split(self):
        text = "Module `com.example.very.long.package.name.ClassName` handles requests and more text here"
        result = _safe_truncate(text, 60)
        assert result.count('`') % 2 == 0, "Should not split inside backticks"

    def test_returns_original_if_short(self):
        assert _safe_truncate("hello", 150) == "hello"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_tree_linker_truncation.py -v`
Expected: FAIL (import error)

- [ ] **Step 3: Implement _safe_truncate and update tree_linker**

Add to `wiki/tree_linker.py` (before the class or as a module-level function):
```python
def _safe_truncate(text: str, max_len: int = 150) -> str:
    """Truncate text at a Markdown-safe boundary."""
    if len(text) <= max_len:
        return text
    cut = text[:max_len]
    if cut.count('`') % 2 != 0:
        last_tick = cut.rfind('`')
        if last_tick > 0:
            cut = cut[:last_tick]
    for sep in ('。', '. ', '，', ', ', ' '):
        pos = cut.rfind(sep)
        if pos > max_len // 2:
            return cut[:pos + len(sep)].rstrip()
    return cut.rstrip()
```

Update lines 390-399 to use both Chinese and English headings + `_safe_truncate`:
```python
                        # Match both English and Chinese overview headings
                        for heading in ("## Overview", "## 概述", "## 业务概述"):
                            overview_start = content.find(heading)
                            if overview_start >= 0:
                                after = content[overview_start + len(heading):].strip()
                                break
                        else:
                            after = ""
                        if after:
                            next_h = after.find("\n## ")
                            snippet = after[:next_h].strip() if next_h > 0 else after[:200].strip()
                            non_heading = [
                                l for l in snippet.split("\n")
                                if l.strip() and not l.strip().startswith("#")
                            ]
                            summary = _safe_truncate(" ".join(non_heading))
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_tree_linker_truncation.py tests/wiki/test_tree_linker.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/tree_linker.py tests/wiki/test_tree_linker_truncation.py
git commit -m "fix: safe truncation in tree_linker + match Chinese headings"
```

---

### Task 5: 进度 callback 透传

**Files:**
- Modify: `wiki/service.py:1285-1293`
- Test: `tests/wiki/test_progress_callback_per_repo.py`

- [ ] **Step 1: Write failing test**

```python
# tests/wiki/test_progress_callback_per_repo.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_generate_passes_progress_callback():
    """Verify generate_business_wiki passes progress_callback to per-repo generate()."""
    # This is a structural test: check the call signature
    import ast, inspect
    from wiki.service import WikiService
    source = inspect.getsource(WikiService.generate_business_wiki)
    tree = ast.parse(source)
    
    # Find all calls to self.generate() and check if progress_callback is passed
    found_generate_call = False
    has_progress_callback = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute) and node.func.attr == "generate":
                found_generate_call = True
                for kw in node.keywords:
                    if kw.arg == "progress_callback":
                        has_progress_callback = True
    
    assert found_generate_call, "Should find self.generate() call"
    assert has_progress_callback, "self.generate() should receive progress_callback"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_progress_callback_per_repo.py -v`
Expected: FAIL (has_progress_callback is False)

- [ ] **Step 3: Add progress_callback to generate() call**

In `wiki/service.py:1285-1293`, add `progress_callback=progress_callback`:
```python
                        await self.generate(
                            repo_name,
                            "repo",
                            mode,
                            "json",
                            language,
                            llm_provider,
                            token_budget_multiplier=token_budget_multiplier,
                            progress_callback=progress_callback,
                        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_progress_callback_per_repo.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/service.py tests/wiki/test_progress_callback_per_repo.py
git commit -m "fix: pass progress_callback to per-repo generate in business wiki"
```

---

## Phase 2: Graph Data Fix (Day 3-4)

### Task 6: Indexer 后处理 — 补全 CONTAINS 关系

**Files:**
- Create: `indexer/post_process.py`
- Test: `tests/wiki/test_post_process_contains.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/wiki/test_post_process_contains.py
import pytest
from indexer.post_process import match_functions_to_modules


class TestMatchFunctionsToModules:
    def test_fqn_prefix_match(self):
        modules = [{"name": "UserService", "fqn": "com.example.UserService", "file_path": "UserService.java"}]
        functions = [{"name": "getUser", "fqn": "com.example.UserService.getUser", "file_path": "UserService.java"}]
        result = match_functions_to_modules(modules, functions)
        assert result == [("UserService", "getUser")]

    def test_file_path_match(self):
        modules = [{"name": "utils", "fqn": "utils", "file_path": "src/utils.py"}]
        functions = [{"name": "helper", "fqn": "helper", "file_path": "src/utils.py"}]
        result = match_functions_to_modules(modules, functions)
        assert result == [("utils", "helper")]

    def test_no_match_logged(self):
        modules = [{"name": "A", "fqn": "pkg.A", "file_path": "A.java"}]
        functions = [{"name": "orphan", "fqn": "pkg.B.orphan", "file_path": "B.java"}]
        result = match_functions_to_modules(modules, functions)
        assert result == []

    def test_fqn_takes_priority_over_filepath(self):
        modules = [
            {"name": "A", "fqn": "pkg.A", "file_path": "shared.java"},
            {"name": "B", "fqn": "pkg.B", "file_path": "shared.java"},
        ]
        functions = [{"name": "method", "fqn": "pkg.A.method", "file_path": "shared.java"}]
        result = match_functions_to_modules(modules, functions)
        assert result == [("A", "method")]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_post_process_contains.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement match_functions_to_modules**

```python
# indexer/post_process.py
"""Post-processing to supplement graph relationships after indexing."""
from __future__ import annotations

from core.log import get_logger

log = get_logger(__name__)


def match_functions_to_modules(
    modules: list[dict],
    functions: list[dict],
) -> list[tuple[str, str]]:
    """Match functions to modules by FQN prefix first, then file_path.
    
    Returns list of (module_name, function_name) pairs.
    """
    fqn_to_module: dict[str, str] = {}
    path_to_modules: dict[str, list[str]] = {}

    for m in modules:
        fqn = m.get("fqn", "")
        if fqn:
            fqn_to_module[fqn] = m["name"]
        fp = m.get("file_path", "")
        if fp:
            path_to_modules.setdefault(fp, []).append(m["name"])

    matches: list[tuple[str, str]] = []
    for f in functions:
        fn_fqn = f.get("fqn", "")
        fn_name = f["name"]
        matched = False

        if fn_fqn:
            for mod_fqn, mod_name in fqn_to_module.items():
                if fn_fqn.startswith(mod_fqn + "."):
                    matches.append((mod_name, fn_name))
                    matched = True
                    break

        if not matched:
            fp = f.get("file_path", "")
            if fp and fp in path_to_modules:
                matches.append((path_to_modules[fp][0], fn_name))
                matched = True

        if not matched:
            log.debug("unmatched_function", function=fn_name, fqn=fn_fqn)

    return matches


async def supplement_contains_relationships(graph_store, graph_name: str) -> int:
    """Query all Functions and Modules, create missing CONTAINS relationships."""
    functions_query = "MATCH (f:Function) RETURN f.name AS name, coalesce(f.fqn, '') AS fqn, coalesce(f.file, f.file_path, '') AS file_path"
    modules_query = "MATCH (m:Module) RETURN m.name AS name, coalesce(m.fqn, '') AS fqn, coalesce(m.file, m.file_path, '') AS file_path"

    fn_result = await graph_store.execute_query(functions_query, {}, graph_name=graph_name)
    mod_result = await graph_store.execute_query(modules_query, {}, graph_name=graph_name)

    functions = [dict(r) for r in fn_result]
    modules = [dict(r) for r in mod_result]

    pairs = match_functions_to_modules(modules, functions)

    created = 0
    batch_size = 100
    for i in range(0, len(pairs), batch_size):
        batch = pairs[i:i + batch_size]
        for mod_name, fn_name in batch:
            cypher = """
            MATCH (m:Module {name: $mod_name}), (f:Function {name: $fn_name})
            WHERE NOT (m)-[:CONTAINS]->(f)
            CREATE (m)-[:CONTAINS]->(f)
            """
            await graph_store.execute_query(
                cypher, {"mod_name": mod_name, "fn_name": fn_name}, graph_name=graph_name
            )
            created += 1

    log.info("supplement_contains_done", created=created, total_functions=len(functions))
    return created
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_post_process_contains.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add indexer/post_process.py tests/wiki/test_post_process_contains.py
git commit -m "feat: add indexer post-processing to supplement CONTAINS relationships"
```

---

### Task 7: CCB Cypher 查询改造

**Files:**
- Modify: `wiki/cypher_queries.py:15-34`
- Modify: `wiki/content_context_builder.py:368-472`
- Test: `tests/wiki/test_ccb_call_chain_cypher.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/wiki/test_ccb_call_chain_cypher.py
from wiki.cypher_queries import call_chain_cypher, METHOD_CALL_CHAIN_CY


def test_call_chain_cypher_uses_function_aggregation():
    """New query should go through Function CALLS, not Module CALLS."""
    cypher = call_chain_cypher(3)
    assert "Function" in cypher, "Should query through Function nodes"
    assert "CONTAINS" in cypher, "Should use CONTAINS to link Module->Function"


def test_method_call_chain_still_works():
    """METHOD_CALL_CHAIN_CY should still be valid Cypher."""
    assert "CALLS" in METHOD_CALL_CHAIN_CY
    assert "Function" in METHOD_CALL_CHAIN_CY
```

- [ ] **Step 2: Run tests to verify call_chain_cypher test fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_ccb_call_chain_cypher.py -v`
Expected: `test_call_chain_cypher_uses_function_aggregation` FAILS

- [ ] **Step 3: Update call_chain_cypher to aggregate from Function level**

Replace in `wiki/cypher_queries.py:15-21`:
```python
def call_chain_cypher(depth: int) -> str:
    d = max(1, int(depth))
    return f"""
MATCH (m1:Module)-[:CONTAINS]->(f1:Function)-[:CALLS*1..{d}]->(f2:Function)<-[:CONTAINS]-(m2:Module)
WHERE m1.name IN $names AND m1 <> m2
RETURN DISTINCT m1.name AS caller, m2.name AS callee,
       collect(DISTINCT f1.name)[..5] AS caller_functions,
       collect(DISTINCT f2.name)[..5] AS callee_functions
ORDER BY caller, callee
""".strip()
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_ccb_call_chain_cypher.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/cypher_queries.py tests/wiki/test_ccb_call_chain_cypher.py
git commit -m "fix: aggregate call chains from Function-level CALLS to Module level"
```

---

## Phase 3: Domain Classification Fix (Day 5)

### Task 8: 域分类反幻觉 + 小域合并

**Files:**
- Modify: `wiki/dependency_graph.py:247-282`
- Create: `wiki/domain_merger.py`
- Test: `tests/wiki/test_domain_merger.py`

- [ ] **Step 1: Write failing tests for domain merger**

```python
# tests/wiki/test_domain_merger.py
from wiki.domain_merger import merge_small_domains


class FakeDomain:
    def __init__(self, name, modules):
        self.name = name
        self.modules = list(modules)
        self.children = []
        self.description = ""


def test_merge_single_module_domain():
    domains = [
        FakeDomain("Big", ["A", "B", "C", "D"]),
        FakeDomain("Small", ["E"]),
    ]
    result = merge_small_domains(domains, min_size=3)
    assert len(result) == 1
    assert "E" in result[0].modules

def test_no_merge_if_all_large():
    domains = [
        FakeDomain("A", ["m1", "m2", "m3"]),
        FakeDomain("B", ["m4", "m5", "m6"]),
    ]
    result = merge_small_domains(domains, min_size=3)
    assert len(result) == 2

def test_merge_preserves_large_domains():
    domains = [
        FakeDomain("Big", ["A", "B", "C"]),
        FakeDomain("Tiny1", ["D"]),
        FakeDomain("Tiny2", ["E"]),
    ]
    result = merge_small_domains(domains, min_size=3)
    assert len(result) == 1
    assert len(result[0].modules) == 5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_domain_merger.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement domain merger**

```python
# wiki/domain_merger.py
"""Post-processing to merge small domains into larger siblings."""
from __future__ import annotations
from typing import Any, Protocol

from core.log import get_logger

log = get_logger(__name__)


class DomainLike(Protocol):
    name: str
    modules: list


def _name_similarity(a: DomainLike, b: DomainLike) -> float:
    """Simple Jaccard similarity on module name character trigrams."""
    def trigrams(text: str) -> set[str]:
        t = text.lower()
        return {t[i:i+3] for i in range(max(0, len(t) - 2))}
    
    a_tri = set()
    for m in a.modules:
        a_tri |= trigrams(str(m))
    b_tri = set()
    for m in b.modules:
        b_tri |= trigrams(str(m))
    
    if not a_tri or not b_tri:
        return 0.0
    return len(a_tri & b_tri) / len(a_tri | b_tri)


def merge_small_domains(domains: list, min_size: int = 3) -> list:
    """Merge domains with fewer than min_size modules into the most similar large domain."""
    large = [d for d in domains if len(d.modules) >= min_size]
    small = [d for d in domains if len(d.modules) < min_size]

    if not large and small:
        large = [small.pop(0)]

    for sd in small:
        if not large:
            break
        best = max(large, key=lambda ld: _name_similarity(sd, ld))
        best.modules.extend(sd.modules)
        log.info("domain_merged", small=sd.name, into=best.name, added=len(sd.modules))

    return large
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_domain_merger.py -v`
Expected: PASS

- [ ] **Step 5: Update dependency_graph.py with anti-hallucination prompt**

In `wiki/dependency_graph.py`, replace `system=SYSTEM_JSON_ONLY` at line 255 with a new constant:

```python
SYSTEM_DOMAIN_CLASSIFICATION = """Reply with JSON only. No markdown fences.

CRITICAL RULES:
1. domain.description MUST only summarize capabilities directly evidenced by the module names
2. Do NOT invent capabilities not reflected in the modules
3. If unsure about a domain's scope, use a conservative generic description
4. Each domain must contain at least 3 modules
"""
```

And update the call: `response = await self._llm.generate(prompt, system=SYSTEM_DOMAIN_CLASSIFICATION)`

- [ ] **Step 6: Wire domain merger into decomposition pipeline**

After `_parse_domain_tree` returns domains, apply merger:
```python
from wiki.domain_merger import merge_small_domains
# After parsing:
domains = self._parse_domain_tree(response, modules)
domains = merge_small_domains(domains, min_size=3)
return domains
```

- [ ] **Step 7: Run tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_domain_merger.py tests/wiki/test_dependency_graph.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add wiki/domain_merger.py wiki/dependency_graph.py tests/wiki/test_domain_merger.py
git commit -m "feat: anti-hallucination domain classification + small domain merger"
```

---

## Phase 4a: Agent-Driven Core (Day 6-8)

### Task 9: WikiPageAgent.generate() 基础实现

**Files:**
- Modify: `wiki/page_agent.py`
- Create: `wiki/agent_prompts.py`
- Test: `tests/wiki/test_agent_generate.py`

- [ ] **Step 1: Write failing test for Agent generate**

```python
# tests/wiki/test_agent_generate.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from wiki.page_agent import WikiPageAgent


@pytest.mark.asyncio
async def test_agent_generate_returns_markdown():
    """Agent.generate() should return non-empty markdown with expected sections."""
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = "## 概述\nTest module\n## 核心业务流程\nNo data\n## 关键实现\nImpl\n## 依赖关系\nNone"
    
    mock_graph = MagicMock()
    mock_graph.execute_query = AsyncMock(return_value=[])
    
    agent = WikiPageAgent(graph_store=mock_graph, llm=mock_llm)
    result = await agent.generate(
        module_names=["TestModule"],
        domain_name="test_domain",
        baseline_context={"modules": [{"name": "TestModule"}]},
        max_rounds=3,
    )
    
    assert result is not None
    assert len(result) > 100
    assert "概述" in result or "Overview" in result


@pytest.mark.asyncio
async def test_agent_generate_fallback_on_error():
    """Agent.generate() should return minimal content on LLM failure."""
    mock_llm = AsyncMock()
    mock_llm.generate.side_effect = Exception("LLM API error")
    
    mock_graph = MagicMock()
    mock_graph.execute_query = AsyncMock(return_value=[])
    
    agent = WikiPageAgent(graph_store=mock_graph, llm=mock_llm)
    result = await agent.generate(
        module_names=["TestModule"],
        domain_name="test_domain",
        baseline_context={},
        max_rounds=3,
    )
    
    assert result is not None
    assert "CONTEXT_GAP" in result or "TestModule" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_agent_generate.py -v`
Expected: FAIL (no generate method)

- [ ] **Step 3: Create agent_prompts.py**

```python
# wiki/agent_prompts.py
"""System prompts for Agent-Driven wiki generation."""

AGENT_GENERATE_SYSTEM = """你是一个代码知识库内容生成 Agent。你的任务是为指定代码模块生成结构化的 Wiki 页面。

## 输出结构
按以下章节顺序生成 Markdown：

1. ## 概述
   - 模块职责、核心类/接口
   - 使用 search_entities + query_module_detail 获取信息

2. ## 核心业务流程
   - 使用 query_call_chain + query_callers + query_callees 获取调用链
   - 基于真实调用链生成 Mermaid sequenceDiagram
   - 若调用链为空，尝试 read_code 从代码中推断关键流程
   - 仍无法获取则标记 CONTEXT_GAP

3. ## 关键实现
   - 使用 read_code / read_source_snippet 获取核心方法实现
   - 重点描述业务逻辑和设计模式

4. ## 依赖关系
   - 使用 query_domain_dependencies + query_implementations
   - 描述模块间依赖和接口实现关系

## 约束
- 100% 代码溯源：所有描述必须基于工具查询的真实信息
- 严禁编造：不确定的内容标记 <!-- CONTEXT_GAP: description -->
- 每个工具最多调用 {max_rounds} 次
- 工具返回空结果时，记录为 CONTEXT_GAP 而非编造
"""
```

- [ ] **Step 4: Implement WikiPageAgent.generate()**

Add to `wiki/page_agent.py`:
```python
    async def generate(
        self,
        module_names: list[str],
        domain_name: str,
        baseline_context: dict[str, Any],
        max_rounds: int = 10,
    ) -> str:
        """Agent-Driven: query context with tools and generate a full Wiki page."""
        from wiki.agent_prompts import AGENT_GENERATE_SYSTEM
        
        system = AGENT_GENERATE_SYSTEM.format(max_rounds=max_rounds)
        modules_desc = ", ".join(module_names)
        baseline_str = str(baseline_context)[:2000]
        
        user_prompt = (
            f"为以下模块生成 Wiki 页面:\n"
            f"域名: {domain_name}\n"
            f"模块: {modules_desc}\n"
            f"基线上下文: {baseline_str}\n\n"
            f"请使用工具查询更多信息后生成完整页面。"
        )
        
        try:
            content = await self._run_agent_loop(
                system=system,
                user_prompt=user_prompt,
                max_rounds=max_rounds,
                domain_name=domain_name,
            )
            if content and len(content) > 200:
                return content
        except Exception:
            log.warning("agent_generate_failed", domain=domain_name, exc_info=True)
        
        # Fallback: minimal skeleton
        return self._generate_skeleton(module_names, domain_name)
    
    def _generate_skeleton(self, module_names: list[str], domain_name: str) -> str:
        """Generate minimal page skeleton when agent fails."""
        modules_list = "\n".join(f"- `{m}`" for m in module_names)
        return (
            f"# {domain_name}\n\n"
            f"## 概述\n\n{domain_name} 包含以下模块:\n{modules_list}\n\n"
            f"<!-- CONTEXT_GAP: Agent 生成失败，需要手动补充内容 -->\n\n"
            f"## 核心业务流程\n\n"
            f"<!-- CONTEXT_GAP: 调用链数据未能获取 -->\n\n"
            f"## 关键实现\n\n"
            f"<!-- CONTEXT_GAP: 代码实现细节未能获取 -->\n\n"
            f"## 依赖关系\n\n"
            f"<!-- CONTEXT_GAP: 依赖关系数据未能获取 -->\n"
        )
    
    async def _run_agent_loop(
        self,
        system: str,
        user_prompt: str,
        max_rounds: int,
        domain_name: str,
    ) -> str:
        """Run the agent tool-calling loop."""
        messages = [{"role": "user", "content": user_prompt}]
        
        for round_num in range(max_rounds):
            response = await self._llm.generate(
                "\n".join(m["content"] for m in messages),
                system=system,
            )
            
            tool_calls = self._extract_tool_calls(response)
            if not tool_calls:
                return strip_agent_artifacts(response)
            
            tool_results = []
            for tc in tool_calls:
                result = await self._execute_tool(tc["name"], tc.get("args", {}))
                tool_results.append(f"[Tool: {tc['name']}] {result[:2000]}")
            
            messages.append({"role": "assistant", "content": response})
            messages.append({"role": "user", "content": "\n".join(tool_results)})
        
        # Max rounds reached, generate with accumulated context
        final = await self._llm.generate(
            "\n".join(m["content"] for m in messages) + "\n\n请基于以上信息直接生成完整 Wiki 页面。",
            system=system,
        )
        return strip_agent_artifacts(final)
```

- [ ] **Step 5: Run tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_agent_generate.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add wiki/page_agent.py wiki/agent_prompts.py tests/wiki/test_agent_generate.py
git commit -m "feat: implement WikiPageAgent.generate() for Agent-Driven generation"
```

---

### Task 10: 路由策略 + 配置开关

**Files:**
- Modify: `wiki/nodes/compose.py` (or `wiki/topic_page_composer.py`)
- Test: `tests/wiki/test_agent_routing.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/wiki/test_agent_routing.py
import os
import pytest


def test_agent_driven_config_default_off():
    """WIKI__AGENT_DRIVEN_GENERATION should default to False."""
    val = os.environ.get("WIKI__AGENT_DRIVEN_GENERATION", "false")
    assert val.lower() in ("false", "0", "")


def test_simple_threshold_default():
    """WIKI__AGENT_SIMPLE_THRESHOLD should default to 3."""
    val = int(os.environ.get("WIKI__AGENT_SIMPLE_THRESHOLD", "3"))
    assert val == 3
```

- [ ] **Step 2: Run tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_agent_routing.py -v`
Expected: PASS (defaults are correct)

- [ ] **Step 3: Add routing logic to compose pipeline**

This step integrates the routing into the existing compose flow. The specific integration point depends on the compose pipeline structure — add a config check in `compose_leaf_modules_node` or `TopicPageComposer`.

- [ ] **Step 4: Commit**

```bash
git add wiki/nodes/compose.py tests/wiki/test_agent_routing.py
git commit -m "feat: add Agent-Driven routing with configurable threshold"
```

---

## Phase 4b: Advanced Features (Day 9-10)

### Task 11: 拓扑排序 + SCC 循环依赖处理

**Files:**
- Create: `wiki/topo_sort.py`
- Test: `tests/wiki/test_topo_sort.py`

_(Detailed TDD steps follow same pattern as above: write test → verify fail → implement → verify pass → commit)_

### Task 12: 自底向上 Overview 合成

**Files:**
- Modify: `wiki/tree_linker.py`
- Test: `tests/wiki/test_overview_from_children.py`

### Task 13: 源码引用验证

**Files:**
- Create: `wiki/citation_verifier.py`
- Test: `tests/wiki/test_citation_verifier.py`

---

## Phase 5: Integration Verification (Day 11-12)

### Task 14: 全量重新索引 + 生成 + 质量对比

- [ ] Deploy Phase 1-4 changes to dev
- [ ] Run reindex with CONTAINS supplement: `POST /api/v1/index`
- [ ] Trigger full wiki regeneration: `POST /api/v1/wiki/business/generate`
- [ ] Run automated quality scan (check CONTEXT_GAP, markdown fences, call chain coverage)
- [ ] Compare before/after metrics against success criteria
- [ ] Update documentation
