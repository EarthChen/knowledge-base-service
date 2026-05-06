# 统一 Wiki 企业级知识库实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Wiki 从两种风格并存、内容浅薄、缺少代码关联的状态，升级为单一业务主题树 + 深度代码关联 + 智能搜索的企业级知识库。

**Architecture:** 双模板体系（域概览模板 A + 主题详情模板 B）共享统一 system prompt 和 JSON 输出格式。新增 `ContentContextBuilder` 统一上下文层；重构 `DomainOverviewComposer` 为所有 overview 页面的唯一生成者（模板 A），增强 `TopicPageComposer` 生成详情页（模板 B）并将 overview 委托给前者；新增 `DomainStabilizer` 保证增量生成时域名称稳定；新增 `ProgressiveComposer` 解决大域 prompt 超长问题；后端 API 扩展实体关联和语义搜索；前端整合为单一主题树导航 + EntityCardsPanel。

**Tech Stack:** Python / FastAPI / LangGraph / FalkorDB / Tree-sitter / React 19 / Vite / TanStack Query

**Spec:** `docs/superpowers/specs/2026-05-06-unified-wiki-enterprise-kb-design.md`

---

## Phase 1: Indexer 方法签名增强 (U11)

### Task 1: 检查并增强 Java 方法签名提取

**Files:**
- Modify: `indexer/languages/java_language.py`
- Test: `tests/indexer/test_java_signature.py`

- [ ] **Step 1: Write failing test — Java 方法签名包含参数类型和返回值**

```python
# tests/indexer/test_java_signature.py
import pytest

def test_java_method_signature_includes_types():
    """Java parser should extract full method signatures with parameter types and return type."""
    from indexer.languages.java_language import JavaLanguageAdapter

    java_code = '''
    public class UserService {
        public UserDTO createUser(String name, int age, List<String> roles) {
            return new UserDTO(name, age, roles);
        }

        private void validateAge(int age) {
            if (age < 0) throw new IllegalArgumentException("invalid age");
        }
    }
    '''

    adapter = JavaLanguageAdapter()
    result = adapter.parse(java_code, "UserService.java")

    methods = [n for n in result if n.get("type") == "function" or n.get("label") == "Function"]
    create_user = next((m for m in methods if "createUser" in str(m.get("name", ""))), None)

    assert create_user is not None, "createUser method should be extracted"
    sig = create_user.get("properties", {}).get("signature", "")
    assert "String" in sig, f"Signature should include parameter types, got: {sig}"
    assert "UserDTO" in sig or "return" in sig.lower(), f"Signature should include return type, got: {sig}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/indexer/test_java_signature.py -v`
Expected: FAIL or SKIP if signature field is incomplete

- [ ] **Step 3: Enhance Java adapter signature extraction**

Read `indexer/languages/java_language.py`, find the method extraction logic. Ensure that for each method node, the `signature` property includes:
- Return type (from `type` child node)
- Method name
- Parameter list with types (from `formal_parameters` child node)

Format: `ReturnType methodName(ParamType1 param1, ParamType2 param2)`

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/indexer/test_java_signature.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add indexer/languages/java_language.py tests/indexer/test_java_signature.py
git commit -m "feat(indexer): enhance Java method signature extraction with parameter types and return type"
```

---

### Task 2: 检查并增强 Python 方法签名提取

**Files:**
- Modify: `indexer/languages/python_language.py`
- Test: `tests/indexer/test_python_signature.py`

- [ ] **Step 1: Write failing test — Python 方法签名包含 type hints**

```python
# tests/indexer/test_python_signature.py
import pytest

def test_python_method_signature_includes_type_hints():
    """Python parser should extract full method signatures with type hints."""
    from indexer.languages.python_language import PythonLanguageAdapter

    python_code = '''
class UserService:
    def create_user(self, name: str, age: int, roles: list[str]) -> UserDTO:
        return UserDTO(name=name, age=age, roles=roles)

    def validate_age(self, age: int) -> None:
        if age < 0:
            raise ValueError("invalid age")
    '''

    adapter = PythonLanguageAdapter()
    result = adapter.parse(python_code, "user_service.py")

    methods = [n for n in result if n.get("type") == "function" or n.get("label") == "Function"]
    create_user = next((m for m in methods if "create_user" in str(m.get("name", ""))), None)

    assert create_user is not None, "create_user method should be extracted"
    sig = create_user.get("properties", {}).get("signature", "")
    assert "str" in sig, f"Signature should include type hints, got: {sig}"
    assert "UserDTO" in sig or "-> " in sig, f"Signature should include return type hint, got: {sig}"
```

- [ ] **Step 2: Run test to verify current state**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/indexer/test_python_signature.py -v`

- [ ] **Step 3: Enhance Python adapter to extract type hints**

Read `indexer/languages/python_language.py`, enhance method extraction to include:
- Parameter type annotations (from `type` child of `typed_parameter`)
- Return type annotation (from `return_type` child of `function_definition`)

