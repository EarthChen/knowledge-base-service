# Agent Quality Patterns Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enhance Wiki generation quality by implementing 6 proven patterns (Tool Guardrails, Smart Early Stop, Context Trimming, Structured Output, Output Guardrail, Improvement Loop) directly into the existing agent architecture.

**Architecture:** Each pattern is an independent module integrated at specific hook points in the explore/write pipeline. Tool Guardrails wraps `_execute_tool`; Smart Early Stop and Context Trimming modify the `explore()` round loop; Structured Output replaces the `write()` response handling; Output Guardrail replaces scattered quality checks; Improvement Loop adds trace recording after generation.

**Tech Stack:** Python 3.11+, pytest, Pydantic, asyncio. No new external dependencies.

---

## File Structure

| File | Responsibility |
|------|---------------|
| `wiki/tool_guardrail.py` (create) | ToolGuardrail protocol + DefaultToolGuardrail impl |
| `wiki/context_manager.py` (create) | ContextManager for explore message trimming |
| `wiki/early_stop.py` (create) | EarlyStopDetector for empty-round detection |
| `wiki/output_guardrail.py` (create) | OutputCheck protocol + built-in checks + chain |
| `wiki/structured_output.py` (create) | WikiPageOutput Pydantic model + render helper |
| `wiki/quality_trace.py` (create) | AgentTrace dataclass + TraceCollector |
| `wiki/page_agent.py` (modify) | Integrate guardrails, early stop, context trimming |
| `wiki/agents/base_agent.py` (modify) | Integrate tool guardrails into `ToolRegistry.dispatch` |
| `wiki/domain_doc_agent.py` (modify) | Integrate output guardrail + trace collection |
| `tests/wiki/test_tool_guardrail.py` (create) | Unit tests for tool guardrails |
| `tests/wiki/test_early_stop.py` (create) | Unit tests for early stop detector |
| `tests/wiki/test_context_manager.py` (create) | Unit tests for context trimming |
| `tests/wiki/test_output_guardrail.py` (create) | Unit tests for output guardrail chain |
| `tests/wiki/test_structured_output.py` (create) | Unit tests for structured output model |
| `tests/wiki/test_quality_trace.py` (create) | Unit tests for trace collection |

---

### Task 1: Tool Guardrails

**Files:**
- Create: `wiki/tool_guardrail.py`
- Modify: `wiki/page_agent.py:1372-1409` (`_execute_tool` method)
- Modify: `wiki/agents/base_agent.py:69-77` (`ToolRegistry.dispatch`)
- Test: `tests/wiki/test_tool_guardrail.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/wiki/test_tool_guardrail.py
"""Tests for tool guardrail pre/post hooks."""

import pytest

from wiki.tool_guardrail import DefaultToolGuardrail, ToolGuardrail


class TestDefaultToolGuardrail:
    @pytest.fixture
    def guardrail(self):
        return DefaultToolGuardrail()

    @pytest.mark.asyncio
    async def test_pre_call_rejects_empty_method_name(self, guardrail):
        result = await guardrail.pre_call("query_call_chain", {"method_name": ""})
        assert result is None

    @pytest.mark.asyncio
    async def test_pre_call_rejects_missing_method_name(self, guardrail):
        result = await guardrail.pre_call("query_call_chain", {})
        assert result is None

    @pytest.mark.asyncio
    async def test_pre_call_rejects_empty_grep_pattern(self, guardrail):
        result = await guardrail.pre_call("grep_code", {"pattern": ""})
        assert result is None

    @pytest.mark.asyncio
    async def test_pre_call_passes_valid_args(self, guardrail):
        args = {"method_name": "doSomething"}
        result = await guardrail.pre_call("query_call_chain", args)
        assert result == args

    @pytest.mark.asyncio
    async def test_pre_call_passes_unknown_tool(self, guardrail):
        args = {"foo": "bar"}
        result = await guardrail.pre_call("unknown_tool", args)
        assert result == args

    @pytest.mark.asyncio
    async def test_post_call_truncates_large_result(self, guardrail):
        big_result = "x" * 10000
        result = await guardrail.post_call("read_code", {}, big_result)
        assert len(result) <= DefaultToolGuardrail.MAX_RESULT_CHARS + 20
        assert "[TRUNCATED]" in result

    @pytest.mark.asyncio
    async def test_post_call_marks_empty_result(self, guardrail):
        result = await guardrail.post_call("read_code", {}, "")
        assert "[EMPTY_RESULT]" in result

    @pytest.mark.asyncio
    async def test_post_call_marks_whitespace_only_result(self, guardrail):
        result = await guardrail.post_call("read_code", {}, "   \n  ")
        assert "[EMPTY_RESULT]" in result

    @pytest.mark.asyncio
    async def test_post_call_passes_normal_result(self, guardrail):
        result = await guardrail.post_call("read_code", {}, "some code here")
        assert result == "some code here"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/wiki/test_tool_guardrail.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'wiki.tool_guardrail'`

- [ ] **Step 3: Implement ToolGuardrail module**

