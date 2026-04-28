# Proposal: Domain Classification Prompt Sub-Batching

| Field | Value |
|-------|-------|
| **Status** | `[Approved]` |
| **Created** | 2026-04-28 23:51 |
| **Priority** | P0 (blocks Wiki generation for large repositories) |
| **Root Cause Ticket** | LLM ReadError during `classifying_domains` phase |

---

## 1. Background

### Problem

`BusinessDomainPlanner.classify()` sends ALL modules of a repository in a single LLM prompt. For large repositories like `ultron/user-moa` (4157 Module nodes), this produces a prompt of **~750K characters ≈ 187K tokens**, far exceeding any LLM context window (typical max: 8K–128K). The LLM gateway times out mid-response, causing `httpx.ReadError (BrokenResourceError)` after 3 retry attempts with exponential backoff.

### Existing But Unused Configuration

`AppWikiFlags` in `config.py` already defines:
- `business_domain_sub_batch_size: int = 80` — **not wired** into `BusinessDomainPlanner`
- `business_domain_classify_timeout: int = 600`
- `business_domain_max_concurrency: int = 3`

### Impact

- Wiki generation for **all repositories under a business ID** stalls at `classifying_domains` for 10+ minutes before falling back to `__infrastructure__` (all modules lumped into one domain).
- Business-domain Wiki pages lose meaningful domain grouping.

---

## 2. Goal

1. **P0**: Make domain classification work for repositories with 1,000+ modules by splitting prompts into sub-batches.
2. **P1**: Add structured logging for observability (batch progress, token estimation, success/failure per batch).
3. **P2** (future): Optimize further by filtering to top-level modules only, reducing total LLM calls.

---

## 3. Design

### 3.1 P0: Sub-Batch Logic in `BusinessDomainPlanner`

**File**: `wiki/business_domain_planner.py`

**Before** (simplified):
```python
async def classify(self, repository_id, modules) -> dict:
    metadata = self._collect_metadata(modules)          # ALL modules
    prompt = self._build_prompt(repository_id, metadata) # ONE giant prompt
    raw = await self._llm.generate(prompt, ...)          # ONE LLM call → BOOM
    return self._parse_domain_map(raw)
```

**After**:
```python
async def classify(
    self,
    repository_id: str,
    modules: list[GraphNode],
    *,
    sub_batch_size: int = 80,
    max_concurrency: int = 3,
) -> dict[str, list[str]]:
    if not modules:
        return {}
    names_in_order = self._module_names_in_order(modules)
    if not names_in_order:
        return {}
    valid_names = set(names_in_order)
    if self._llm is None:
        return {self._infrastructure_label: list(names_in_order)}

    # Single batch — fast path (unchanged behavior)
    if len(modules) <= sub_batch_size:
        return await self._classify_single_batch(repository_id, modules, names_in_order, valid_names)

    # Multi-batch with bounded concurrency
    batches = [modules[i:i + sub_batch_size] for i in range(0, len(modules), sub_batch_size)]
    sem = asyncio.Semaphore(max_concurrency)
    results: list[dict[str, list[str]]] = [{}] * len(batches)

    async def _run_batch(idx, batch):
        async with sem:
            batch_names = self._module_names_in_order(batch)
            batch_valid = set(batch_names)
            try:
                results[idx] = await self._classify_single_batch(
                    repository_id, batch, batch_names, batch_valid,
                )
            except Exception:
                results[idx] = {self._infrastructure_label: batch_names}

    await asyncio.gather(*[_run_batch(i, b) for i, b in enumerate(batches)])

    merged: dict[str, list[str]] = {}
    for batch_result in results:
        for domain, domain_modules in batch_result.items():
            merged.setdefault(domain, []).extend(domain_modules)

    return self._ensure_all_assigned(merged, valid_names, names_in_order)
```

#### Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Batch execution | **Bounded concurrency** via `asyncio.Semaphore` | Controlled by `business_domain_max_concurrency` (default 3); balances speed vs LLM pressure; 52 batches / 3 concurrency ≈ ~35s |
| Merge strategy | **Direct merge** (no extra LLM call) | Domain names within same repo are consistent enough; saves cost |
| Fault tolerance | **Per-batch fallback** to infrastructure | One failed batch doesn't block others |
| `sub_batch_size` source | `config.business_domain_sub_batch_size` (existing, default 80) | No new config needed |
| Concurrency source | `config.business_domain_max_concurrency` (existing, default 3) | No new config needed |

