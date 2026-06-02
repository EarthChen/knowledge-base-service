# Wiki Pipeline Resilience: Industry Best Practices (2026-06)

**Extracted from:** `docs/wiki-quality-audit.md` Rev.2  
**Purpose:** Reference material for pipeline architecture decisions

---

## Cursor Cloud Agents — Temporal Migration (2026)

Cursor's cloud agent infrastructure represents the most relevant production comparison:

| Aspect | Cursor's approach | Our pipeline |
|--------|-------------------|--------------|
| **Orchestration** | Migrated from work-stealing to **Temporal** durable execution | LangGraph StateGraph + SQLite checkpoint |
| **Scale** | 50M+ actions/day, 7M+ workflows; 40% of PRs from cloud agents | Single pipeline run, ~20 domains |
| **Timeout** | Activity-level `StartToCloseTimeout` + `HeartbeatTimeout` per tool call | Node-level `idle_timeout` + `run_timeout` |
| **Failure isolation** | Short workflows that exit after single task; activities independently retryable | Monolithic compose node; all domains fail together |
| **Recovery** | Checkpoint/replay; worker crash → resume exactly where left off | LangGraph checkpoint; error → heal cycles or skeleton |
| **Key lesson** | Split "eternal" agent workflows → shorter ones + version-gated upgrades | Our compose node IS the "eternal workflow" anti-pattern |

Source: [Cursor blog — What we've learned building cloud agents](https://cursor.com/blog/cloud-agent-lessons)

---

## LangGraph 1.2 Native Solutions

Our pipeline uses `langgraph>=1.2.0` but has incomplete API adoption:

| Mechanism | Status | Gap |
|-----------|--------|-----|
| `TimeoutPolicy(idle_timeout=180, run_timeout=3600)` | Configured | heartbeat not implemented → idle always fires |
| `error_handler=compose_error_fallback` | Registered | Signature `BaseException\|None` should be `NodeError` |
| `RetryPolicy(retry_on=(TimeoutError,))` | Configured | `NodeTimeoutError` does not inherit `TimeoutError` |
| `runtime.heartbeat()` | Not implemented | Custom agent stack bypasses LangChain callbacks |
| `NodeTimeoutError` rich metadata | Available | error_handler never receives it |

**Correct LangGraph 1.2 pattern:**

```python
# 1. Node registration
builder.add_node(
    "compose",
    compose_fn,
    timeout=TimeoutPolicy(run_timeout=3600, idle_timeout=180, refresh_on="auto"),
    retry_policy=RetryPolicy(max_attempts=2, retry_on=(NodeTimeoutError,)),
    error_handler=fallback_fn,
)

# 2. Heartbeat in long operations
async def slow_tool(state, runtime: Runtime):
    async for chunk in call_external_api():
        process(chunk)
        runtime.heartbeat()  # resets idle timer

# 3. Correct error_handler signature
def fallback_fn(state, *, error: NodeError):
    exc = error.error  # NodeTimeoutError with .node, .elapsed, .kind
```

Source: [LangGraph Fault tolerance docs](https://docs.langchain.com/oss/python/langgraph/fault-tolerance)

---

## Production Agent Resilience (2026 Industry Consensus)

| Layer | Pattern | Description | Our application |
|-------|---------|-------------|-----------------|
| 0 | **Retry** | Same call, same params; exponential backoff + jitter | LangGraph `RetryPolicy` (configured but retry_on mismatch) |
| 1 | **Fallback** | Different model/provider | compose → skeleton fallback (configured but signature bug) |
| 2 | **Reroute** | Different tool or approach | heal cycles: Targeted → Enrich → RawLLM |
| 3 | **Replan** | Generate entirely new plan | Not implemented; consider for Sprint 2+ |

**Temporal Heartbeat Pattern (industry standard):**

```go
// Temporal Activity heartbeat — structurally identical to LangGraph
agentOpts := workflow.ActivityOptions{
    StartToCloseTimeout: 120 * time.Second,
    HeartbeatTimeout:    30 * time.Second,  // equivalent to idle_timeout
    RetryPolicy:         &temporal.RetryPolicy{MaximumAttempts: 3},
}
```

Temporal resets timeout via `activity.RecordHeartbeat(ctx, progress)` inside activities. This is **structurally identical** to LangGraph's `runtime.heartbeat()`. The difference: Temporal heartbeats are per-Activity (maps to our per-domain), while LangGraph heartbeats are per-Node (maps to entire compose node).

**Key insight:** Our compose node runs 20+ parallel domain agents inside a single LangGraph node. Heartbeats must originate from the lowest level (runner, tool dispatch) to cover all parallel tasks.

---

## Durable Execution Landscape (2026)

| Solution | Representative | Use case | Applicability |
|----------|---------------|----------|---------------|
| **Temporal** | Cursor, many AI startups | Cross-hour/day agent workflows | Long-term direction; LangGraph sufficient for now |
| **LangGraph checkpoint** | Our pipeline + LangChain users | Single pipeline run state recovery | In use; need to fix error_handler |
| **Cloudflare Workflows** | Edge agents | Lightweight durable execution | Not applicable |
| **AWS Step Functions** | Enterprise backends | Low-code orchestration | Not applicable |