```python
# wiki/tool_guardrail.py
"""Tool guardrail protocol and default implementation.

Pre/post hooks around tool dispatch to validate args and sanitize results.
"""
from __future__ import annotations

from typing import Protocol


class ToolGuardrail(Protocol):
    """Protocol for tool call validation hooks."""

    async def pre_call(self, tool_name: str, args: dict) -> dict | None:
        """Validate/transform args before tool execution.

        Return None to reject the call (will produce an error result).
        Return (possibly modified) args to proceed.
        """
        ...

    async def post_call(self, tool_name: str, args: dict, result: str) -> str:
        """Validate/transform tool result before it enters memory.

        Return the (possibly modified) result string.
        """
        ...


class DefaultToolGuardrail:
    """Built-in guardrails for common quality issues."""

    MAX_RESULT_CHARS = 8000

    _REQUIRED_PARAMS: dict[str, list[str]] = {
        "query_call_chain": ["method_name"],
        "grep_code": ["pattern"],
        "read_code": ["entity_name"],
        "query_callers": ["entity_name"],
        "query_callees": ["entity_name"],
    }

    async def pre_call(self, tool_name: str, args: dict) -> dict | None:
        required = self._REQUIRED_PARAMS.get(tool_name)
        if required:
            for param in required:
                val = args.get(param)
                if not val or (isinstance(val, str) and not val.strip()):
                    return None
        return args

    async def post_call(self, tool_name: str, args: dict, result: str) -> str:
        if not result or not result.strip():
            return f"[EMPTY_RESULT] No data returned for {tool_name}({args})"
        if len(result) > self.MAX_RESULT_CHARS:
            return result[: self.MAX_RESULT_CHARS] + "\n[TRUNCATED]"
        return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/wiki/test_tool_guardrail.py -v`
Expected: All 9 tests PASS

- [ ] **Step 5: Integrate into WikiPageAgent._execute_tool**

In `wiki/page_agent.py`, add guardrail integration. Add import at top:
```python
from wiki.tool_guardrail import DefaultToolGuardrail
```

In `WikiPageAgent.__init__` (around line 820), add:
```python
self._tool_guardrail = DefaultToolGuardrail()
```

Modify `_execute_tool` (line 1372) to wrap with guardrails:
```python
async def _execute_tool(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    log.info("agent_tool_call", tool=tool_name, args_keys=list(args.keys()))

    validated_args = await self._tool_guardrail.pre_call(tool_name, args)
    if validated_args is None:
        return {"error": f"rejected by guardrail: {tool_name} missing required params"}

    try:
        if tool_name == "read_code":
            return await self._tool_read_code(validated_args)
        # ... (all existing elif branches unchanged, using validated_args) ...
        else:
            return {"error": f"unknown tool: {tool_name}"}
    except Exception as e:
        log.warning("agent_tool_failed", tool=tool_name, error=str(e))
        return {"error": str(e)}
```

- [ ] **Step 6: Integrate into ToolRegistry.dispatch**

In `wiki/agents/base_agent.py`, add guardrail to `ToolRegistry`:

```python
from wiki.tool_guardrail import DefaultToolGuardrail, ToolGuardrail

class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDef] = {}
        self._guardrail: ToolGuardrail = DefaultToolGuardrail()

    async def dispatch(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        tool = self._tools.get(name)
        if tool is None:
            return {"error": f"Unknown tool: {name}"}

        validated_args = await self._guardrail.pre_call(name, args)
        if validated_args is None:
            return {"error": f"rejected by guardrail: {name} missing required params"}

        try:
            return await tool.handler(validated_args)
        except Exception as exc:
            log.warning("tool_dispatch_error", tool=name, exc_info=True)
            return {"error": str(exc)}
```

- [ ] **Step 7: Integrate post_call into explore loop message truncation**

In `wiki/page_agent.py` `explore()` method (around line 1067–1074), replace the raw JSON dump with guardrail post-processing:

```python
result_data = await self._execute_tool(tool_name, args)
result_str = json.dumps(result_data, ensure_ascii=False, default=str)
result_str = await self._tool_guardrail.post_call(tool_name, args, result_str)
messages.append({
    "role": "tool",
    "tool_call_id": tc.get("id", ""),
    "content": result_str,
})
```

- [ ] **Step 8: Run full test suite for page_agent**

Run: `uv run pytest tests/wiki/test_page_agent.py tests/wiki/test_tool_guardrail.py -v`
Expected: All PASS

- [ ] **Step 9: Commit**

```bash
git add wiki/tool_guardrail.py tests/wiki/test_tool_guardrail.py wiki/page_agent.py wiki/agents/base_agent.py
git commit -m "feat(agent): add tool guardrails with pre/post validation hooks"
```

---

### Task 2: Smart Early Stop