Format: `def method_name(param1: Type1, param2: Type2) -> ReturnType`

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/indexer/test_python_signature.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add indexer/languages/python_language.py tests/indexer/test_python_signature.py
git commit -m "feat(indexer): enhance Python method signature extraction with type hints"
```

---

## Phase 2: ContentContextBuilder + 统一 Prompt 模板 (U1 + U2)

### Task 3: 实现 ContentContextBuilder 核心数据模型和构建逻辑

**Files:**
- Create: `wiki/content_context_builder.py`
- Test: `tests/wiki/test_content_context_builder.py`

- [ ] **Step 1: Write failing test — CCB 构建基础上下文**

```python
# tests/wiki/test_content_context_builder.py
import pytest
from unittest.mock import AsyncMock, MagicMock

@pytest.mark.asyncio
async def test_ccb_builds_enriched_context():
    """ContentContextBuilder should return EnrichedDomainContext with populated fields."""
    from wiki.content_context_builder import ContentContextBuilder, EnrichedDomainContext

    mock_graph = AsyncMock()
    mock_graph.execute_query = AsyncMock(return_value=MagicMock(data=[
        {"name": "handleSend", "signature": "void handleSend(Request req)", "file": "MeetingSendBH.java", "start_line": 45, "docstring": "Send meeting signal"},
    ]))

    mock_wiki = AsyncMock()

    ccb = ContentContextBuilder(mock_graph, mock_wiki)
    module_index = {
        "MeetingSendBusinessHandler": [{"uid": "Module::MeetingSendBH:0", "properties": {"name": "MeetingSendBusinessHandler", "business_summary": "Handles meeting send", "file": "MeetingSendBH.java"}, "_repo": "ultron-composite"}],
    }
    entity_roles = {"Module::MeetingSendBH:0": "has_business_logic"}
    domain_mapping = {"meeting": [("ultron-composite", "MeetingSendBusinessHandler")]}

    context = await ccb.build_context(
        domain_name="meeting",
        module_names=["MeetingSendBusinessHandler"],
        module_index=module_index,
        entity_roles=entity_roles,
        domain_mapping=domain_mapping,
    )

    assert isinstance(context, EnrichedDomainContext)
    assert context.domain_name == "meeting"
    assert len(context.biz_entities) >= 1
    assert context.biz_entities[0].name == "MeetingSendBusinessHandler"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_content_context_builder.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement ContentContextBuilder with data models**

Create `wiki/content_context_builder.py` with:
- `MethodDetail`, `CallChainStep`, `EntityDetail`, `EnrichedDomainContext` dataclasses
- `ContentContextBuilder` class with `build_context()` method
- Graph queries for method signatures, call chains, enums/constants, cross-domain deps
- Use `asyncio.gather` for parallel graph queries

Key implementation notes:
- Edge types: Use `CONTAINS` (not `HAS_METHOD`) based on existing schema
- Call chain query: `MATCH path = (a:Module)-[:CALLS*1..{depth}]->(b:Module) WHERE a.name IN $names`
- Method query: `MATCH (m:Module)-[:CONTAINS*1..3]->(f:Function) WHERE m.name IN $names`
- Cross-domain: `MATCH (a:Module)-[:CALLS]->(b:Module) WHERE a.name IN $domain_a AND b.name IN $domain_b`
- `EnrichedDomainContext` 包含 `existing_wiki_context: str` 字段
- `build_context()` 查询同域已有 wiki 页面的 executive_summary 作为生成参考
- 用于避免重复内容、保持域内页面一致性、增量生成时的风格延续

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_content_context_builder.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add wiki/content_context_builder.py tests/wiki/test_content_context_builder.py
git commit -m "feat: add ContentContextBuilder for unified wiki context assembly"
```

---

### Task 4: 实现统一 Prompt 模板 + System Prompt + 两种页面模板

**Files:**
- Create: `wiki/unified_prompt_templates.py`
- Test: `tests/wiki/test_unified_prompt_templates.py`

- [ ] **Step 1: Write failing test — section builders + prompt builders 输出正确**

```python
# tests/wiki/test_unified_prompt_templates.py
import pytest
from wiki.content_context_builder import EntityDetail, MethodDetail, CallChainStep, EnrichedDomainContext

def test_build_entity_section_includes_methods_and_repo():
    from wiki.unified_prompt_templates import build_entity_section

    entities = [
        EntityDetail(
            uid="uid1", name="MeetingSendBH", repository="ultron-composite",
            file_path="MeetingSendBH.java", entity_type="Module",
            business_summary="Handles meeting send",
            methods=[MethodDetail(name="handleSend", signature="void handleSend(Request req)", file_path="MeetingSendBH.java", start_line=45, repository="ultron-composite")],
            call_chains=[],
        ),
    ]

    result = build_entity_section(entities)
    assert "MeetingSendBH" in result
    assert "ultron-composite" in result
    assert "handleSend" in result
    assert "void handleSend(Request req)" in result

