# Sprint 1: LangGraph 基础接入 + 可观测性 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce LangGraph as the pipeline orchestration layer for Wiki generation, with a ChatModel adapter, pipeline state definition, StateGraph skeleton, node wrappers, observability via callbacks, and LangChain ChatPromptTemplate-based prompt management.

**Architecture:** The existing business components (BusinessDomainPlanner, WikiComposer, etc.) remain untouched. A new LangGraph StateGraph orchestrates them as nodes. LLMPortBridge is preserved as the ai-gateway SDK; a thin `LLMPortChatModel` adapter bridges it to LangChain's ChatModel interface. All prompts are centralized in `wiki/prompts.py` using `ChatPromptTemplate`.

**Tech Stack:** Python 3.12, LangGraph ≥0.2, langchain-core ≥0.3, pydantic ≥2.10, structlog

---

### Task 1: Add LangGraph Dependencies

**Files:**
- Modify: `pyproject.toml:7-29`
- Test: `tests/test_langgraph_import.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_langgraph_import.py
"""Verify LangGraph and langchain-core are importable."""


def test_langgraph_importable():
    from langgraph.graph import StateGraph
    assert StateGraph is not None


def test_langchain_core_importable():
    from langchain_core.language_models import BaseChatModel
    from langchain_core.prompts import ChatPromptTemplate
    assert BaseChatModel is not None
    assert ChatPromptTemplate is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/test_langgraph_import.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'langgraph'`

- [ ] **Step 3: Add dependencies to pyproject.toml**

In `pyproject.toml`, add to the `dependencies` list:

```toml
    "langgraph>=0.2.0",
    "langchain-core>=0.3.0",
```

Then install:

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv pip install -e ".[dev]"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/test_langgraph_import.py -v`
Expected: PASS — both imports succeed

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml tests/test_langgraph_import.py
git commit -m "feat: add langgraph and langchain-core dependencies"
```

---

### Task 2: LLMPortChatModel — LangChain Adapter

**Files:**
- Create: `wiki/langchain_adapter.py`
- Test: `tests/wiki/test_langchain_adapter.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/wiki/test_langchain_adapter.py
"""Tests for LLMPortChatModel adapter."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage


@pytest.fixture
def mock_bridge():
    bridge = MagicMock()
    bridge.complete = AsyncMock(return_value="Hello from LLM")
    return bridge


@pytest.mark.asyncio
async def test_agenerate_converts_messages(mock_bridge):
    from wiki.langchain_adapter import LLMPortChatModel

    model = LLMPortChatModel(bridge=mock_bridge)
    messages = [
        SystemMessage(content="You are helpful."),
        HumanMessage(content="Say hello"),
    ]
    result = await model.ainvoke(messages)

    assert isinstance(result, AIMessage)
    assert result.content == "Hello from LLM"

    mock_bridge.complete.assert_called_once()
    call_args = mock_bridge.complete.call_args
    lm_messages = call_args[0][0]
    assert lm_messages[0] == {"role": "system", "content": "You are helpful."}
    assert lm_messages[1] == {"role": "user", "content": "Say hello"}


@pytest.mark.asyncio
async def test_agenerate_passes_model_kwarg(mock_bridge):
    from wiki.langchain_adapter import LLMPortChatModel

    model = LLMPortChatModel(bridge=mock_bridge, model_name="qwen3")
    messages = [HumanMessage(content="test")]
    await model.ainvoke(messages, model="qwen3-fast")

    call_kwargs = mock_bridge.complete.call_args[1]
    assert call_kwargs.get("model") == "qwen3-fast"


def test_sync_generate_raises(mock_bridge):
    from wiki.langchain_adapter import LLMPortChatModel

    model = LLMPortChatModel(bridge=mock_bridge)
    with pytest.raises(NotImplementedError):
        model.invoke([HumanMessage(content="test")])


def test_llm_type(mock_bridge):
    from wiki.langchain_adapter import LLMPortChatModel

    model = LLMPortChatModel(bridge=mock_bridge)
    assert model._llm_type == "llm-port-bridge"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_langchain_adapter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'wiki.langchain_adapter'`