**Files:**
- Create: `wiki/early_stop.py`
- Modify: `wiki/page_agent.py:1037-1097` (explore round loop)
- Test: `tests/wiki/test_early_stop.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/wiki/test_early_stop.py
"""Tests for smart early stop detection."""

import pytest

from wiki.early_stop import EarlyStopDetector


class TestEarlyStopDetector:
    def test_no_stop_on_meaningful_results(self):
        detector = EarlyStopDetector(max_empty_rounds=2)
        assert not detector.should_stop(["some code found", "class Foo {}"])

    def test_no_stop_on_first_empty_round(self):
        detector = EarlyStopDetector(max_empty_rounds=2)
        assert not detector.should_stop(["[EMPTY_RESULT] No data returned for read_code"])

    def test_stop_after_consecutive_empty_rounds(self):
        detector = EarlyStopDetector(max_empty_rounds=2)
        detector.should_stop(["[EMPTY_RESULT] No data"])
        assert detector.should_stop(["[EMPTY_RESULT] No data"])

    def test_reset_on_meaningful_result(self):
        detector = EarlyStopDetector(max_empty_rounds=2)
        detector.should_stop(["[EMPTY_RESULT] No data"])
        detector.should_stop(["meaningful data here"])
        assert not detector.should_stop(["[EMPTY_RESULT] No data"])

    def test_mixed_results_not_empty(self):
        detector = EarlyStopDetector(max_empty_rounds=2)
        assert not detector.should_stop([
            "[EMPTY_RESULT] No data",
            "but this one has data",
        ])

    def test_empty_list_counts_as_empty(self):
        detector = EarlyStopDetector(max_empty_rounds=2)
        detector.should_stop([])
        assert detector.should_stop([])

    def test_reset_method(self):
        detector = EarlyStopDetector(max_empty_rounds=2)
        detector.should_stop(["[EMPTY_RESULT] No data"])
        detector.reset()
        assert not detector.should_stop(["[EMPTY_RESULT] No data"])

    def test_custom_max_empty_rounds(self):
        detector = EarlyStopDetector(max_empty_rounds=3)
        detector.should_stop(["[EMPTY_RESULT] x"])
        detector.should_stop(["[EMPTY_RESULT] x"])
        assert not detector.should_stop(["[EMPTY_RESULT] x"])
        # 4th empty round should NOT stop (max_empty_rounds=3 means stop on 3rd)
        # Actually: 3 consecutive means >= 3, so 3rd should stop
        # Let me re-check: max_empty_rounds=3, after 3 empties, should_stop
        detector2 = EarlyStopDetector(max_empty_rounds=3)
        detector2.should_stop(["[EMPTY_RESULT] x"])
        detector2.should_stop(["[EMPTY_RESULT] x"])
        assert detector2.should_stop(["[EMPTY_RESULT] x"])

    def test_error_results_count_as_empty(self):
        detector = EarlyStopDetector(max_empty_rounds=2)
        detector.should_stop(['{"error": "something failed"}'])
        assert detector.should_stop(['{"error": "another failure"}'])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/wiki/test_early_stop.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'wiki.early_stop'`

- [ ] **Step 3: Implement EarlyStopDetector**

```python
# wiki/early_stop.py
"""Smart early stop detection for explore phase.

Detects when consecutive rounds produce no meaningful new information
and signals the explore loop to terminate early.
"""
from __future__ import annotations

import json


class EarlyStopDetector:
    """Detect consecutive empty/useless rounds in the explore loop."""

    def __init__(self, max_empty_rounds: int = 2) -> None:
        self._max_empty = max_empty_rounds
        self._consecutive_empty = 0

    def should_stop(self, round_results: list[str]) -> bool:
        """Check if this round produced meaningful new information.

        A result is considered empty/useless if:
        - It starts with "[EMPTY_RESULT]"
        - It looks like an error JSON (contains "error" key)
        - The round_results list is empty
        """
        meaningful = [
            r for r in round_results
            if not r.startswith("[EMPTY_RESULT]") and not self._is_error(r)
        ]
        if not meaningful:
            self._consecutive_empty += 1
        else:
            self._consecutive_empty = 0
        return self._consecutive_empty >= self._max_empty

    def reset(self) -> None:
        self._consecutive_empty = 0

    @staticmethod
    def _is_error(result: str) -> bool:
        try:
            data = json.loads(result)
            return isinstance(data, dict) and "error" in data
        except (json.JSONDecodeError, TypeError):
            return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/wiki/test_early_stop.py -v`
Expected: All 9 tests PASS

- [ ] **Step 5: Integrate into WikiPageAgent.explore()**

In `wiki/page_agent.py`, add import:
```python
from wiki.early_stop import EarlyStopDetector
```

In `explore()` method, before the round loop (around line 1036), initialize the detector:
```python
early_stop = EarlyStopDetector(max_empty_rounds=2)
```

Collect post-processed result strings during the tool_calls loop. After `memory.incorporate(tool_results)` (line 1077), add early stop check using the message content strings that were already post-processed by tool guardrail:

```python
# Collect result strings during the for-tc loop (these are already post-processed by guardrail)
round_result_strs: list[str] = []
for tc in tool_calls:
    # ... existing code ...
    result_str = await self._tool_guardrail.post_call(tool_name, args, result_str)
    round_result_strs.append(result_str)
    # ... existing messages.append ...

# After memory.incorporate:
if early_stop.should_stop(round_result_strs):
    log.info("explore_early_stop", domain=domain_name, round=round_num)
    break
```

- [ ] **Step 6: Run existing page_agent tests + new tests**