def test_build_call_chain_section():
    from wiki.unified_prompt_templates import build_call_chain_section

    intra = [CallChainStep(caller="ServiceA", callee="ServiceB", caller_method="doX", callee_method="handleX", relationship="CALLS")]
    cross = [CallChainStep(caller="ServiceB", callee="ExternalSvc", caller_method="callExt", callee_method="process", relationship="CALLS")]

    result = build_call_chain_section(intra, cross)
    assert "ServiceA" in result
    assert "ServiceB" in result
    assert "ExternalSvc" in result

def test_build_domain_overview_prompt_has_required_sections():
    from wiki.unified_prompt_templates import build_domain_overview_prompt

    context = EnrichedDomainContext(
        domain_name="Meeting", parent_domain="root",
        biz_entities=[], data_models=[], intra_domain_calls=[], cross_domain_calls=[],
        key_snippets=[], enums_and_constants=[],
        sibling_domains=["Live"], dependent_domains=["User Management"], dependee_domains=[],
        sub_topics=[{"title": "Meeting Initiation", "description": "发起流程", "entity_count": 3}],
    )

    prompt = build_domain_overview_prompt(context)
    assert "业务概述" in prompt
    assert "架构全景图" in prompt
    assert "子主题导航" in prompt
    assert "关键入口" in prompt
    assert "跨域依赖" in prompt

def test_build_topic_detail_prompt_has_required_sections():
    from wiki.unified_prompt_templates import build_topic_detail_prompt

    context = EnrichedDomainContext(
        domain_name="Meeting Initiation", parent_domain="Meeting",
        biz_entities=[EntityDetail(
            uid="u1", name="MeetingSendBH", repository="ultron-composite",
            file_path="MeetingSendBH.java", entity_type="Module",
            business_summary="Send meeting signals",
            methods=[MethodDetail(name="handleSend", signature="void handleSend(Request req)",
                                  file_path="MeetingSendBH.java", start_line=45, repository="ultron-composite")],
            call_chains=[],
        )],
        data_models=[], intra_domain_calls=[], cross_domain_calls=[],
        key_snippets=[], enums_and_constants=[],
        sibling_domains=[], dependent_domains=[], dependee_domains=[],
        sub_topics=[],
    )

    prompt = build_topic_detail_prompt(context)
    assert "业务概述" in prompt
    assert "核心业务流程" in prompt
    assert "核心服务详解" in prompt
    assert "数据模型" in prompt
    assert "设计要点" in prompt

def test_unified_system_prompt_contains_constraints():
    from wiki.unified_prompt_templates import UNIFIED_WIKI_SYSTEM_PROMPT

    assert "禁止" in UNIFIED_WIKI_SYSTEM_PROMPT
    assert "Mermaid" in UNIFIED_WIKI_SYSTEM_PROMPT
    assert "JSON" in UNIFIED_WIKI_SYSTEM_PROMPT
    assert "source://" in UNIFIED_WIKI_SYSTEM_PROMPT
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_unified_prompt_templates.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement unified_prompt_templates.py**

Create `wiki/unified_prompt_templates.py` with:

1. **`UNIFIED_WIKI_SYSTEM_PROMPT`** — 统一 system prompt，包含写作规则、禁止条款、输出格式要求
2. **Section builder 函数**：
   - `build_entity_section(entities) -> str`
   - `build_call_chain_section(intra, cross) -> str`
   - `build_data_model_section(models) -> str`
   - `build_enum_constants_section(items) -> str`
   - `build_cross_domain_section(dependent, dependee, cross_calls) -> str`
3. **模板 A prompt builder**：`build_domain_overview_prompt(context: EnrichedDomainContext) -> str`
4. **模板 B prompt builder**：`build_topic_detail_prompt(context: EnrichedDomainContext) -> str`

每个函数的具体 prompt 内容详见 spec U2c 和 U2d。

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_unified_prompt_templates.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add wiki/unified_prompt_templates.py tests/wiki/test_unified_prompt_templates.py
git commit -m "feat: add unified prompt templates with dual page templates and system prompt"
```

---

## Phase 3: ProgressiveComposer + Composer 重构 + Pipeline 集成 (U12 + U3 + U4 + U5 + U6)

### Task 5: 实现 ProgressiveComposer

**Files:**
- Create: `wiki/progressive_composer.py`
- Test: `tests/wiki/test_progressive_composer.py`

- [ ] **Step 1: Write failing test — 小上下文使用单次调用**

```python
# tests/wiki/test_progressive_composer.py
import pytest
from unittest.mock import AsyncMock
from wiki.content_context_builder import EnrichedDomainContext, EntityDetail, MethodDetail

