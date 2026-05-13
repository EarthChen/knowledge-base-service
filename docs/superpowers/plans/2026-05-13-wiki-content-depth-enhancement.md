# Wiki Content Depth Enhancement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enhance wiki domain overview pages to cover all core business logic, fix Mermaid validation for domain pages, and improve quality metrics.

**Architecture:** Modify prompt templates to request per-module detailed sections instead of 2-4 code refs, add `implementation_depth` quality metric, increase explore sampling, and pipe domain compose output through Mermaid sanitize/repair.

**Tech Stack:** Python 3.11+, LangGraph pipeline, async/await

**Spec:** `docs/PROPOSALS/PROPOSAL_20260513_183324_wiki-content-depth-enhancement.md`

---

### Task 1: Add `implementation_depth` metric to quality_report.py

**Files:**
- Modify: `wiki/quality_report.py`
- Test: `tests/wiki/test_quality_report.py`

- [ ] **Step 1: Write the failing test**

```python
# In tests/wiki/test_quality_report.py — add to existing test file

def test_implementation_depth_all_modules_have_headings():
    content = """\
## 概述
模块表格...

## 模块详解

### SendGiftHandler
业务职责...
<!-- CODE_REF: SendGiftHandler.handle -->

### OrderService
核心订单逻辑...
<!-- CODE_REF: OrderService.createOrder -->
"""
    qr = evaluate_quality(content, ["SendGiftHandler", "OrderService"])
    assert qr.implementation_depth >= 0.9


def test_implementation_depth_partial_coverage():
    content = """\
## 概述
提到了 SendGiftHandler 和 OrderService

### SendGiftHandler
详细描述...
"""
    qr = evaluate_quality(content, ["SendGiftHandler", "OrderService"])
    assert 0.4 <= qr.implementation_depth <= 0.6


def test_implementation_depth_no_detail():
    content = "## 概述\n只有概要内容，没有模块详解"
    qr = evaluate_quality(content, ["ModA", "ModB", "ModC"])
    assert qr.implementation_depth < 0.1


def test_implementation_depth_empty_modules():
    content = "any content"
    qr = evaluate_quality(content, [])
    assert qr.implementation_depth == 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_quality_report.py -v -k "implementation_depth" 2>&1 | tail -20`
Expected: FAIL — `QualityReport` has no `implementation_depth` attribute

- [ ] **Step 3: Implement `implementation_depth` in quality_report.py**

In `wiki/quality_report.py`:

1. Add regex: `_H3_HEADING_RE = re.compile(r"^### (.+)", re.MULTILINE)`
2. Add `_CODE_REF_RE = re.compile(r"<!-- CODE_REF:\s*(\S+)")`
3. Add field to dataclass: `implementation_depth: float = 0.0`
4. Add helper function:

```python
def _calc_implementation_depth(content: str, module_names: list[str]) -> float:
    if not module_names:
        return 1.0
    h3_headings = set(_H3_HEADING_RE.findall(content))
    code_refs = set(_CODE_REF_RE.findall(content))
    all_markers = h3_headings | code_refs
    detailed = 0
    for m in module_names:
        short = m.rsplit(".", 1)[-1] if "." in m else m
        if any(short.lower() in marker.lower() for marker in all_markers):
            detailed += 1
    return detailed / len(module_names)
```

5. Call in `evaluate_quality` and set on `QualityReport`:

```python
depth = _calc_implementation_depth(content, module_names)
# ... in QualityReport constructor:
implementation_depth=round(depth, 4),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_quality_report.py -v -k "implementation_depth" 2>&1 | tail -20`
Expected: PASS (all 4 tests)

- [ ] **Step 5: Commit**

```bash
git add wiki/quality_report.py tests/wiki/test_quality_report.py
git commit -m "feat: add implementation_depth metric to quality_report"
```

---

### Task 2: Update prompt templates in agent_prompts.py

**Files:**
- Modify: `wiki/agent_prompts.py`

- [ ] **Step 1: Modify AGENT_CORE_CONSTRAINTS code reference rule**

In `wiki/agent_prompts.py`, replace line 39:
```
- 每篇文档应包含 2-4 个代码引用。
```
With:
```
- 每个核心业务模块（入口 Handler/Controller/Consumer、核心 Service）至少包含 1 个代码引用。辅助/配置模块可不包含代码引用。
```

- [ ] **Step 2: Modify AGENT_WRITE_SYSTEM output structure**

Replace the entire `## 输出结构` section (lines ~123-141) with:
```
## 输出结构
直接输出 Markdown（不要 JSON 包装），按以下章节顺序：

1. ## 概述
   - 域的整体业务职责和价值
   - 所有模块及其角色分工（以表格形式）

2. ## 核心业务流程
   - 按业务场景分组（如「送礼流程」「收礼流程」「收益结算」）
   - 每个场景包含 Mermaid sequenceDiagram + 文字描述
   - 场景中涉及的入口模块和核心 Service 详细说明其业务逻辑

3. ## 模块详解
   - 为域内每个核心业务模块生成一个 ### 子章节：
     ### ModuleName
     - 业务职责（2-3句）
     - 核心方法及其逻辑
     - <!-- CODE_REF: key_method -->
   - 入口模块（Handler/Controller/Consumer）和核心 Service 必须详细描述
   - 辅助/配置模块可简要描述职责即可

4. ## 依赖关系
   - 基于探索结果的跨域依赖绘制 Mermaid flowchart
   - 描述模块间依赖和与外部系统的关系
```

- [ ] **Step 3: Modify AGENT_GENERATE_SYSTEM output structure**

Apply the same output structure changes to the `## 输出结构（最终 Markdown 页面）` section in `AGENT_GENERATE_SYSTEM` (lines ~171-177).