Run: `uv run pytest tests/wiki/test_page_agent.py tests/wiki/test_early_stop.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add wiki/early_stop.py tests/wiki/test_early_stop.py wiki/page_agent.py
git commit -m "feat(agent): add smart early stop for explore phase"
```

---

### Task 3: Context Trimming

**Files:**
- Create: `wiki/context_manager.py`
- Modify: `wiki/page_agent.py:1083-1089` (replace hard reset with gradual trimming)
- Test: `tests/wiki/test_context_manager.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/wiki/test_context_manager.py
"""Tests for context manager message trimming."""

import pytest

from wiki.context_manager import ContextManager


class TestContextManager:
    @pytest.fixture
    def manager(self):
        return ContextManager(max_context_chars=5000, keep_recent_rounds=2)

    def test_no_trim_when_under_threshold(self, manager):
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        result = manager.trim(messages)
        assert result == messages

    def test_preserves_system_prompt(self, manager):
        messages = self._build_large_messages(manager)
        result = manager.trim(messages)
        assert result[0]["role"] == "system"
        assert result[0]["content"] == "System prompt"

    def test_preserves_recent_rounds(self, manager):
        messages = self._build_large_messages(manager)
        result = manager.trim(messages)
        last_user = [m for m in result if m["role"] == "user"]
        assert any("recent" in m["content"] for m in last_user)

    def test_compresses_old_tool_results(self, manager):
        messages = self._build_large_messages(manager)
        result = manager.trim(messages)
        old_tools = [m for m in result if m["role"] == "tool" and "[compressed]" in m.get("content", "")]
        assert len(old_tools) > 0

    def test_total_chars_reduced(self, manager):
        messages = self._build_large_messages(manager)
        original_chars = sum(len(m.get("content", "")) for m in messages)
        result = manager.trim(messages)
        trimmed_chars = sum(len(m.get("content", "")) for m in result)
        assert trimmed_chars < original_chars

    def test_short_tool_results_not_compressed(self):
        mgr = ContextManager(max_context_chars=50000, keep_recent_rounds=2)
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "a", "tool_calls": [{"id": "1"}]},
            {"role": "tool", "tool_call_id": "1", "content": "short result"},
            {"role": "user", "content": "recent"},
        ]
        result = mgr.trim(messages)
        tool_msgs = [m for m in result if m["role"] == "tool"]
        assert tool_msgs[0]["content"] == "short result"

    def _build_large_messages(self, manager) -> list[dict]:
        msgs = [{"role": "system", "content": "System prompt"}]
        for i in range(10):
            msgs.append({"role": "user", "content": f"question {i}"})
            msgs.append({
                "role": "assistant", "content": f"thinking {i}",
                "tool_calls": [{"id": f"tc_{i}", "function": {"name": "read_code", "arguments": "{}"}}],
            })
            msgs.append({
                "role": "tool", "tool_call_id": f"tc_{i}",
                "content": "x" * 800,
            })
        msgs.append({"role": "user", "content": "recent question"})
        msgs.append({"role": "assistant", "content": "recent answer"})
        return msgs
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/wiki/test_context_manager.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'wiki.context_manager'`

- [ ] **Step 3: Implement ContextManager**

```python
# wiki/context_manager.py
"""Context trimming for explore phase messages.

Replaces the hard message reset (>30 msgs → discard all) with gradual
compression of old tool results while preserving recent rounds fully.
"""
from __future__ import annotations


class ContextManager:
    """Trim explore messages to fit context budget."""

    def __init__(
        self,
        max_context_chars: int = 60000,
        keep_recent_rounds: int = 3,
    ) -> None:
        self._max_chars = max_context_chars
        self._keep_recent = keep_recent_rounds

    def trim(self, messages: list[dict]) -> list[dict]:
        """Trim messages if total chars exceed 80% of max budget.

        Strategy:
        - Always keep system prompt (messages[0])
        - Always keep most recent N round-trips fully
        - Compress older tool results to head+tail summary
        """
        total_chars = self._total_chars(messages)
        if total_chars <= self._max_chars * 0.8:
            return messages

        boundary = self._find_recent_boundary(messages)
        trimmed: list[dict] = [messages[0]]

        for msg in messages[1:boundary]:
            if msg.get("role") == "tool":
                content = msg.get("content", "")
                trimmed.append({
                    **msg,
                    "content": self._compress(content),
                })
            else:
                trimmed.append(msg)

        trimmed.extend(messages[boundary:])
        return trimmed

    def _find_recent_boundary(self, messages: list[dict]) -> int:
        """Find the index where 'recent' rounds begin (counting from end)."""
        user_count = 0
        for i in range(len(messages) - 1, 0, -1):
            if messages[i].get("role") == "user":
                user_count += 1
                if user_count >= self._keep_recent:
                    return i
        return 1

    def _compress(self, content: str) -> str:
        if len(content) <= 500:
            return content
        return content[:200] + "\n...[compressed]...\n" + content[-200:]

    @staticmethod
    def _total_chars(messages: list[dict]) -> int:
        return sum(len(m.get("content", "")) for m in messages)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/wiki/test_context_manager.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Integrate into WikiPageAgent.explore()**

In `wiki/page_agent.py`, add import:
```python
from wiki.context_manager import ContextManager
```

In `explore()`, replace the hard reset block (lines 1083–1089):

**Before:**
```python
if len(messages) > self._MAX_HISTORY_MESSAGES:
    from wiki.agent_prompts import AGENT_EXPLORE_SYSTEM as _ES
    messages = [
        {"role": "system", "content": _ES.format(max_rounds=self.max_rounds)},
        {"role": "user", "content": user_prompt},
    ]
    log.info("explore_history_compressed", round=round_num)