@pytest.mark.asyncio
async def test_small_context_uses_single_pass():
    """When context fits within budget, ProgressiveComposer uses single LLM call."""
    from wiki.progressive_composer import ProgressiveComposer

    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value='{"content": "# Meeting\\nContent here", "executive_summary": "Meeting overview"}')

    context = EnrichedDomainContext(
        domain_name="meeting", parent_domain="root",
        biz_entities=[EntityDetail(uid="u1", name="Svc", repository="r", file_path="f.java", entity_type="Module", business_summary="desc", methods=[], call_chains=[])],
        data_models=[], intra_domain_calls=[], cross_domain_calls=[],
        key_snippets=[], enums_and_constants=[],
        sibling_domains=[], dependent_domains=[], dependee_domains=[],
        sub_topics=[],
    )

    composer = ProgressiveComposer(threshold_tokens=6000)
    result = await composer.compose(context, mock_llm, token_budget=8000)

    assert mock_llm.generate.call_count == 1, "Should use single pass for small context"
    assert "Meeting" in result or "Content" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_progressive_composer.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement ProgressiveComposer**

Create `wiki/progressive_composer.py` with:
- Token estimation logic (`_estimate_tokens`)
- Single pass path for small contexts
- 3-round progressive path for large contexts:
  - Round 1: Core entities (entry_point + has_business_logic) → skeleton
  - Round 2: Supporting entities + call chains → enrichment (takes Round 1 output as prefix)
  - Round 3: Append structured data (data models, enums) as Markdown tables
- Use `unified_prompt_templates` builders for prompt construction

- [ ] **Step 4: Write test for large context progressive mode**

```python
@pytest.mark.asyncio
async def test_large_context_uses_progressive():
    """When context exceeds budget, ProgressiveComposer uses multiple LLM calls."""
    from wiki.progressive_composer import ProgressiveComposer

    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value='{"content": "# Page\\nContent", "executive_summary": "Summary"}')

    entities = [
        EntityDetail(uid=f"u{i}", name=f"Svc{i}", repository="r", file_path=f"f{i}.java",
                     entity_type="Module", business_summary=f"Description for service {i} " * 50,
                     methods=[MethodDetail(name=f"m{j}", signature=f"void m{j}(Param p)", file_path=f"f{i}.java", start_line=j*10, repository="r") for j in range(20)],
                     call_chains=[])
        for i in range(30)
    ]

    context = EnrichedDomainContext(
        domain_name="large-domain", parent_domain="root",
        biz_entities=entities, data_models=[{"name": f"DTO{i}", "fields": ["a", "b", "c"]} for i in range(20)],
        intra_domain_calls=[], cross_domain_calls=[],
        key_snippets=[], enums_and_constants=[],
        sibling_domains=[], dependent_domains=[], dependee_domains=[],
        sub_topics=[],
    )

    composer = ProgressiveComposer(threshold_tokens=2000)
    result = await composer.compose(context, mock_llm, token_budget=8000)

    assert mock_llm.generate.call_count >= 2, "Should use multiple passes for large context"
```

- [ ] **Step 5: Run tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_progressive_composer.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add wiki/progressive_composer.py tests/wiki/test_progressive_composer.py
git commit -m "feat: add ProgressiveComposer for multi-round LLM content generation"
```

---

### Task 6: 重构 DomainOverviewComposer (U3)

**Files:**
- Modify: `wiki/domain_overview_composer.py`
- Test: `tests/wiki/test_domain_overview_composer.py`

- [ ] **Step 1: Write failing test — compose_from_context 输出 JSON 格式并包含模板 A 结构**

```python
# tests/wiki/test_domain_overview_composer.py
import pytest
from unittest.mock import AsyncMock
from wiki.content_context_builder import EnrichedDomainContext, EntityDetail

@pytest.mark.asyncio
async def test_compose_from_context_uses_unified_system_prompt():
    """compose_from_context should use UNIFIED_WIKI_SYSTEM_PROMPT and JSON output."""
    from wiki.domain_overview_composer import DomainOverviewComposer

    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value=(
        '{"executive_summary": "会议管理域概述", "content": '
        '"## 业务概述\\n会议管理域负责...\\n\\n'
        '## 架构全景图\\n```mermaid\\nflowchart TD\\nA-->B\\n```\\n\\n'
        '## 子主题导航\\n- 会议发起(3个实体)\\n\\n'
        '## 关键入口\\n- MeetingSendBH\\n\\n'
        '## 跨域依赖与交互\\n- 依赖用户管理域"}'
    ))

    context = EnrichedDomainContext(
        domain_name="meeting", parent_domain="root",
        biz_entities=[EntityDetail(uid="u1", name="MeetingSendBH", repository="ultron-composite", file_path="f.java", entity_type="Module", business_summary="Send meetings", methods=[], call_chains=[])],
        data_models=[], intra_domain_calls=[], cross_domain_calls=[],
        key_snippets=[], enums_and_constants=[],
        sibling_domains=["live"], dependent_domains=["user-management"], dependee_domains=[],
        sub_topics=[{"title": "Meeting Initiation", "description": "发起流程", "entity_count": 3}],
    )

    composer = DomainOverviewComposer(llm=mock_llm)
    page = await composer.compose_from_context(context, language="zh")

    assert "业务概述" in page.content
    assert page.page_type == PageType.DOMAIN_OVERVIEW
    assert page.metadata.executive_summary == "会议管理域概述"

    # Verify UNIFIED_WIKI_SYSTEM_PROMPT was used (check system arg)
    call_args = mock_llm.generate.call_args
    from wiki.unified_prompt_templates import UNIFIED_WIKI_SYSTEM_PROMPT
    assert call_args.kwargs.get("system") == UNIFIED_WIKI_SYSTEM_PROMPT or \
           call_args[1] == UNIFIED_WIKI_SYSTEM_PROMPT