- [ ] **Step 3: Write minimal implementation**

```python
# wiki/langchain_adapter.py
"""LangChain ChatModel adapter for LLMPortBridge."""
from __future__ import annotations

from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun, AsyncCallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class LLMPortChatModel(BaseChatModel):
    """Wraps LLMPortBridge as a LangChain ChatModel.

    The bridge talks to our internal ai-gateway. This adapter lets us use
    LangGraph nodes, with_structured_output, OutputFixingParser, etc.
    """

    bridge: Any
    model_name: str = "default"

    @property
    def _llm_type(self) -> str:
        return "llm-port-bridge"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        raise NotImplementedError("Use async via ainvoke / _agenerate")

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        lm_messages = _convert_messages(messages)
        model = kwargs.get("model") or self.model_name
        result = await self.bridge.complete(lm_messages, model=model)
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=result))]
        )


def _convert_messages(messages: list[BaseMessage]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for m in messages:
        role = m.type
        if role == "human":
            role = "user"
        out.append({"role": role, "content": m.content})
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_langchain_adapter.py -v`
Expected: PASS — all 4 tests green

- [ ] **Step 5: Commit**

```bash
git add wiki/langchain_adapter.py tests/wiki/test_langchain_adapter.py
git commit -m "feat: add LLMPortChatModel adapter bridging LLMPortBridge to LangChain"
```

---

### Task 3: WikiPipelineState — Pipeline State Definition

**Files:**
- Create: `wiki/pipeline_state.py`
- Test: `tests/wiki/test_pipeline_state.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/wiki/test_pipeline_state.py
"""Tests for WikiPipelineState type definition."""


def test_pipeline_state_is_typed_dict():
    from wiki.pipeline_state import WikiPipelineState
    import typing
    assert hasattr(WikiPipelineState, "__annotations__")
    annotations = typing.get_type_hints(WikiPipelineState)
    assert "business_id" in annotations
    assert "repositories" in annotations
    assert "modules" in annotations
    assert "domain_mapping" in annotations
    assert "pages" in annotations
    assert "quality_scores" in annotations
    assert "stage_timings" in annotations
    assert "errors" in annotations


def test_pipeline_state_can_be_instantiated():
    from wiki.pipeline_state import WikiPipelineState
    state: WikiPipelineState = {
        "business_id": "test-biz",
        "repositories": ["repo-a"],
        "config": {},
        "modules": {},
        "domain_mapping": {},
        "domain_tree": None,
        "topic_structure": None,
        "pages": [],
        "quality_scores": {},
        "pages_to_heal": [],
        "heal_attempts": {},
        "stage_timings": {},
        "llm_call_count": 0,
        "errors": [],
    }
    assert state["business_id"] == "test-biz"
    assert state["pages"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_pipeline_state.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'wiki.pipeline_state'`

- [ ] **Step 3: Write minimal implementation**

```python
# wiki/pipeline_state.py
"""Wiki generation pipeline state for LangGraph StateGraph."""
from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class WikiPipelineState(TypedDict):
    """State flowing through the Wiki generation pipeline.

    Each LangGraph node reads from and writes to this state.
    Only fields returned by a node are updated; others are preserved.
    """

    # --- Input (set once at pipeline start) ---
    business_id: str
    repositories: list[str]
    config: dict[str, Any]

    # --- Stage outputs (accumulated by nodes) ---
    modules: dict[str, list[Any]]
    domain_mapping: dict[str, list[Any]]
    domain_tree: list[dict[str, Any]] | None
    topic_structure: list[dict[str, Any]] | None
    pages: Annotated[list[dict[str, Any]], operator.add]

    # --- Quality tracking ---
    quality_scores: dict[str, float]
    pages_to_heal: list[str]
    heal_attempts: dict[str, int]

    # --- Observability ---
    stage_timings: dict[str, float]
    llm_call_count: int
    errors: list[str]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_pipeline_state.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/pipeline_state.py tests/wiki/test_pipeline_state.py
git commit -m "feat: define WikiPipelineState TypedDict for LangGraph"
```