- [ ] **Step 4: Commit**

```bash
git add wiki/agent_prompts.py
git commit -m "feat: restructure wiki prompts for full module coverage"
```

---

### Task 3: Update quality exit conditions and timeouts in domain_doc_agent.py

**Files:**
- Modify: `wiki/domain_doc_agent.py`

- [ ] **Step 1: Update timeout defaults**

Change line 22-23:
```python
EXPLORE_TIMEOUT_SEC = int(os.environ.get("EXPLORE_TIMEOUT_SEC", "240"))
WRITE_TIMEOUT_SEC = int(os.environ.get("WRITE_TIMEOUT_SEC", "120"))
```
To:
```python
EXPLORE_TIMEOUT_SEC = int(os.environ.get("EXPLORE_TIMEOUT_SEC", "240"))
WRITE_TIMEOUT_SEC = int(os.environ.get("WRITE_TIMEOUT_SEC", "180"))
```

And in `generate_with_iterations`, change line 276:
```python
total_budget = int(os.environ.get("DOMAIN_AGENT_TIMEOUT_SEC", "600"))
```
To:
```python
total_budget = int(os.environ.get("DOMAIN_AGENT_TIMEOUT_SEC", "900"))
```

- [ ] **Step 2: Update evaluate hook to include implementation_depth**

In `DomainDocAgent.evaluate()` (line ~215), update to include `implementation_depth`:
```python
async def evaluate(self, content: str, module_names: list[str]) -> QualityResult:
    qr = evaluate_quality(content, module_names)
    return QualityResult(
        coverage=qr.coverage,
        citation_density=qr.citation_density,
        context_gap_count=qr.context_gap_count,
        uncovered_modules=qr.uncovered_modules,
        implementation_depth=qr.implementation_depth,
    )
```

Note: `QualityResult` in `wiki/agents/doc_orchestrator.py` may need `implementation_depth` field added. Check and add if missing.

- [ ] **Step 3: Update quality exit conditions**

In `generate_with_iterations`, update the perfect exit (line ~364):
```python
if (
    quality.coverage >= 0.95
    and quality.citation_density >= 0.5
    and getattr(quality, 'implementation_depth', 1.0) >= 0.6
    and quality.context_gap_count == 0
):
```

Update acceptable exit (line ~372):
```python
if iteration >= 2 and quality.coverage >= 0.9 and quality.citation_density >= 0.3 and getattr(quality, 'implementation_depth', 1.0) >= 0.4:
```

Update max iteration (line ~382):
```python
if iteration >= 4:
```

- [ ] **Step 4: Add implementation_depth to iteration logging**

In the log.info("domain_agent_iteration", ...) call, add:
```python
depth=getattr(quality, 'implementation_depth', 0),
```

- [ ] **Step 5: Commit**

```bash
git add wiki/domain_doc_agent.py wiki/agents/doc_orchestrator.py
git commit -m "feat: add implementation_depth to quality gates, increase timeouts"
```

---

### Task 4: Increase explore sampling limits in page_agent.py

**Files:**
- Modify: `wiki/page_agent.py`

- [ ] **Step 1: Increase search_entities sampling**

Find the line (around line 243-248):
```python
items = data.get("results", [])
for item in items[:5]:
```
Change `[:5]` to `[:8]`.

- [ ] **Step 2: Increase query_module_detail sampling**

Find the line (around line 314-323) where method names are sliced:
```python
method_names = [str(m.get("name", "")) for m in methods[:5]]
```
Change `[:5]` to `[:8]`.

- [ ] **Step 3: Commit**

```bash
git add wiki/page_agent.py
git commit -m "feat: increase explore sampling limits 5→8"
```

---

### Task 5: Add Mermaid sanitize to domain compose output

**Files:**
- Modify: `wiki/nodes/domain_compose.py`

- [ ] **Step 1: Add sanitize imports and call after domain generation**

At the top of `wiki/nodes/domain_compose.py`, add import:
```python
from wiki.source_ref_validator import sanitize_wiki_content, repair_broken_mermaid_blocks
```

In `compose_domain_agents_node`, after all domain pages are collected (before `return`), add:
```python
llm = state.get("llm")
known_entities = state.get("entities", [])
for page in pages:
    raw = page.get("content", "")
    page["content"] = sanitize_wiki_content(raw, known_entities)
    if llm is not None:
        page["content"] = await repair_broken_mermaid_blocks(page["content"], llm)
```

Note: Need to verify that `state` has `llm` and `entities` keys. If `llm` is not in state, get it from the outer scope or service context.

- [ ] **Step 2: Commit**

```bash
git add wiki/nodes/domain_compose.py
git commit -m "fix: add Mermaid sanitize/repair to domain compose output"
```

---

### Task 6: Integration test and deployment

- [ ] **Step 1: Run existing tests to ensure no regressions**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/ -x -q 2>&1 | tail -20`
Expected: All existing tests pass

- [ ] **Step 2: Deploy to dev**

Run: `bash scripts/deploy-dev.sh --skip-build`

- [ ] **Step 3: Clean and regenerate a single domain for validation**

Use the trigger script to clean and regenerate:
```bash
bash scripts/trigger_wiki_generate.sh clean-regenerate
```

- [ ] **Step 4: Verify domain page content**

Check that domain overview pages now have:
- `## 模块详解` section with `### ModuleName` subsections
- Each core module has a CODE_REF
- Mermaid diagrams render correctly (no collapsed blocks)

- [ ] **Step 5: Final commit with all changes**

```bash
git add -A
git commit -m "feat: wiki content depth enhancement - full module coverage + Mermaid fix"
```