@pytest.mark.asyncio
async def test_compose_from_context_uses_domain_overview_prompt():
    """Prompt should follow Template A structure (domain overview)."""
    from wiki.domain_overview_composer import DomainOverviewComposer
    from wiki.unified_prompt_templates import build_domain_overview_prompt

    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value='{"executive_summary": "...", "content": "## 业务概述\\n..."}')

    context = EnrichedDomainContext(
        domain_name="meeting", parent_domain="root",
        biz_entities=[], data_models=[], intra_domain_calls=[], cross_domain_calls=[],
        key_snippets=[], enums_and_constants=[],
        sibling_domains=[], dependent_domains=[], dependee_domains=[],
        sub_topics=[],
    )

    composer = DomainOverviewComposer(llm=mock_llm)
    await composer.compose_from_context(context)

    # Verify build_domain_overview_prompt was used
    call_args = mock_llm.generate.call_args
    prompt_text = call_args[0][0] if call_args[0] else call_args.kwargs.get("prompt", "")
    assert "架构全景图" in prompt_text or "子主题导航" in prompt_text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_domain_overview_composer.py -v`
Expected: FAIL — compose_from_context not defined

- [ ] **Step 3: Add compose_from_context to DomainOverviewComposer**

In `wiki/domain_overview_composer.py`, add the new method that:
1. Accepts `EnrichedDomainContext` and `language`
2. Uses `UNIFIED_WIKI_SYSTEM_PROMPT` (replacing `_llm_system()`)
3. Uses `build_domain_overview_prompt(context)` (replacing `_llm_prompt()`)
4. Parses JSON response with `_parse_wiki_json_response()` (matching TopicPageComposer)
5. Falls back to structural markdown if LLM fails
6. Returns `WikiPage` with `PageType.DOMAIN_OVERVIEW` and `executive_summary`

Keep original `compose()` method as compatibility wrapper.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_domain_overview_composer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add wiki/domain_overview_composer.py tests/wiki/test_domain_overview_composer.py
git commit -m "feat: add compose_from_context to DomainOverviewComposer with unified system prompt and JSON output"
```

---

### Task 7: 增强 TopicPageComposer + Overview 委托 (U4)

**Files:**
- Modify: `wiki/topic_page_composer.py`
- Test: `tests/wiki/test_topic_page_composer_enhanced.py`

- [ ] **Step 1: Write failing test — compose_leaf_domain_from_context 使用模板 B**