---

### Task 4: StructlogCallbackHandler — Observability Bridge

**Files:**
- Create: `wiki/structlog_callback.py`
- Test: `tests/wiki/test_structlog_callback.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/wiki/test_structlog_callback.py
"""Tests for StructlogCallbackHandler."""
import pytest
from unittest.mock import patch, MagicMock


@pytest.mark.asyncio
async def test_on_llm_start_logs():
    from wiki.structlog_callback import StructlogCallbackHandler
    handler = StructlogCallbackHandler()

    with patch("wiki.structlog_callback.log") as mock_log:
        await handler.on_llm_start(
            serialized={"id": ["langchain", "chat_models", "qwen3"]},
            prompts=["Hello world, this is a test prompt"],
        )
        mock_log.info.assert_called_once()
        call_kwargs = mock_log.info.call_args
        assert call_kwargs[0][0] == "llm_call_start"


@pytest.mark.asyncio
async def test_on_llm_end_logs():
    from wiki.structlog_callback import StructlogCallbackHandler
    handler = StructlogCallbackHandler()

    with patch("wiki.structlog_callback.log") as mock_log:
        mock_response = MagicMock()
        mock_response.__str__ = lambda self: "Generated response text"
        await handler.on_llm_end(response=mock_response)
        mock_log.info.assert_called_once()
        call_kwargs = mock_log.info.call_args
        assert call_kwargs[0][0] == "llm_call_done"


@pytest.mark.asyncio
async def test_on_llm_error_logs():
    from wiki.structlog_callback import StructlogCallbackHandler
    handler = StructlogCallbackHandler()

    with patch("wiki.structlog_callback.log") as mock_log:
        await handler.on_llm_error(error=RuntimeError("timeout"))
        mock_log.error.assert_called_once()
        call_kwargs = mock_log.error.call_args
        assert call_kwargs[0][0] == "llm_call_failed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_structlog_callback.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'wiki.structlog_callback'`

- [ ] **Step 3: Write minimal implementation**

```python
# wiki/structlog_callback.py
"""Bridge LangGraph/LangChain events to structlog."""
from __future__ import annotations

from typing import Any

from langchain_core.callbacks import AsyncCallbackHandler

from log import get_logger

log = get_logger(__name__)


class StructlogCallbackHandler(AsyncCallbackHandler):
    """Emits structlog events for every LLM call in the pipeline."""

    async def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        **kwargs: Any,
    ) -> None:
        model_id = serialized.get("id", ["unknown"])
        model_name = model_id[-1] if model_id else "unknown"
        prompt_tokens = sum(len(p) // 3 for p in prompts)
        log.info("llm_call_start", model=model_name, prompt_tokens=prompt_tokens)

    async def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        response_tokens = len(str(response)) // 3
        log.info("llm_call_done", response_tokens=response_tokens)

    async def on_llm_error(self, error: BaseException, **kwargs: Any) -> None:
        log.error("llm_call_failed", error=str(error)[:200])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_structlog_callback.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/structlog_callback.py tests/wiki/test_structlog_callback.py
git commit -m "feat: add StructlogCallbackHandler for LangGraph observability"
```

---

### Task 5: Prompt Management — ChatPromptTemplate + versioned_prompt