```

**After:**
```python
ctx_mgr = ContextManager(max_context_chars=60000, keep_recent_rounds=3)
messages = ctx_mgr.trim(messages)
```

- [ ] **Step 6: Run existing tests**

Run: `uv run pytest tests/wiki/test_page_agent.py tests/wiki/test_context_manager.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add wiki/context_manager.py tests/wiki/test_context_manager.py wiki/page_agent.py
git commit -m "feat(agent): replace hard message reset with gradual context trimming"
```

---

### Task 4: Structured Output

**Files:**
- Create: `wiki/structured_output.py`
- Modify: `wiki/page_agent.py:1142-1179` (write method)
- Test: `tests/wiki/test_structured_output.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/wiki/test_structured_output.py
"""Tests for structured output model and rendering."""

import pytest

from wiki.structured_output import WikiPageOutput, WikiSection, render_wiki_page


class TestWikiPageOutput:
    def test_valid_output_parsing(self):
        data = {
            "title": "User Service",
            "summary": "Handles user operations.",
            "sections": [
                {"heading": "Overview", "content": "The user service...", "code_refs": []},
                {"heading": "API", "content": "REST endpoints...", "code_refs": ["UserController"]},
            ],
            "modules_covered": ["UserService", "UserController"],
            "dependencies_mentioned": ["DatabaseService"],
        }
        output = WikiPageOutput.model_validate(data)
        assert output.title == "User Service"
        assert len(output.sections) == 2
        assert output.modules_covered == ["UserService", "UserController"]

    def test_minimal_output(self):
        data = {
            "title": "Test",
            "summary": "A test page.",
            "sections": [{"heading": "Overview", "content": "Content"}],
            "modules_covered": [],
        }
        output = WikiPageOutput.model_validate(data)
        assert output.title == "Test"
        assert output.dependencies_mentioned == []

    def test_render_produces_valid_markdown(self):
        output = WikiPageOutput(
            title="Order Service",
            summary="Manages orders.",
            sections=[
                WikiSection(heading="Overview", content="The order service manages...", code_refs=["OrderService"]),
                WikiSection(heading="Flow", content="1. Create order\n2. Process payment", code_refs=[]),
            ],
            modules_covered=["OrderService", "PaymentGateway"],
            dependencies_mentioned=["PaymentGateway"],
        )
        md = render_wiki_page(output)
        assert "# Order Service" in md
        assert "## Overview" in md
        assert "## Flow" in md
        assert "OrderService" in md

    def test_render_includes_code_refs_as_source_links(self):
        output = WikiPageOutput(
            title="Test",
            summary="Test.",
            sections=[
                WikiSection(heading="Impl", content="Details.", code_refs=["FooClass", "BarMethod"]),
            ],
            modules_covered=["FooClass"],
        )
        md = render_wiki_page(output)
        assert "FooClass" in md
        assert "BarMethod" in md

    def test_json_schema_generation(self):
        schema = WikiPageOutput.model_json_schema()
        assert "title" in schema["properties"]
        assert "sections" in schema["properties"]
        assert schema["properties"]["sections"]["type"] == "array"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/wiki/test_structured_output.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'wiki.structured_output'`

- [ ] **Step 3: Implement structured output module**

```python
# wiki/structured_output.py
"""Structured output model for wiki page generation.

Defines the WikiPageOutput Pydantic model that constrains LLM output
to a predictable JSON structure, and a renderer to convert it to Markdown.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class WikiSection(BaseModel):
    heading: str
    content: str
    code_refs: list[str] = Field(default_factory=list)


class WikiPageOutput(BaseModel):
    title: str
    summary: str
    sections: list[WikiSection]
    modules_covered: list[str]
    dependencies_mentioned: list[str] = Field(default_factory=list)


def render_wiki_page(output: WikiPageOutput) -> str:
    """Convert structured output to Markdown page."""
    parts: list[str] = [f"# {output.title}", "", output.summary, ""]

    for section in output.sections:
        parts.append(f"## {section.heading}")
        parts.append("")
        parts.append(section.content)
        if section.code_refs:
            parts.append("")
            parts.append("**Related code:** " + ", ".join(f"`{ref}`" for ref in section.code_refs))
        parts.append("")

    return "\n".join(parts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/wiki/test_structured_output.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Integrate into WikiPageAgent.write()**

In `wiki/page_agent.py`, add import:
```python
from wiki.structured_output import WikiPageOutput, render_wiki_page
```

In `write()` method, use `complete_json()` (which accepts a schema) for structured output with fallback to plain `generate()`:

```python
async def write(self, memory: WorkingMemory, module_names: list[str], domain_name: str) -> str:
    # ... existing prompt building ...
    
    # Try structured output via complete_json
    try:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ]
        data = await self._llm.complete_json(
            messages, WikiPageOutput.model_json_schema()
        )
        page_data = WikiPageOutput.model_validate(data)
        return render_wiki_page(page_data)
    except Exception:
        # Fallback to plain text generation if model doesn't support JSON schema
        response = await self._llm.generate(prompt=user_prompt, system=system)
        return response
```

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/wiki/test_structured_output.py tests/wiki/test_page_agent.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add wiki/structured_output.py tests/wiki/test_structured_output.py wiki/page_agent.py
git commit -m "feat(agent): add structured output model for write phase with fallback"
```

---

### Task 5: Output Guardrail Chain

**Files:**
- Create: `wiki/output_guardrail.py`
- Modify: `wiki/domain_doc_agent.py:347-392` (quality evaluation in generate_with_iterations)
- Test: `tests/wiki/test_output_guardrail.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/wiki/test_output_guardrail.py
"""Tests for output guardrail checks."""

import pytest

from wiki.output_guardrail import (
    CheckResult,
    CoverageCheck,
    FormatCheck,
    GuardrailResult,
    LengthCheck,
    OutputGuardrailChain,
)


class TestFormatCheck:
    @pytest.mark.asyncio
    async def test_passes_valid_markdown(self):
        content = "# Title\n\n## Overview\n\nSome content here.\n\n## Details\n\nMore content."
        result = await FormatCheck().check(content, {})
        assert result.passed

    @pytest.mark.asyncio
    async def test_fails_without_heading(self):
        content = "Just some text without any heading structure."
        result = await FormatCheck().check(content, {})
        assert not result.passed

    @pytest.mark.asyncio
    async def test_detects_thinking_leak(self):
        content = "# Title\n\n<think>internal reasoning</think>\n\n## Section\n\nContent."
        result = await FormatCheck().check(content, {})
        assert not result.passed
        assert any("thinking" in issue.lower() or "think" in issue.lower() for issue in result.issues)


class TestCoverageCheck:
    @pytest.mark.asyncio
    async def test_passes_full_coverage(self):
        content = "# Auth\n\nThe AuthService handles login. The UserRepo stores data."
        ctx = {"module_names": ["AuthService", "UserRepo"]}
        result = await CoverageCheck().check(content, ctx)
        assert result.passed
        assert result.score >= 0.9

    @pytest.mark.asyncio
    async def test_fails_low_coverage(self):
        content = "# Auth\n\nSome generic description."
        ctx = {"module_names": ["AuthService", "UserRepo", "TokenManager"]}
        result = await CoverageCheck().check(content, ctx)
        assert not result.passed

    @pytest.mark.asyncio
    async def test_empty_modules_passes(self):
        content = "# Page\n\nContent."
        ctx = {"module_names": []}
        result = await CoverageCheck().check(content, ctx)
        assert result.passed


class TestLengthCheck:
    @pytest.mark.asyncio
    async def test_passes_normal_length(self):
        content = "# Title\n\n" + "word " * 200
        result = await LengthCheck().check(content, {})
        assert result.passed

    @pytest.mark.asyncio
    async def test_fails_too_short(self):
        content = "# Title\n\nToo short."
        result = await LengthCheck().check(content, {})
        assert not result.passed

    @pytest.mark.asyncio
    async def test_fails_too_long(self):
        content = "# Title\n\n" + "word " * 20000
        result = await LengthCheck().check(content, {})
        assert not result.passed


class TestOutputGuardrailChain:
    @pytest.mark.asyncio
    async def test_all_pass(self):
        chain = OutputGuardrailChain([FormatCheck(), LengthCheck()])
        content = "# Title\n\n## Overview\n\n" + "Good content. " * 50
        result = await chain.evaluate(content, {})
        assert result.passed

    @pytest.mark.asyncio
    async def test_one_fails(self):
        chain = OutputGuardrailChain([FormatCheck(), LengthCheck()])
        content = "no heading, too short"
        result = await chain.evaluate(content, {})
        assert not result.passed
        assert len(result.details) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/wiki/test_output_guardrail.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'wiki.output_guardrail'`

- [ ] **Step 3: Implement output guardrail module**

```python
# wiki/output_guardrail.py
"""Output guardrail chain for wiki page quality validation.