```python
# tests/wiki/test_topic_page_composer_enhanced.py
import pytest
from unittest.mock import AsyncMock, patch
from wiki.content_context_builder import EnrichedDomainContext, EntityDetail, MethodDetail, CallChainStep

@pytest.mark.asyncio
async def test_compose_leaf_domain_from_context_uses_topic_template():
    """TopicPageComposer should use UNIFIED_WIKI_SYSTEM_PROMPT + build_topic_detail_prompt."""
    from wiki.topic_page_composer import TopicPageComposer
    from wiki.unified_prompt_templates import UNIFIED_WIKI_SYSTEM_PROMPT

    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value='{"content": "## 业务概述\\nContent", "executive_summary": "Meeting init summary"}')

    context = EnrichedDomainContext(
        domain_name="Meeting Initiation", parent_domain="meeting",
        biz_entities=[EntityDetail(
            uid="u1", name="MeetingSendBH", repository="ultron-composite",
            file_path="MeetingSendBH.java", entity_type="Module",
            business_summary="Send meeting signals",
            methods=[MethodDetail(name="handleSend", signature="void handleSend(Request req)", file_path="MeetingSendBH.java", start_line=45, repository="ultron-composite")],
            call_chains=[CallChainStep(caller="MeetingSendBH", callee="MeetingService", caller_method="handleSend", callee_method="createMeeting", relationship="CALLS")],
        )],
        data_models=[], intra_domain_calls=[], cross_domain_calls=[],
        key_snippets=[], enums_and_constants=[],
        sibling_domains=[], dependent_domains=[], dependee_domains=[],
        sub_topics=[],
    )

    composer = TopicPageComposer(mock_llm, token_budget=8000)
    pages = await composer.compose_leaf_domain_from_context(context)

    assert len(pages) >= 1
    assert pages[0]["title"] == "Meeting Initiation"
    # Verify unified system prompt was used
    call_args = mock_llm.generate.call_args
    assert UNIFIED_WIKI_SYSTEM_PROMPT in str(call_args)

@pytest.mark.asyncio
async def test_medium_complexity_delegates_overview_to_domain_overview_composer():
    """When MEDIUM/HIGH complexity, overview page should be generated by DomainOverviewComposer."""
    from wiki.topic_page_composer import TopicPageComposer
    from wiki.domain_overview_composer import DomainOverviewComposer
    from wiki.models import WikiPage, PageType, WikiPageMetadata

    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value='{"content": "## 业务概述\\nSub page", "executive_summary": "..."}')

    mock_overview_composer = AsyncMock(spec=DomainOverviewComposer)
    mock_overview_page = WikiPage(
        path="/meeting/_overview", title="Meeting — 概述",
        page_type=PageType.DOMAIN_OVERVIEW, content="## 业务概述\nOverview content",
        diagrams=[], source_locations=[],
        metadata=WikiPageMetadata(node_count=1, edge_count=0),
    )
    mock_overview_composer.compose_from_context = AsyncMock(return_value=mock_overview_page)

    entities = [
        EntityDetail(uid=f"u{i}", name=f"Svc{i}", repository="r", file_path=f"f{i}.java",
                     entity_type="Module", business_summary=f"Service {i}",
                     methods=[], call_chains=[])
        for i in range(8)  # enough to trigger MEDIUM
    ]

    context = EnrichedDomainContext(
        domain_name="Meeting", parent_domain="root",
        biz_entities=entities, data_models=[], intra_domain_calls=[], cross_domain_calls=[],
        key_snippets=[], enums_and_constants=[],
        sibling_domains=[], dependent_domains=[], dependee_domains=[],
        sub_topics=[],
    )

    composer = TopicPageComposer(mock_llm, token_budget=8000)
    pages = await composer.compose_leaf_domain_from_context(
        context, overview_composer=mock_overview_composer
    )

    # Overview page should come from DomainOverviewComposer
    mock_overview_composer.compose_from_context.assert_called_once()
    overview_pages = [p for p in pages if p.get("page_type") == "domain_overview"]
    assert len(overview_pages) >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_topic_page_composer_enhanced.py -v`
Expected: FAIL — compose_leaf_domain_from_context not defined

- [ ] **Step 3: Add compose_leaf_domain_from_context method**

In `wiki/topic_page_composer.py`, add new method that:
1. Accepts `EnrichedDomainContext` and optional `overview_composer: DomainOverviewComposer`
2. Uses `UNIFIED_WIKI_SYSTEM_PROMPT` + `build_topic_detail_prompt(context)` for TOPIC pages
3. For MEDIUM/HIGH complexity: delegates overview to `overview_composer.compose_from_context()` (模板 A)
4. Integrates `ProgressiveComposer` for large contexts
5. Sub-pages use `build_topic_detail_prompt()` with sub-context (模板 B)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_topic_page_composer_enhanced.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add wiki/topic_page_composer.py tests/wiki/test_topic_page_composer_enhanced.py
git commit -m "feat: add compose_leaf_domain_from_context with overview delegation and unified prompts"
```

---

### Task 8: Pipeline 集成 CCB (U5 + U6)

**Files:**
- Modify: `wiki/pipeline_nodes.py`
- Modify: `wiki/tree_linker.py`
- Test: `tests/wiki/test_pipeline_ccb_integration.py`

- [ ] **Step 1: Write failing test — compose_leaf_pages_node 使用 CCB**

```python
# tests/wiki/test_pipeline_ccb_integration.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