**Files:**
- Create: `wiki/prompts.py`
- Test: `tests/wiki/test_prompts.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/wiki/test_prompts.py
"""Tests for LangChain-based prompt management."""


def test_versioned_prompt_attaches_metadata():
    from langchain_core.prompts import ChatPromptTemplate
    from wiki.prompts import versioned_prompt

    template = ChatPromptTemplate.from_messages([
        ("system", "You are helpful."),
        ("human", "Hello {name}"),
    ])
    vp = versioned_prompt("test_prompt", template, version="2.0")
    assert vp.metadata["name"] == "test_prompt"
    assert vp.metadata["version"] == "2.0"


def test_prompt_hash_changes_with_version():
    from langchain_core.prompts import ChatPromptTemplate
    from wiki.prompts import versioned_prompt, prompt_hash

    template = ChatPromptTemplate.from_messages([
        ("human", "Classify: {modules}"),
    ])
    v1 = versioned_prompt("classify", template, version="1.0")
    v2 = versioned_prompt("classify", template, version="2.0")

    h1 = prompt_hash(v1, modules="[mod_a, mod_b]")
    h2 = prompt_hash(v2, modules="[mod_a, mod_b]")
    assert h1 != h2


def test_prompt_hash_changes_with_input():
    from langchain_core.prompts import ChatPromptTemplate
    from wiki.prompts import versioned_prompt, prompt_hash

    template = ChatPromptTemplate.from_messages([
        ("human", "Classify: {modules}"),
    ])
    vp = versioned_prompt("classify", template, version="1.0")

    h1 = prompt_hash(vp, modules="[mod_a]")
    h2 = prompt_hash(vp, modules="[mod_a, mod_b]")
    assert h1 != h2


def test_domain_classify_prompt_defined():
    from wiki.prompts import DOMAIN_CLASSIFY_PROMPT
    assert DOMAIN_CLASSIFY_PROMPT is not None
    assert DOMAIN_CLASSIFY_PROMPT.metadata["name"] == "domain_classify"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_prompts.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'wiki.prompts'`

- [ ] **Step 3: Write minimal implementation**

```python
# wiki/prompts.py
"""Centralized prompt management using LangChain ChatPromptTemplate."""
from __future__ import annotations

import hashlib

from langchain_core.prompts import ChatPromptTemplate


def versioned_prompt(
    name: str,
    template: ChatPromptTemplate,
    version: str = "1.0",
) -> ChatPromptTemplate:
    """Attach version metadata for cache invalidation."""
    template.metadata = {"name": name, "version": version}
    return template


def prompt_hash(template: ChatPromptTemplate, **kwargs: str) -> str:
    """Content hash for cache key derivation."""
    version = (template.metadata or {}).get("version", "1.0")
    rendered = template.format(**kwargs)
    content = f"{version}:{rendered}"
    return hashlib.sha256(content.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Prompt definitions
# ---------------------------------------------------------------------------

DOMAIN_CLASSIFY_PROMPT = versioned_prompt(
    name="domain_classify",
    version="2.0",
    template=ChatPromptTemplate.from_messages([
        ("system", (
            "You are a software architecture expert. "
            "Classify repository modules into business domains. "
            "Output ONLY valid JSON."
        )),
        ("human", (
            "Classify the following modules into business domains.\n\n"
            "Rules:\n"
            "- Use 5-20 domains, lowercase-kebab-case names, 1-3 words\n"
            "- Each domain must have >=3 modules\n"
            "- Place shared utilities under '{infrastructure_label}'\n\n"
            "Repository: {repository_id}\n"
            "Modules:\n{modules_json}\n\n"
            "Return ONLY valid JSON: object with domain names as keys "
            "and arrays of module names as values."
        )),
    ]),
)

TOPIC_STRUCTURE_PROMPT = versioned_prompt(
    name="topic_structure",
    version="1.0",
    template=ChatPromptTemplate.from_messages([
        ("system", "You are a technical documentation planner. Output ONLY valid JSON."),
        ("human", (
            "Based on the following business domain classification, plan a Wiki structure.\n\n"
            "Rules:\n"
            "1. Generate {min_pages}-{max_pages} topic pages total\n"
            "2. Each top-level topic = one business domain or a merge of related domains\n"
            "3. Each topic can have 3-5 sub-pages\n"
            "4. Assign every module to exactly one page\n\n"
            "Domains:\n{domain_mapping_json}\n\n"
            "Output JSON: array of objects with title, description, modules, sub_topics"
        )),
    ]),
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_prompts.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/prompts.py tests/wiki/test_prompts.py
git commit -m "feat: add LangChain ChatPromptTemplate-based prompt management"
```

