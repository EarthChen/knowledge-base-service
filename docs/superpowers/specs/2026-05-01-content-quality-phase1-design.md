# Design Spec: Phase 1 — Content Quality Enhancement

> **Status**: Approved  
> **Created**: 2026-05-01  
> **Scope**: Narrative prompt enhancement + Targeted heal  
> **Source**: `DEEP_ANALYSIS_20260501_085742_wiki_gaps_and_bugs.md` Phase 1

---

## 1. Narrative Prompt Enhancement

### 1.1 Problem

Current `_SYSTEM_WIKI` and `_build_single_page_prompt` produce template-like content:
- Fixed 5-section structure with Chinese headings
- No guidance on WHY/HOW narrative
- Content reads like "API inventory" not "technical story"

### 1.2 Changes

**`_SYSTEM_WIKI` — add narrative guidance:**

```
"You are a technical wiki author writing business domain documentation. "
"Write like a technical blog post — explain WHY these services exist, "
"HOW they collaborate, and WHAT business value they deliver. "
"Output Markdown with Mermaid diagrams. Use Chinese for business descriptions. "
"Do NOT explain frameworks or annotations — focus on business logic and "
"the story behind the architecture."
```

**`_build_single_page_prompt` — relax structure for non-concise mode:**

Replace rigid numbered sections with guided suggestions:
```
Write a wiki page for domain: **{name}**

Before writing, analyze:
1. What is each service's primary business role?
2. How do these services interact? (callers, shared data)
3. Which flows deserve Mermaid diagrams?

Required elements (organize freely):
- Business overview explaining WHY this domain exists
- Core business flow with Mermaid diagram (sequenceDiagram or flowchart)
- Key services with their responsibilities and interactions
- Related topics using [[wiki-link]] notation

{entities_desc}
{data_model_table}
```

**Concise mode (LOW complexity)** — keep current brief format unchanged.

### 1.3 Files to Change

- `wiki/topic_page_composer.py`: `_SYSTEM_WIKI`, `_build_single_page_prompt` (non-concise branch), `_build_sub_page_prompt`
- No schema/model changes needed

---

## 2. Targeted Heal

### 2.1 Problem

Current heal is full regeneration:
- Good sections are discarded along with bad ones
- Heal quality is inconsistent (LLM may produce worse content)
- High token cost for full regen

### 2.2 Design: TargetedHealer

**New file**: `wiki/targeted_healer.py`

**Core approach**: Use LLM to diagnose issues and generate JSON patches, then apply patches programmatically. Fallback to full regen on parse failure.

```python
class TargetedHealer:
    """Diagnose wiki page issues and generate targeted patches."""

    async def heal(self, page: WikiPage, bench: BenchScore, llm, domain_context: str) -> WikiPage:
        """Attempt targeted fix; fallback to full regen."""
        result = await self._diagnose_and_patch(page, bench, llm, domain_context)
        if result:
            return result
        return await self._full_regen(page, bench, llm, domain_context)
```

**Diagnosis prompt:**
```
You are reviewing a wiki page that scored below quality threshold.

Page content:
{page_content}

Quality issues identified:
{bench_hints}

Before fixing, diagnose the root cause for each issue:
- Why is the section weak?
- What specific information should be added?
- Which sections are fine and should NOT be changed?

Return JSON:
{
  "diagnosis": [
    {"issue": "missing_overview_section", "root_cause": "...", "fix": "..."}
  ],
  "patches": [
    {
      "action": "insert_after|replace_section|append",
      "target_heading": "## 业务概述",
      "content": "...markdown content..."
    }
  ],
  "preserved_sections": ["## 核心服务详情"]
}
```

**Patch application logic:**
```python
def _apply_patches(self, content: str, patches: list[dict]) -> str:
    for patch in patches:
        action = patch["action"]
        heading = patch["target_heading"]
        new_content = patch["content"]
        if action == "replace_section":
            content = self._replace_section(content, heading, new_content)
        elif action == "insert_after":
            content = self._insert_after_heading(content, heading, new_content)
        elif action == "append":
            content += "\n\n" + new_content
    return content
```

### 2.3 Integration with heal_pages_node

In `pipeline_nodes.py` `heal_pages_node`:
1. Import `TargetedHealer`
2. Before the current full-regen path, try `TargetedHealer.heal()`
3. If targeted heal succeeds (returns patched content), use it
4. If it fails (JSON parse error, empty patches), fallback to current full-regen

### 2.4 Files to Change

- **New**: `wiki/targeted_healer.py` — TargetedHealer class
- **New**: `tests/wiki/test_targeted_healer.py` — unit tests
- **Modify**: `wiki/pipeline_nodes.py` — `heal_pages_node` to try targeted first

---

## 3. Success Criteria

- [ ] Topic pages read like "technical blog posts" not "API inventories"
- [ ] Heal preserves good sections, only fixes broken ones
- [ ] Heal token cost reduced (patches vs full regen)
- [ ] Existing tests pass
- [ ] New tests for TargetedHealer