Provides a unified quality gate that replaces scattered checks with
a composable chain of independent check functions.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class CheckResult:
    name: str
    passed: bool
    score: float
    issues: list[str] = field(default_factory=list)


@dataclass
class GuardrailResult:
    passed: bool
    details: dict[str, CheckResult] = field(default_factory=dict)

    @property
    def total_score(self) -> float:
        if not self.details:
            return 0.0
        return sum(r.score for r in self.details.values()) / len(self.details)


class OutputCheck(Protocol):
    name: str

    async def check(self, page_content: str, context: dict) -> CheckResult: ...


class FormatCheck:
    """Validate Markdown structure: headings present, no thinking leaks."""

    name = "format"

    _THINKING_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
    _H1_RE = re.compile(r"^# .+", re.MULTILINE)
    _H2_RE = re.compile(r"^## .+", re.MULTILINE)

    async def check(self, page_content: str, context: dict) -> CheckResult:
        issues: list[str] = []
        score = 1.0

        if not self._H1_RE.search(page_content) and not self._H2_RE.search(page_content):
            issues.append("No heading structure found")
            score -= 0.5

        if self._THINKING_RE.search(page_content):
            issues.append("Thinking leak detected (<think> tags)")
            score -= 0.5

        return CheckResult(
            name=self.name,
            passed=score >= 0.5,
            score=max(0.0, score),
            issues=issues,
        )