@pytest.mark.asyncio
async def test_compose_leaf_pages_uses_ccb_when_available():
    """When graph_store is available in config, compose_leaf_pages_node should use CCB."""
    from wiki.pipeline_nodes import compose_leaf_pages_node

    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value='{"content": "# Test\\nContent", "executive_summary": "Summary"}')

    mock_graph = AsyncMock()
    mock_graph.execute_query = AsyncMock(return_value=MagicMock(data=[]))

    state = {
        "domain_tree": [{"name": "test_domain", "modules": ["TestService"], "children": []}],
        "topic_structure": None,
        "entity_roles": {"Module::TestService:0": "has_business_logic"},
        "modules": {"repo1": [{"uid": "Module::TestService:0", "properties": {"name": "TestService", "business_summary": "Test"}}]},
        "domain_mapping": {"test_domain": [("repo1", "TestService")]},
    }
    config = {"configurable": {"llm": mock_llm, "graph_store": mock_graph, "wiki_store": AsyncMock()}}

    with patch("wiki.pipeline_nodes.ContentContextBuilder") as MockCCB:
        mock_ccb_instance = AsyncMock()
        mock_ccb_instance.build_context = AsyncMock(return_value=MagicMock(
            domain_name="test_domain", biz_entities=[], data_models=[],
            intra_domain_calls=[], cross_domain_calls=[],
            key_snippets=[], enums_and_constants=[],
            sibling_domains=[], dependent_domains=[], dependee_domains=[],
            sub_topics=[],
        ))
        MockCCB.return_value = mock_ccb_instance

        result = await compose_leaf_pages_node(state, config)

    MockCCB.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_pipeline_ccb_integration.py -v`
Expected: FAIL — CCB not imported or used

- [ ] **Step 3: Modify compose_leaf_pages_node to use CCB**

In `wiki/pipeline_nodes.py`:
1. Add import: `from wiki.content_context_builder import ContentContextBuilder`
2. In `compose_leaf_pages_node()`, extract `graph_store` and `wiki_store` from config
3. Pass them to `_compose_single_leaf_domain()`
4. In `_compose_single_leaf_domain()`, if `graph_store` and `wiki_store` available, create CCB and build context
5. Pass `EnrichedDomainContext` to composer's `compose_leaf_domain_from_context()`

- [ ] **Step 4: Modify tree_linker.py to use CCB for domain overviews**

In `wiki/tree_linker.py`, in `link_pages_to_nested_tree()`:
1. Before calling `DomainOverviewComposer.compose()`, create CCB and build context
2. Call `DomainOverviewComposer.compose_from_context()` instead
3. Keep fallback to original `compose()` if graph_store unavailable

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_pipeline_ccb_integration.py -v`
Expected: PASS

- [ ] **Step 6: Run full wiki test suite**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/ -x -q --timeout=120 2>&1 | tail -20`
Expected: All tests pass

- [ ] **Step 7: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add wiki/pipeline_nodes.py wiki/tree_linker.py tests/wiki/test_pipeline_ccb_integration.py
git commit -m "feat: integrate ContentContextBuilder into pipeline and tree_linker"
```

---

## Phase 4: 域名称稳定器 (U9)

### Task 9: 实现 DomainStabilizer

**Files:**
- Create: `wiki/domain_stabilizer.py`
- Modify: `wiki/pipeline_nodes.py`
- Modify: `wiki/pipeline_graph.py`
- Test: `tests/wiki/test_domain_stabilizer.py`

- [ ] **Step 1: Write failing test — 语义相似域名被锚定**

```python
# tests/wiki/test_domain_stabilizer.py
import pytest
import numpy as np
from unittest.mock import AsyncMock

@pytest.mark.asyncio
async def test_stabilizer_anchors_similar_domain_names():
    """DomainStabilizer should map 'meeting-management' to existing 'meeting' domain."""
    from wiki.domain_stabilizer import DomainStabilizer

    async def mock_embed(texts):
        embeddings = {
            "meeting": np.array([1.0, 0.0, 0.0]),
            "meeting-management": np.array([0.98, 0.1, 0.0]),
            "live-streaming": np.array([0.0, 1.0, 0.0]),
            "live": np.array([0.0, 0.95, 0.1]),
            "payment": np.array([0.0, 0.0, 1.0]),
        }
        return [embeddings.get(t, np.array([0.5, 0.5, 0.5])) for t in texts]

    stabilizer = DomainStabilizer(mock_embed)
    new_mapping = {
        "meeting-management": [("repo1", "MeetingSvc")],
        "live-streaming": [("repo1", "LiveSvc")],
        "payment": [("repo1", "PaySvc")],
    }
    existing = ["meeting", "live"]

    result = await stabilizer.stabilize(new_mapping, existing, similarity_threshold=0.85)

    assert "meeting" in result, "meeting-management should be mapped to existing 'meeting'"
    assert "live" in result, "live-streaming should be mapped to existing 'live'"
    assert "payment" in result, "payment should remain as-is (no similar existing domain)"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_domain_stabilizer.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement DomainStabilizer**

Create `wiki/domain_stabilizer.py` with:
- `DomainStabilizer` class accepting embedding function
- `stabilize()` method: compute cosine similarity matrix, match above threshold, replace names
- `cosine_similarity()` helper

- [ ] **Step 4: Add stabilize_domains_node to pipeline**

In `wiki/pipeline_nodes.py`, add `stabilize_domains_node()` function.
In `wiki/pipeline_graph.py`, wire between `classify_domains` and `decompose_hierarchy`.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_domain_stabilizer.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add wiki/domain_stabilizer.py wiki/pipeline_nodes.py wiki/pipeline_graph.py tests/wiki/test_domain_stabilizer.py
git commit -m "feat: add DomainStabilizer for consistent domain naming across incremental runs"
```

---

## Phase 5: 实体关联 API (U7)