---

### Task 6: build_wiki_pipeline() — StateGraph Skeleton + should_heal

**Files:**
- Create: `wiki/pipeline_graph.py`
- Test: `tests/wiki/test_pipeline_graph.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/wiki/test_pipeline_graph.py
"""Tests for wiki pipeline graph definition."""
import pytest


def test_build_wiki_pipeline_returns_compiled_graph():
    from wiki.pipeline_graph import build_wiki_pipeline
    graph = build_wiki_pipeline()
    assert graph is not None
    assert hasattr(graph, "ainvoke")


def test_should_heal_returns_finalize_when_no_pages_to_heal():
    from wiki.pipeline_graph import should_heal
    state = {
        "pages_to_heal": [],
        "heal_attempts": {},
    }
    assert should_heal(state) == "finalize"


def test_should_heal_returns_heal_when_pages_need_healing():
    from wiki.pipeline_graph import should_heal
    state = {
        "pages_to_heal": ["page/a"],
        "heal_attempts": {"page/a": 0},
    }
    assert should_heal(state) == "heal_pages"


def test_should_heal_returns_finalize_when_max_attempts_reached():
    from wiki.pipeline_graph import should_heal
    state = {
        "pages_to_heal": ["page/a"],
        "heal_attempts": {"page/a": 2},
    }
    assert should_heal(state) == "finalize"


def test_pipeline_graph_has_expected_nodes():
    from wiki.pipeline_graph import build_wiki_pipeline
    graph = build_wiki_pipeline()
    node_names = set(graph.get_graph().nodes.keys())
    expected = {
        "collect_modules", "classify_domains", "decompose_hierarchy",
        "plan_structure", "compose_pages", "quality_gate",
        "heal_pages", "finalize", "__start__", "__end__",
    }
    assert expected.issubset(node_names)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_pipeline_graph.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'wiki.pipeline_graph'`

- [ ] **Step 3: Write minimal implementation**

```python
# wiki/pipeline_graph.py
"""LangGraph StateGraph definition for Wiki generation pipeline."""
from __future__ import annotations

import time
from typing import Any

from langgraph.graph import StateGraph
from langgraph.checkpoint.memory import MemorySaver

from log import get_logger
from wiki.pipeline_state import WikiPipelineState

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Conditional edges
# ---------------------------------------------------------------------------

def should_heal(state: WikiPipelineState) -> str:
    """Route to heal_pages if low-quality pages exist and retries remain."""
    pages_to_heal = state.get("pages_to_heal", [])
    heal_attempts = state.get("heal_attempts", {})
    if pages_to_heal and any(heal_attempts.get(p, 0) < 2 for p in pages_to_heal):
        return "heal_pages"
    return "finalize"


# ---------------------------------------------------------------------------
# Stub nodes (to be implemented in later Sprints)
# ---------------------------------------------------------------------------

async def collect_modules_node(state: WikiPipelineState) -> dict[str, Any]:
    log.info("pipeline_node_stub", node="collect_modules")
    return {}


async def classify_domains_node(state: WikiPipelineState) -> dict[str, Any]:
    log.info("pipeline_node_stub", node="classify_domains")
    return {}


async def decompose_hierarchy_node(state: WikiPipelineState) -> dict[str, Any]:
    log.info("pipeline_node_stub", node="decompose_hierarchy")
    return {}


async def plan_structure_node(state: WikiPipelineState) -> dict[str, Any]:
    log.info("pipeline_node_stub", node="plan_structure")
    return {}


async def compose_pages_node(state: WikiPipelineState) -> dict[str, Any]:
    log.info("pipeline_node_stub", node="compose_pages")
    return {}


async def quality_gate_node(state: WikiPipelineState) -> dict[str, Any]:
    log.info("pipeline_node_stub", node="quality_gate")
    return {"pages_to_heal": [], "quality_scores": {}}


async def heal_pages_node(state: WikiPipelineState) -> dict[str, Any]:
    log.info("pipeline_node_stub", node="heal_pages")
    return {"pages_to_heal": []}


async def finalize_node(state: WikiPipelineState) -> dict[str, Any]:
    timings = state.get("stage_timings", {})
    total_ms = sum(timings.values())
    log.info(
        "pipeline_complete",
        total_pages=len(state.get("pages", [])),
        total_elapsed_ms=total_ms,
        llm_call_count=state.get("llm_call_count", 0),
    )
    return {"errors": []}


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_wiki_pipeline() -> Any:
    """Build and compile the Wiki generation StateGraph."""
    graph = StateGraph(WikiPipelineState)

    graph.add_node("collect_modules", collect_modules_node)
    graph.add_node("classify_domains", classify_domains_node)
    graph.add_node("decompose_hierarchy", decompose_hierarchy_node)
    graph.add_node("plan_structure", plan_structure_node)
    graph.add_node("compose_pages", compose_pages_node)
    graph.add_node("quality_gate", quality_gate_node)
    graph.add_node("heal_pages", heal_pages_node)
    graph.add_node("finalize", finalize_node)

    graph.add_edge("collect_modules", "classify_domains")
    graph.add_edge("classify_domains", "decompose_hierarchy")
    graph.add_edge("decompose_hierarchy", "plan_structure")
    graph.add_edge("plan_structure", "compose_pages")
    graph.add_edge("compose_pages", "quality_gate")

    graph.add_conditional_edges(
        "quality_gate",
        should_heal,
        {"heal_pages": "heal_pages", "finalize": "finalize"},
    )
    graph.add_edge("heal_pages", "compose_pages")

    graph.set_entry_point("collect_modules")
    graph.set_finish_point("finalize")

    return graph.compile(checkpointer=MemorySaver())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_pipeline_graph.py -v`
