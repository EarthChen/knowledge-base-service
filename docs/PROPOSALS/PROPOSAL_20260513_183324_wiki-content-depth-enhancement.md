# Proposal: Wiki Domain Page Content Depth Enhancement

**Status**: AwaitingApproval
**Created**: 2026-05-13
**Author**: AI Agent

## Background

Wiki domain overview pages (e.g., `/__domains__/message-business-processing/_overview`)
currently only include 2-4 code references in the "关键实现" section, even when the domain
contains 15+ modules. Users expect the wiki to describe **all core business logic
implementations**, not just a curated selection.

Additionally, domain pages produced by `compose_domain_agents_node` bypass Mermaid
validation/repair entirely, causing broken diagrams to be published as-is.

### Root Causes

1. **Prompt constraint**: `AGENT_CORE_CONSTRAINTS` line 39 says "每篇文档应包含 2-4 个代码引用"
2. **Output structure**: `AGENT_WRITE_SYSTEM` defines "关键实现" as a single section with 2-4 CODE_REF
3. **Quality metric gap**: `coverage` in `quality_report.py` only checks substring presence, not content depth
4. **Missing sanitize**: `compose_domain_agents_node` never calls `_sanitize_pages()` / Mermaid repair
5. **Explore sampling**: `page_agent.py` caps tool results at 5 items per call

## Objective

- Domain overview pages should describe **every core business module's logic** organized by
  business scenarios, with detailed treatment for entry points (Handler/Controller/Consumer)
  and core Services
- All generated pages should pass through Mermaid validation + LLM repair
- Generation time increase should be controllable via environment variables

## Design

### 1. Prompt Structure Reorganization (`wiki/agent_prompts.py`)

#### 1.1 AGENT_CORE_CONSTRAINTS

**Before:**
```
- 每篇文档应包含 2-4 个代码引用。
```

**After:**
```
- 每个核心业务模块（入口 Handler/Controller/Consumer、核心 Service）至少包含 1 个代码引用。
- 辅助/配置模块可不包含代码引用。
```

#### 1.2 AGENT_WRITE_SYSTEM Output Structure

**Before:**
```
1. ## 概述
2. ## 核心业务流程
3. ## 关键实现 (2-4 CODE_REF)
4. ## 依赖关系
```

**After:**
```
1. ## 概述
   - 域的整体业务职责和价值
   - 所有模块及其角色分工（以表格形式）

2. ## 核心业务流程
   - 按业务场景分组（如「送礼流程」「收礼流程」「收益结算」）
   - 每个场景包含 Mermaid sequenceDiagram + 文字描述
   - 场景中涉及的入口模块和核心 Service 必须详细说明其业务逻辑

3. ## 模块详解
   - 为域内每个核心业务模块生成 ### 子章节：
     ### ModuleName
     - 业务职责（2-3句）
     - 核心方法及其逻辑
     - <!-- CODE_REF: key_method -->
   - 入口模块和 Service 必须详细，辅助模块可简要描述职责

4. ## 依赖关系
   - 基于探索结果的跨域依赖绘制 Mermaid flowchart
   - 描述模块间依赖和与外部系统的关系
```

#### 1.3 AGENT_GENERATE_SYSTEM

Synchronize the same output structure changes to the single-pass mode prompt.

### 2. Quality Metric Enhancement (`wiki/quality_report.py`)

#### 2.1 New `implementation_depth` Metric

Add a new metric that checks whether each module has a corresponding `### SubHeading`
or `CODE_REF` in the generated content:

```python
def _calc_implementation_depth(content: str, module_names: list[str]) -> float:
    """Fraction of modules that have a ### heading or CODE_REF."""
    if not module_names:
        return 1.0
    h3_headings = set(re.findall(r"^### (.+)", content, re.MULTILINE))
    code_refs = set(re.findall(r"<!-- CODE_REF:\s*(\S+)", content))
    detailed = 0
    for m in module_names:
        short = m.rsplit(".", 1)[-1] if "." in m else m
        if any(short.lower() in h.lower() for h in h3_headings):
            detailed += 1
        elif any(short.lower() in r.lower() for r in code_refs):
            detailed += 1
    return detailed / len(module_names)
```

Add `implementation_depth: float` to `QualityReport` dataclass.

### 3. Quality Exit Conditions (`wiki/domain_doc_agent.py`)

#### 3.1 Updated Exit Conditions

| Condition | Before | After |
|-----------|--------|-------|
| Perfect exit | coverage ≥ 0.95, citation ≥ 0.5, gaps = 0 | + **depth ≥ 0.6** |
| Acceptable exit (iter ≥ 2) | coverage ≥ 0.9, citation ≥ 0.3 | + **depth ≥ 0.4** |
| Max iteration | iter ≥ 3 | iter ≥ **4** |

#### 3.2 Timeout Adjustments

| Parameter | Before | After | Controllable |
|-----------|--------|-------|-------------|
| WRITE_TIMEOUT_SEC | 120 | **180** | env var |
| EXPLORE_TIMEOUT_SEC | 240 | 240 (unchanged) | env var |
| DOMAIN_AGENT_TIMEOUT_SEC | 600 | **900** | env var |

### 4. Explore Sampling Enhancement (`wiki/page_agent.py`)

#### 4.1 Increased Sampling Limits

| Tool | Before | After |
|------|--------|-------|
| search_entities results | 5 | **8** |
| query_module_detail methods | 5 | **8** |

`MAX_TOTAL_CHARS` stays at 200,000 (already sufficient).

### 5. Domain Compose Mermaid Fix (`wiki/nodes/domain_compose.py`)

#### 5.1 Add Sanitize Step

After collecting all domain pages in `compose_domain_agents_node`, call the sanitize
pipeline to validate and repair Mermaid diagrams:

```python
# After all domain agent results are collected
from wiki.source_ref_validator import sanitize_wiki_content, repair_broken_mermaid_blocks

for page in pages:
    raw = page.get("content", "")
    page["content"] = sanitize_wiki_content(raw, known_entities)
    if llm is not None:
        page["content"] = await repair_broken_mermaid_blocks(page["content"], llm)
```

This ensures domain overview pages go through the same Mermaid validation/repair
pipeline as leaf module pages.

## Implementation Checklist

- [ ] 1. Modify `wiki/agent_prompts.py`: AGENT_CORE_CONSTRAINTS, AGENT_WRITE_SYSTEM, AGENT_GENERATE_SYSTEM
- [ ] 2. Modify `wiki/quality_report.py`: add `implementation_depth` metric
- [ ] 3. Modify `wiki/domain_doc_agent.py`: quality exit conditions + timeout defaults
- [ ] 4. Modify `wiki/page_agent.py`: sampling limits 5→8
- [ ] 5. Modify `wiki/nodes/domain_compose.py`: add sanitize + Mermaid repair
- [ ] 6. Deploy and test with a single domain regeneration
- [ ] 7. If successful, trigger full wiki rebuild

## Risk Assessment

- **Generation time**: ~50-100% increase per domain (controlled via env vars)
- **Token cost**: Proportional to content increase
- **Backward compat**: _maybe_split auto-splits large pages, no UI changes needed
- **Rollback**: All timeouts/limits are env-var controllable
