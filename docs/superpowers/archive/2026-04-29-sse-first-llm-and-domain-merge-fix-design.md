# SSE-First LLM Calls & Business Wiki Domain Merge Fix

> **Status:** Approved  
> **Created:** 2026-04-29  
> **Scope:** Backend — LLM bridge layer + cross-repo domain planner  
> **Estimated Effort:** ~1 day (3 changes)

---

## 1. Problem

Business wiki generation (`mode=full`) fails at the `classifying_domains` phase. Root cause chain:

1. Per-repo domain classification **succeeds** (962 modules → 13 batches → 105 domains in 40s)
2. Cross-repo merge prompt asks LLM to output ALL 962 module reassignments as JSON (~15k tokens)
3. LLM response generation takes too long → `ai-gateway` / intermediate proxy drops the TCP connection
4. `httpx.ReadError(BrokenResourceError())` after 3 retries
5. Classification falls back to `__infrastructure__` → no business semantics in wiki tree

The non-streaming `LLMProvider.complete()` waits for the full response with no data flowing on the wire, making the idle connection vulnerable to proxy timeouts. `LLMProvider.complete_stream()` (SSE) already exists but is not used by the wiki pipeline.

Reference: DeepWiki uses WebSocket + HTTP streaming for all LLM interactions; CodeWiki uses lightweight inputs (component IDs only). Neither does cross-repo domain merging.

## 2. Design

### 2.1 Fix 1: SSE-First `generate()` in LLMPortBridge (Critical)

**File:** `llm/base_provider.py`  
**Method:** `LLMPortBridge.generate()`

Change `generate()` to prefer streaming when the underlying provider supports it. Streaming keeps the TCP connection alive with incremental SSE chunks, preventing proxy/gateway timeouts.

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
    """Collect an SSE stream into a single string with bridge-level retry."""
    import httpx

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
                import asyncio
                await asyncio.sleep(min(2 ** attempt, 10))
    raise last_exc  # type: ignore[misc]
```

**Key decisions:**
- Retry at Bridge level (not Provider level) to avoid partial-response corruption
- `supports_streaming` check preserves backward compatibility
- `LLMPort` protocol unchanged — callers are unaware of the switch
- All wiki LLM calls (domain classification, hierarchical decomposition, page composition, semantic diagrams) automatically benefit

### 2.2 Fix 2: Lightweight Domain-Name Merge Prompt

**File:** `wiki/cross_repo_domain_planner.py`  
**Method:** `_build_merge_prompt()` + `_classify_multi_batch()`

Replace the heavy merge prompt (input: all modules per domain, output: all module reassignments) with a lightweight domain-name alignment prompt.

**Before:** LLM must output 962 `[repo_id, module_name]` pairs (~15k tokens output)  
**After:** LLM only maps domain names across repos (~500 tokens output)

New merge prompt structure:
```
Input to LLM:
{
  "ultron/ultron-composite": ["Auth", "Payments", "User Management", ...],
  "ultron/user-moa": ["Authentication", "Payment Service", "User Profiles", ...]
}

Output from LLM (lightweight):
{
  "Authentication": {"ultron/ultron-composite": "Auth", "ultron/user-moa": "Authentication"},
  "Payments": {"ultron/ultron-composite": "Payments", "ultron/user-moa": "Payment Service"},
  ...
}
```

Then programmatically reassign modules based on the domain name mapping.

### 2.3 Fix 3: Per-Repo Fallback Instead of `__infrastructure__`

**File:** `wiki/cross_repo_domain_planner.py`  
**Method:** `_classify_multi_batch()`

When the cross-repo merge LLM call fails, fall back to the per-repo classification results (which already succeeded) instead of dumping everything into `__infrastructure__`.

```python
# Before: all modules → __infrastructure__ (loses all semantics)
return self._all_infrastructure(pairs_in_order)

# After: keep per-repo domains as-is; same-name domains from different repos
# naturally merge (e.g. both repos' "Auth" modules end up in one "Auth" domain)
result: dict[str, list[tuple[str, str]]] = {}
for repo_id, domain_map in per_repo.items():
    for domain, module_names in domain_map.items():
        result.setdefault(domain, []).extend(
            (repo_id, name) for name in module_names
        )
return self._merge_llm_assignment(result, valid_pairs, pairs_in_order)
```

## 3. Tasks

### Task 1: SSE-First LLMPortBridge.generate() (~0.5 day)

**Modify** `llm/base_provider.py`:
- Add `_collect_stream()` helper with bridge-level retry
- Change `generate()` to call `_collect_stream()` when `supports_streaming` is True
- Keep `generate_stream()` as-is for backward compatibility

**Tests:**
- test_generate_prefers_streaming_when_supported
- test_generate_fallback_to_complete_when_no_streaming
- test_collect_stream_retry_on_transport_error
- test_collect_stream_no_partial_response_corruption

### Task 2: Lightweight Domain-Name Merge (~0.3 day)

**Modify** `wiki/cross_repo_domain_planner.py`:
- New `_build_lightweight_merge_prompt()` — sends only domain name lists
- New `_parse_domain_name_mapping()` — parses the name mapping response
- New `_apply_domain_name_mapping()` — programmatically reassigns modules
- Update `_classify_multi_batch()` to use the new flow

**Tests:**
- test_lightweight_merge_prompt_size
- test_parse_domain_name_mapping
- test_apply_domain_name_mapping_preserves_all_modules

### Task 3: Per-Repo Fallback (~0.2 day)

**Modify** `wiki/cross_repo_domain_planner.py`:
- Update `_classify_multi_batch()` failure path to preserve per-repo results
- Ensure all modules are still assigned

**Tests:**
- test_merge_failure_preserves_per_repo_domains
- test_fallback_covers_all_modules

## 4. Risk Assessment

| Risk | Mitigation |
|------|-----------|
| SSE not supported by provider | `supports_streaming` check + fallback to `complete()` |
| Streaming partial response on retry | Bridge-level retry collects fresh parts each attempt |
| Lightweight merge loses nuance | Only affects domain NAME alignment, not module assignment |
| Per-repo fallback creates duplicate domains | Acceptable — domains from different repos may genuinely differ |

## 5. Success Criteria

- Business wiki generation with `mode=full` completes without `ReadError`
- Domain classification produces meaningful business domains (not `__infrastructure__`)
- All existing tests pass without regression
- Wiki tree in frontend shows business-semantic domain navigation
