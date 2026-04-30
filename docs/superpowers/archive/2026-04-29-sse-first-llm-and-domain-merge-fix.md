# SSE-First LLM & Domain Merge Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix business wiki generation failures by making LLM calls use SSE streaming by default and improving cross-repo domain merge reliability.

**Architecture:** Single-point change in `LLMPortBridge.generate()` to prefer SSE streaming, keeping connections alive during long LLM responses. Complementary fix in `CrossRepoBusinessDomainPlanner` to reduce merge prompt output size and improve fallback quality.

**Tech Stack:** Python 3.12+, httpx (SSE streaming), pytest + pytest-asyncio (TDD)

---

## File Structure

| File | Responsibility | Change Type |
|------|---------------|-------------|
| `llm/base_provider.py` | LLMPortBridge SSE-first generate | Modify |
| `wiki/cross_repo_domain_planner.py` | Lightweight merge + per-repo fallback | Modify |
| `tests/llm/test_provider_abstraction.py` | LLMPortBridge tests | Modify |
| `tests/wiki/test_cross_repo_domain_planner.py` | Domain planner tests | Modify |

---

### Task 1: SSE-First LLMPortBridge.generate()

**Files:**
- Modify: `llm/base_provider.py:127-138` (`LLMPortBridge.generate`)
- Test: `tests/llm/test_provider_abstraction.py`

- [ ] **Step 1.1: Write failing test — generate prefers streaming**

```python
@pytest.mark.asyncio
async def test_bridge_generate_prefers_streaming():
    """When provider supports streaming, generate() should use complete_stream."""
    provider = MagicMock()
    provider.supports_streaming = True

    async def fake_stream(messages, **kwargs):
        for chunk in ["Hello", " ", "World"]:
            yield chunk

    provider.complete_stream = MagicMock(side_effect=fake_stream)
    provider.complete = AsyncMock(return_value="should not be called")

    bridge = LLMPortBridge(provider)
    result = await bridge.generate("test prompt", system="sys")

    assert result == "Hello World"
    provider.complete.assert_not_awaited()
```

- [ ] **Step 1.2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/llm/test_provider_abstraction.py::test_bridge_generate_prefers_streaming -xvs`
Expected: FAIL (current `generate()` always calls `complete()`)

- [ ] **Step 1.3: Write failing test — fallback to complete when no streaming**

```python
@pytest.mark.asyncio
async def test_bridge_generate_fallback_no_streaming():
    """When provider does not support streaming, generate() falls back to complete()."""
    provider = MagicMock()
    provider.supports_streaming = False
    provider.complete = AsyncMock(return_value="non-stream result")

    bridge = LLMPortBridge(provider)
    result = await bridge.generate("prompt")

    assert result == "non-stream result"
    provider.complete.assert_awaited_once()