Expected: PASS — all 5 tests green

- [ ] **Step 5: Run all Sprint 1 tests together**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/test_langgraph_import.py tests/wiki/test_langchain_adapter.py tests/wiki/test_pipeline_state.py tests/wiki/test_structlog_callback.py tests/wiki/test_prompts.py tests/wiki/test_pipeline_graph.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add wiki/pipeline_graph.py tests/wiki/test_pipeline_graph.py
git commit -m "feat: define LangGraph StateGraph skeleton with stub nodes and conditional edges"
```

---

### Task 7: Integration Test — Pipeline End-to-End with Stubs

**Files:**
- Test: `tests/wiki/test_pipeline_integration.py`

- [ ] **Step 1: Write the integration test**

```python
# tests/wiki/test_pipeline_integration.py
"""Integration test: run the stub pipeline end-to-end."""
import pytest


@pytest.mark.asyncio
async def test_stub_pipeline_runs_to_completion():
    from wiki.pipeline_graph import build_wiki_pipeline

    pipeline = build_wiki_pipeline()

    initial_state = {
        "business_id": "test-biz",
        "repositories": ["repo-a"],
        "config": {},
        "modules": {},
        "domain_mapping": {},
        "domain_tree": None,
        "topic_structure": None,
        "pages": [],
        "quality_scores": {},
        "pages_to_heal": [],
        "heal_attempts": {},
        "stage_timings": {},
        "llm_call_count": 0,
        "errors": [],
    }

    result = await pipeline.ainvoke(
        initial_state,
        config={"configurable": {"thread_id": "test-run-1"}},
    )

    assert result is not None
    assert result["business_id"] == "test-biz"
    assert isinstance(result["errors"], list)
```

- [ ] **Step 2: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_pipeline_integration.py -v`
Expected: PASS — pipeline runs through all stub nodes and finalize

- [ ] **Step 3: Run full test suite to ensure nothing is broken**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/ -v --tb=short 2>&1 | tail -30`
Expected: All existing tests still pass; new tests pass

- [ ] **Step 4: Commit**

```bash
git add tests/wiki/test_pipeline_integration.py
git commit -m "test: add integration test for stub pipeline end-to-end run"
```
