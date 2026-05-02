# Architecture Improvements Design — B-14/B-02/B-15/B-03/B-04/B-05/B-06

**Date**: 2026-05-02  
**Scope**: 7 architecture items from DEEP_ANALYSIS, implemented incrementally in priority order  
**Strategy**: Incremental — one module at a time, each rollback-safe

---

## Phase 1: B-14 — Distributed Rate Limiter (Redis Hybrid)

### Problem
`RateLimiterMiddleware` stores token buckets in a process-local `dict`. Multi-worker deployments (`uvicorn --workers N`) result in effective limit = `rpm × N`.

### Design

**Approach**: Redis-backed sliding window with automatic fallback to in-process bucket.

**Components**:

1. **`api/rate_limiter.py`** — refactored:
   - `RateLimiterMiddleware.__init__` accepts optional `redis_url: str | None`
   - On init, attempts to connect to Redis; sets `_use_redis = True/False`
   - `dispatch()` calls `_check_redis()` or `_check_local()` based on flag
   - Redis failure at runtime → logs warning + falls back to local for that request

2. **Redis strategy**: Lua script for atomic `INCR + EXPIRE`:
   ```lua
   local key = KEYS[1]
   local limit = tonumber(ARGV[1])
   local window = tonumber(ARGV[2])
   local current = redis.call("INCR", key)
   if current == 1 then
     redis.call("EXPIRE", key, window)
   end
   if current > limit then
     return 0
   end
   return 1
   ```
   Key format: `rl:{ip}:{minute_bucket}`

3. **Configuration**: Uses existing `Settings.falkordb_url` to derive Redis URL (FalkorDB runs on Redis protocol), or new `RATE_LIMIT_REDIS_URL` env var for override.

4. **Fallback**: Existing `_Bucket` / `defaultdict` logic preserved as `_check_local()`.

### Test Plan
- Unit test: mock Redis, verify Lua script logic
- Unit test: Redis unavailable → fallback to local
- Unit test: existing behavior preserved when `redis_url=None`

---

## Phase 2: B-02 + B-15 — Lifespan Decomposition + Task Supervision

### Problem
- B-02: Single `lifespan` function handles security, services, wiki, lint, shutdown — too many responsibilities
- B-15: Background tasks via `asyncio.create_task` lack supervision, cancellation, retry

### Design (Deferred — will detail when Phase 1 completes)
- Extract lifespan into pluggable lifecycle phases
- Introduce `TaskSupervisor` collecting and monitoring all background tasks
- Graceful cancellation during shutdown

---

## Phase 3: B-03 — Redis Connection Formalization

### Problem
`wiki/bootstrap.py` probes `kb.store._redis`, `_graph._redis` — private attributes.

### Design (Deferred)
- Add `get_redis_connection()` to `AppContainer` or `FalkorDBStore`
- Wiki bootstrap uses the public API

---

## Phase 4: B-04/B-05/B-06 — Large File Splits

### Problem
- B-04: `api/mcp_server.py` — 1700+ lines
- B-05: `indexer/code_graph_builder.py` — 1100+ lines
- B-06: `store/falkordb_store.py` — mixed responsibilities

### Design (Deferred)
- Split by domain/responsibility
- Maintain backward-compatible re-exports

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| v1 | 2026-05-02 | Initial design: Phase 1 (B-14) detailed |