#### Prompt Size Estimation

With `sub_batch_size=80`, average module metadata ~180 chars:
- Per batch: 80 × 180 = **~14,400 chars ≈ 3,600 tokens** + prompt framework ~500 tokens ≈ **~4,100 tokens**
- Well within any model's context window (even 8K models)
- `user-moa`: ⌈4157 / 80⌉ = **52 batches**, with `max_concurrency=3` → ~18 waves × ~2s ≈ **~36 seconds**

### 3.2 P0: Wire `sub_batch_size` and `max_concurrency` from Config

**File**: `wiki/cross_repo_domain_planner.py`

In `_classify_multi_batch()`, pass both params to `BusinessDomainPlanner.classify()`:

```python
per_repo[repo_id] = await planner.classify(
    repo_id, modules,
    sub_batch_size=sub_batch_size,
    max_concurrency=max_concurrency,
)
```

Both values are read from `AppWikiFlags`:
- `business_domain_sub_batch_size` (default 80)
- `business_domain_max_concurrency` (default 3)

### 3.3 P1: Structured Logging

Add `structlog` log statements at critical points:

| Event | Level | Fields | Location |
|-------|-------|--------|----------|
| `domain_classify_start` | info | `repository_id`, `module_count`, `batch_count`, `sub_batch_size` | `classify()` entry |
| `domain_classify_batch_start` | debug | `repository_id`, `batch_index`, `batch_size`, `estimated_tokens` | each batch start |
| `domain_classify_batch_done` | info | `repository_id`, `batch_index`, `domains_found`, `elapsed_ms` | each batch end |
| `domain_classify_batch_failed` | warning | `repository_id`, `batch_index`, `exc_info=True` | batch exception |
| `domain_classify_done` | info | `repository_id`, `total_domains`, `total_elapsed_ms` | `classify()` exit |

### 3.4 P2: Future Optimizations (Not in This PR)

- **Top-level module filtering**: Query only modules without parent `CONTAINS` relationship, reducing 4157 → ~100s.
- **Dynamic batch sizing**: Estimate tokens per module and adjust batch boundaries to target ~4K tokens.
- **Cross-batch domain name unification**: Lightweight LLM call with only domain names (no module details) to normalize naming.

---

## 4. Affected Files

| File | Change Type | Description |
|------|------------|-------------|
| `wiki/business_domain_planner.py` | **Major** | Add sub-batch logic, extract `_classify_single_batch`, per-batch error handling, logging |
| `wiki/cross_repo_domain_planner.py` | **Minor** | Pass `sub_batch_size` parameter |
| `wiki/service.py` | **Minor** | Pass `sub_batch_size` from `AppWikiFlags` to planner constructors |
| `tests/wiki/test_business_domain_planner.py` | **New** | Unit tests for batching, merge, fault tolerance |

---

## 5. Test Plan

| # | Test | Type | Description |
|---|------|------|-------------|
| T1 | Small repo (≤80 modules) | Unit | Single batch path unchanged |
| T2 | Large repo (200 modules) | Unit | Verify 3 batches created, results merged correctly |
| T3 | Batch failure isolation | Unit | Mock one batch to raise, verify other batches succeed, failed batch → infrastructure |
| T4 | All batches fail | Unit | Verify graceful fallback to all-infrastructure |
| T5 | Domain merge correctness | Unit | Same domain name across batches → modules combined |
| T6 | Unassigned modules | Unit | Modules not in any LLM response → infrastructure |
| T7 | Integration with real data | Integration | Deploy to dev, trigger Wiki generation for `user-moa`, verify no ReadError |

---

## 6. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Different domain names across batches for same concept | Medium | Low | Acceptable for grouping; P2 unification will address |
| Concurrent LLM calls overload gateway | Low | Medium | Bounded by `max_concurrency` (default 3); LLM provider also has global semaphore |
| Config change breaks existing deployments | Very Low | Low | No config changes needed; existing `sub_batch_size=80` is already defined |

---

## 7. Rollback Plan

If the fix introduces regressions:
1. The existing fallback (`_all_infrastructure`) catches all exceptions — worst case is same behavior as today (all modules in one domain).
2. No schema migrations or config changes — can revert to previous code via git.