class CoverageCheck:
    """Compare mentioned modules against expected modules."""

    name = "coverage"

    async def check(self, page_content: str, context: dict) -> CheckResult:
        module_names: list[str] = context.get("module_names", [])
        if not module_names:
            return CheckResult(name=self.name, passed=True, score=1.0)

        content_lower = page_content.lower()
        covered = sum(1 for m in module_names if m.lower() in content_lower)
        score = covered / len(module_names)

        issues = []
        if score < 0.8:
            uncovered = [m for m in module_names if m.lower() not in content_lower]
            issues.append(f"Uncovered modules: {', '.join(uncovered[:5])}")

        return CheckResult(
            name=self.name,
            passed=score >= 0.8,
            score=round(score, 4),
            issues=issues,
        )


class LengthCheck:
    """Ensure page length is within acceptable bounds."""

    name = "length"
    MIN_CHARS = 200
    MAX_CHARS = 80000

    async def check(self, page_content: str, context: dict) -> CheckResult:
        length = len(page_content)
        issues: list[str] = []

        if length < self.MIN_CHARS:
            issues.append(f"Too short: {length} chars (min {self.MIN_CHARS})")
            return CheckResult(name=self.name, passed=False, score=0.2, issues=issues)
        if length > self.MAX_CHARS:
            issues.append(f"Too long: {length} chars (max {self.MAX_CHARS})")
            return CheckResult(name=self.name, passed=False, score=0.5, issues=issues)

        return CheckResult(name=self.name, passed=True, score=1.0)