### Task 10: 后端 API 扩展 — related_entities

**Files:**
- Create: `api/models/wiki_entity.py`
- Modify: `store/wiki_store.py` (或 `store/wiki_tree_store.py`)
- Modify: `api/routes/wiki_routes.py`
- Test: `tests/api/test_wiki_entity_api.py`

- [ ] **Step 1: Create RelatedEntity response model**

Create `api/models/wiki_entity.py` with `RelatedEntity` and extended response model.

- [ ] **Step 2: Add get_related_entities to wiki store**

In the appropriate wiki store file, add graph query method for SOURCE_ENTITY edges.

- [ ] **Step 3: Extend wiki page API route**

In `api/routes/wiki_routes.py`, extend the page detail endpoint to include `related_entities`.

- [ ] **Step 4: Write and run API test**

- [ ] **Step 5: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add api/models/wiki_entity.py store/wiki_store.py api/routes/wiki_routes.py tests/api/test_wiki_entity_api.py
git commit -m "feat: extend wiki page API with related_entities for code navigation"
```

---

## Phase 6: 语义搜索 (U8)

### Task 11: 实现 SemanticWikiQuery

**Files:**
- Create: `query/semantic_wiki_query.py`
- Modify: `api/routes/wiki_routes.py`
- Test: `tests/query/test_semantic_wiki_query.py`

- [ ] **Step 1: Implement SemanticWikiQuery class**

- [ ] **Step 2: Add API route**

- [ ] **Step 3: Write and run tests**

- [ ] **Step 4: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add query/semantic_wiki_query.py api/routes/wiki_routes.py tests/query/test_semantic_wiki_query.py
git commit -m "feat: add semantic wiki search combining wiki pages, code entities, and call chains"
```

---

## Phase 7: 前端整合 (U10)

### Task 12: EntityCardsPanel 组件

**Files:**
- Create: `dashboard/src/components/wiki/EntityCardsPanel.tsx`
- Modify: `dashboard/src/components/wiki/WikiPageDetail.tsx` (或等效页面组件)
- Modify: `dashboard/src/hooks/useWikiPage.ts`

- [ ] **Step 1: Extend useWikiPage hook to fetch related_entities**

- [ ] **Step 2: Create EntityCardsPanel component**

- [ ] **Step 3: Integrate into WikiPageDetail**

- [ ] **Step 4: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add dashboard/src/components/wiki/EntityCardsPanel.tsx dashboard/src/components/wiki/WikiPageDetail.tsx dashboard/src/hooks/useWikiPage.ts
git commit -m "feat: add EntityCardsPanel to wiki pages for code entity navigation"
```

---

### Task 13: 统一主题树导航

**Files:**
- Modify: `dashboard/src/components/wiki/WikiTopicTreeNav.tsx` (或等效导航组件)

- [ ] **Step 1: Default-hide code structure tab**

- [ ] **Step 2: Ensure topic tree is the only default navigation**

- [ ] **Step 3: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add dashboard/src/components/wiki/WikiTopicTreeNav.tsx
git commit -m "feat: default to topic tree navigation, hide code structure tab"
```

---

### Task 14: 搜索增强前端

**Files:**
- Create: `dashboard/src/components/wiki/SemanticSearchPanel.tsx`

- [ ] **Step 1: Create SemanticSearchPanel with wiki/entity/chain tabs**

- [ ] **Step 2: Integrate into search page**

- [ ] **Step 3: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add dashboard/src/components/wiki/SemanticSearchPanel.tsx
git commit -m "feat: add SemanticSearchPanel with wiki + code entity + call chain results"
```

---

## Phase 8: 部署验证

### Task 15: 部署到开发机并验证

**Files:**
- `deploy-dev.sh`

- [ ] **Step 1: 部署到开发机**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && bash deploy-dev.sh`

- [ ] **Step 2: 重新触发 wiki 生成**

通过 API 触发业务级 wiki 重新生成（全量模式），观察日志确认:
- CCB 正常构建上下文
- DomainStabilizer 正常工作（增量场景）
- ProgressiveComposer 在大域上使用多次调用
- 所有页面生成成功

- [ ] **Step 3: 验收检查**

访问 http://172.18.228.71:8100/ 验证:
- [ ] DOMAIN_OVERVIEW 遵循模板 A（5 sections：业务概述/架构全景图/子主题导航/关键入口/跨域依赖）
- [ ] TOPIC 遵循模板 B（5 sections：业务概述/核心业务流程/核心服务详解/数据模型/设计要点）
- [ ] TopicPageComposer 拆分时的 overview 页面也使用模板 A
- [ ] domain overview 页面内容量 ≥ 1200 字
- [ ] 每个 wiki 页面有实体卡片区域
- [ ] 实体卡片点击可查看详情
- [ ] 主题树为默认导航入口
- [ ] 搜索 "会议发起流程" 返回 wiki + 代码实体 + 调用链