```

- [ ] **Step 1.4: Write failing test — bridge-level retry on transport error**

```python
@pytest.mark.asyncio
async def test_bridge_collect_stream_retries_on_transport_error():
    """_collect_stream retries on httpx.TransportError, returns result on success."""
    import httpx

    provider = MagicMock()
    provider.supports_streaming = True
    call_count = 0

    async def flaky_stream(messages, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise httpx.ReadError("connection reset")
        for chunk in ["retry", " ", "ok"]:
            yield chunk

    provider.complete_stream = MagicMock(side_effect=flaky_stream)

    bridge = LLMPortBridge(provider)
    result = await bridge.generate("prompt", system="sys")

    assert result == "retry ok"
    assert call_count == 2
```

- [ ] **Step 1.5: Implement SSE-first generate() and _collect_stream()**

Modify `llm/base_provider.py` — `LLMPortBridge`:

```python
async def generate(self, prompt: str, system: str = "", *, model: str | None = None) -> str:
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    if getattr(self._provider, "supports_streaming", False):
        return await self._collect_stream(messages, model=model)

    return await self._provider.complete(messages, model=model)

async def _collect_stream(
    self,
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    max_retries: int = 3,
) -> str:
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            parts: list[str] = []
            async for chunk in self._provider.complete_stream(messages, model=model):
                if chunk:
                    parts.append(chunk)
            return "".join(parts)
        except (httpx.HTTPStatusError, httpx.TransportError) as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                await asyncio.sleep(min(2 ** attempt, 10))
    raise last_exc
```

Add `import asyncio` and `import httpx` at file top if missing.

- [ ] **Step 1.6: Run all tests to verify pass**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/llm/test_provider_abstraction.py -xvs`
Expected: ALL PASS

---

### Task 2: Lightweight Domain-Name Merge

**Files:**
- Modify: `wiki/cross_repo_domain_planner.py:191-217` (`_classify_multi_batch`, `_build_merge_prompt`)
- Test: `tests/wiki/test_cross_repo_domain_planner.py`

- [ ] **Step 2.1: Write failing test — lightweight merge prompt uses domain names only**

```python
@pytest.mark.asyncio
async def test_lightweight_merge_sends_domain_names_only():
    """Multi-batch merge prompt should send only domain names, not module lists."""
    prompts_received = []
    llm = AsyncMock()
    async def capture_generate(prompt, system=""):
        prompts_received.append(prompt)
        if "Classify" in prompt:
            return '{"Auth": ["mod1"], "Pay": ["mod2"]}'
        return '{"Authentication": {"r1": "Auth", "r2": "Auth"}, "Payments": {"r1": "Pay", "r2": "Pay"}}'
    llm.generate = AsyncMock(side_effect=capture_generate)

    planner = CrossRepoBusinessDomainPlanner(llm, batch_threshold=2)
    all_modules = {
        "r1": [_make_module("mod1"), _make_module("mod2")],
        "r2": [_make_module("mod1"), _make_module("mod2")],
    }
    result = await planner.classify("biz", all_modules)
    merge_prompt = prompts_received[-1]
    assert "mod1" not in merge_prompt or "module" not in merge_prompt.lower()
```

- [ ] **Step 2.2: Implement _build_lightweight_merge_prompt + _parse_domain_name_mapping + _apply_domain_name_mapping**

Add three new private methods to `CrossRepoBusinessDomainPlanner`:

1. `_build_lightweight_merge_prompt(business_id, per_repo)` — extracts domain name lists only
2. `_parse_domain_name_mapping(raw)` — parses `{unified: {repo: per_repo_name}}` response
3. `_apply_domain_name_mapping(mapping, per_repo, pairs_in_order, valid_pairs)` — programmatic reassignment

Update `_classify_multi_batch` to use the new flow.

- [ ] **Step 2.3: Run all domain planner tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_cross_repo_domain_planner.py -xvs`
Expected: ALL PASS (including existing tests)

---

### Task 3: Per-Repo Fallback

**Files:**
- Modify: `wiki/cross_repo_domain_planner.py:191-217` (failure path in `_classify_multi_batch`)
- Test: `tests/wiki/test_cross_repo_domain_planner.py`

- [ ] **Step 3.1: Write failing test — merge failure preserves per-repo domains**

```python
@pytest.mark.asyncio
async def test_merge_failure_preserves_per_repo_domains():
    """When merge LLM call fails, per-repo domains should be preserved."""
    call_count = 0
    llm = AsyncMock()
    async def failing_merge(prompt, system=""):
        nonlocal call_count
        call_count += 1
        if "Classify" in prompt:
            return '{"Auth": ["mod1"], "Pay": ["mod2"]}'
        raise Exception("LLM merge failed")
    llm.generate = AsyncMock(side_effect=failing_merge)

    planner = CrossRepoBusinessDomainPlanner(llm, batch_threshold=2)
    all_modules = {
        "r1": [_make_module("mod1"), _make_module("mod2")],
        "r2": [_make_module("mod1"), _make_module("mod2")],
    }
    result = await planner.classify("biz", all_modules)
    assert "Auth" in result
    assert "Pay" in result
    assert "__infrastructure__" not in result or len(result.get("__infrastructure__", [])) == 0
```

- [ ] **Step 3.2: Implement per-repo fallback in _classify_multi_batch**

In the failure path of `_classify_multi_batch`, instead of calling `_all_infrastructure`, construct the cross-repo result from per-repo classification results.

- [ ] **Step 3.3: Run all tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_cross_repo_domain_planner.py tests/llm/test_provider_abstraction.py -xvs`
Expected: ALL PASS