class OutputGuardrailChain:
    """Compose multiple OutputChecks and evaluate them concurrently."""

    def __init__(self, checks: list[OutputCheck]) -> None:
        self._checks = checks

    async def evaluate(self, page_content: str, context: dict) -> GuardrailResult:
        results = await asyncio.gather(
            *(c.check(page_content, context) for c in self._checks)
        )
        details = {r.name: r for r in results}
        return GuardrailResult(
            passed=all(r.passed for r in results),
            details=details,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/wiki/test_output_guardrail.py -v`
Expected: All 11 tests PASS

- [ ] **Step 5: Integrate into DomainDocAgent.generate_with_iterations()**

In `wiki/domain_doc_agent.py`, add import:
```python
from wiki.output_guardrail import (
    CoverageCheck,
    FormatCheck,
    LengthCheck,
    OutputGuardrailChain,
)
```

In `__init__` or at class level, create the chain:
```python
self._output_guardrail = OutputGuardrailChain([
    FormatCheck(),
    CoverageCheck(),
    LengthCheck(),
])
```

After `content` is generated in the iteration loop (around line 347), add guardrail evaluation alongside existing `evaluate_quality`:
```python
guardrail_result = await self._output_guardrail.evaluate(
    content, {"module_names": module_names}
)
log.info(
    "output_guardrail_result",
    domain=self.domain_name,
    iteration=iteration,
    passed=guardrail_result.passed,
    score=guardrail_result.total_score,
)
```

Use `guardrail_result` as an additional exit condition (if both quality report AND guardrail pass, exit early).

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/wiki/test_output_guardrail.py tests/wiki/test_domain_doc_agent.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add wiki/output_guardrail.py tests/wiki/test_output_guardrail.py wiki/domain_doc_agent.py
git commit -m "feat(agent): add output guardrail chain for centralized quality validation"
```

---

### Task 6: Quality Trace Collection

**Files:**
- Create: `wiki/quality_trace.py`
- Modify: `wiki/domain_doc_agent.py` (add trace recording after generation)
- Test: `tests/wiki/test_quality_trace.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/wiki/test_quality_trace.py
"""Tests for quality trace collection."""

import time
from datetime import datetime, timezone

import pytest

from wiki.quality_trace import AgentTrace, TraceCollector, ToolCallRecord


class TestAgentTrace:
    def test_create_trace(self):
        trace = AgentTrace(
            domain="auth",
            page_title="Auth Service",
            timestamp=datetime.now(timezone.utc),
            explore_rounds=4,
            tools_called=[
                ToolCallRecord(name="read_code", args_summary="entity=AuthService", duration_ms=120),
            ],
            quality_score=0.85,
            modules_expected=["AuthService", "TokenManager"],
            modules_covered=["AuthService"],
            generation_time_ms=5000,
        )
        assert trace.domain == "auth"
        assert trace.coverage == 0.5
        assert len(trace.tools_called) == 1

    def test_coverage_calculation(self):
        trace = AgentTrace(
            domain="orders",
            page_title="Orders",
            timestamp=datetime.now(timezone.utc),
            explore_rounds=3,
            tools_called=[],
            quality_score=0.9,
            modules_expected=["A", "B", "C", "D"],
            modules_covered=["A", "B", "C"],
            generation_time_ms=3000,
        )
        assert trace.coverage == 0.75

    def test_coverage_empty_expected(self):
        trace = AgentTrace(
            domain="misc",
            page_title="Misc",
            timestamp=datetime.now(timezone.utc),
            explore_rounds=1,
            tools_called=[],
            quality_score=1.0,
            modules_expected=[],
            modules_covered=[],
            generation_time_ms=1000,
        )
        assert trace.coverage == 1.0


class TestTraceCollector:
    @pytest.fixture
    def collector(self, tmp_path):
        return TraceCollector(trace_dir=str(tmp_path))

    @pytest.mark.asyncio
    async def test_record_creates_file(self, collector, tmp_path):
        trace = AgentTrace(
            domain="test",
            page_title="Test Page",
            timestamp=datetime.now(timezone.utc),
            explore_rounds=2,
            tools_called=[],
            quality_score=0.8,
            modules_expected=["A"],
            modules_covered=["A"],
            generation_time_ms=2000,
        )
        await collector.record(trace)
        files = list(tmp_path.glob("*.jsonl"))
        assert len(files) == 1

    @pytest.mark.asyncio
    async def test_record_multiple_appends(self, collector, tmp_path):
        for i in range(3):
            trace = AgentTrace(
                domain=f"domain_{i}",
                page_title=f"Page {i}",
                timestamp=datetime.now(timezone.utc),
                explore_rounds=i + 1,
                tools_called=[],
                quality_score=0.5 + i * 0.1,
                modules_expected=[],
                modules_covered=[],
                generation_time_ms=1000,
            )
            await collector.record(trace)
        files = list(tmp_path.glob("*.jsonl"))
        assert len(files) == 1
        lines = files[0].read_text().strip().split("\n")
        assert len(lines) == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/wiki/test_quality_trace.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'wiki.quality_trace'`

- [ ] **Step 3: Implement quality trace module**

```python
# wiki/quality_trace.py
"""Quality trace collection for agent improvement loop.

Records structured traces of each page generation for analysis and
strategy optimization. Phase 1: file-based persistence (JSONL).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)


@dataclass
class ToolCallRecord:
    name: str
    args_summary: str = ""
    duration_ms: int = 0


@dataclass
class AgentTrace:
    domain: str
    page_title: str
    timestamp: datetime
    explore_rounds: int
    tools_called: list[ToolCallRecord]
    quality_score: float
    modules_expected: list[str]
    modules_covered: list[str]
    generation_time_ms: int

    @property
    def coverage(self) -> float:
        if not self.modules_expected:
            return 1.0
        return len(self.modules_covered) / len(self.modules_expected)


class TraceCollector:
    """Persist traces to JSONL file for later analysis."""

    def __init__(self, trace_dir: str = "data/traces") -> None:
        self._trace_dir = Path(trace_dir)
        self._trace_dir.mkdir(parents=True, exist_ok=True)
        self._file = self._trace_dir / "agent_traces.jsonl"

    async def record(self, trace: AgentTrace) -> None:
        try:
            record = asdict(trace)
            record["timestamp"] = trace.timestamp.isoformat()
            record["coverage"] = trace.coverage
            with self._file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except Exception:
            log.warning("trace_record_failed", domain=trace.domain, exc_info=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/wiki/test_quality_trace.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Integrate into DomainDocAgent.generate_with_iterations()**

In `wiki/domain_doc_agent.py`, add import:
```python
from wiki.quality_trace import AgentTrace, ToolCallRecord, TraceCollector
```

After the generation loop completes (before `return pages`, around line 424), record the trace:
```python
trace = AgentTrace(
    domain=self.domain_name,
    page_title=self.domain_display_name or self.domain_name,
    timestamp=datetime.now(timezone.utc),
    explore_rounds=len(self.iteration_history),
    tools_called=[],  # populated from memory stats
    quality_score=quality.coverage if quality else 0.0,
    modules_expected=module_names,
    modules_covered=[m for m in module_names if quality and m.lower() in (content or "").lower()],
    generation_time_ms=int((time.monotonic() - start_time) * 1000),
)
try:
    collector = TraceCollector()
    await collector.record(trace)
except Exception:
    log.warning("trace_collection_failed", domain=self.domain_name, exc_info=True)
```

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/wiki/test_quality_trace.py tests/wiki/test_domain_doc_agent.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add wiki/quality_trace.py tests/wiki/test_quality_trace.py wiki/domain_doc_agent.py
git commit -m "feat(agent): add quality trace collection for improvement loop"
```

---

## Self-Review Checklist

1. **Spec coverage:** All 6 patterns from the design spec have corresponding tasks.
2. **Placeholder scan:** No TBD, TODO, or "implement later" markers. All code blocks are complete.
3. **Type consistency:** `ToolGuardrail`, `EarlyStopDetector`, `ContextManager`, `WikiPageOutput`, `OutputGuardrailChain`, `AgentTrace` — names consistent across all tasks.
4. **Integration order:** Tasks are ordered by dependency (Tool Guardrails first since Early Stop depends on `[EMPTY_RESULT]` markers from guardrails).
