# Infrastructure Resilience & Optimization — Design Spec

> **状态**: Draft | **日期**: 2026-05-20  
> **前置**: Code Audit Round 2 完成；所有 CRITICAL/HIGH/MEDIUM 问题已修复

---

## 1. Embedding 并发度配置化

### 1.1 现状

- ONNX/Torch 后端信号量硬编码为 1（串行）
- HTTP 后端有 `http_max_concurrency` 配置（默认也是 1）
- 查询嵌入和索引嵌入共享同一信号量，互相阻塞
- ONNX 内部 `batch_size=32` 有效利用了硬件，但 async 层只允许 1 个并发请求

### 1.2 设计

**方案 B（推荐）：分离查询/索引信号量 + 可配置并发度**

```python
# core/config.py - EmbeddingConfig 新增字段
class EmbeddingConfig:
    # ...existing...
    query_concurrency: int = 2      # 查询路径并发（轻量，低延迟）
    index_concurrency: int = 1      # 索引路径并发（重量，GPU 独占）
```

```python
# indexer/embedding_generator.py
class EmbeddingGenerator:
    def _get_semaphore(self, *, for_query: bool = False) -> asyncio.Semaphore:
        if for_query:
            return self._query_sem  # concurrency=query_concurrency
        return self._index_sem      # concurrency=index_concurrency
```

- `generate_for_query()` 使用 `query_concurrency`（默认 2，允许并发查询）
- `generate()` 使用 `index_concurrency`（默认 1，保护 GPU 内存）
- HTTP 后端保留独立 `http_max_concurrency`（无变化）

### 1.3 影响范围

| 文件 | 改动 |
|------|------|
| `core/config.py` | 新增 2 字段 |
| `indexer/embedding_generator.py` | 拆分信号量逻辑 (~40 行) |
| 测试 | 验证双信号量隔离 |

### 1.4 约束

- ONNX Runtime 在 CoreML/CUDA provider 下不保证线程安全；`index_concurrency > 1` 时需用 thread pool 隔离 session
- Torch MPS 不支持真正并发推理；该后端应固定 `index_concurrency=1`
- **HTTP 后端优先级**：当 backend=http 时，使用 `http_max_concurrency` 而非 query/index 分离（HTTP 无 GPU 内存限制）
- `query_concurrency > 1` 仅对 CPU/CoreML EP 安全；CUDA EP 应保持 1

---

## 2. Redis 连接韧性

### 2.1 现状

- `FalkorDBStore.execute_query` 有 `run_with_connection_retry`（5 次，指数退避）
- `BusinessManager` 直接调用 `self._conn`，无重试
- `wiki/editing_store.py` 同样无重试
- 无熔断器；Redis 持续不可用时重试风暴

### 2.2 设计

**方案 A+（推荐）：共享重试装饰器 + 简易熔断**

```python
# core/redis_resilience.py (新文件, ~80 行)

class RedisCircuitBreaker:
    """Simple circuit breaker: open after N consecutive failures, half-open after cooldown."""
    def __init__(self, failure_threshold: int = 5, cooldown_sec: float = 30.0): ...
    def record_success(self) -> None: ...
    def record_failure(self) -> None: ...
    def is_open(self) -> bool: ...

def with_redis_retry(
    max_retries: int = 3,
    backoff_base: float = 1.0,
    circuit_breaker: RedisCircuitBreaker | None = None,
):
    """Decorator for Redis operations: retry + circuit breaker."""
    def decorator(fn):
        async def wrapper(*args, **kwargs):
            if circuit_breaker and circuit_breaker.is_open():
                raise RedisUnavailableError("circuit open")
            for attempt in range(max_retries):
                try:
                    result = await fn(*args, **kwargs) if asyncio.iscoroutinefunction(fn) else fn(*args, **kwargs)
                    if circuit_breaker: circuit_breaker.record_success()
                    return result
                except (RedisConnectionError, ConnectionError, OSError, BusyLoadingError) as e:
                    if circuit_breaker: circuit_breaker.record_failure()
                    if attempt == max_retries - 1: raise
                    await asyncio.sleep(min(backoff_base * 2**attempt, 10))
        return wrapper
    return decorator
```

应用到：
- `BusinessManager`: 所有公开方法加 `@with_redis_retry()`
- `wiki/editing_store.py`: 关键操作加装饰器
- 共享一个 `RedisCircuitBreaker` 实例（通过 AppContainer 注入）

### 2.3 影响范围

| 文件 | 改动 |
|------|------|
| `core/redis_resilience.py` | 新增 (~80 行) |
| `store/business_manager.py` | 每个方法加装饰器 (~15 行) |
| `wiki/editing_store.py` | 关键方法加装饰器 (~10 行) |
| `core/container.py` | 添加 `redis_circuit_breaker` 字段 |
| 测试 | 模拟 Redis 连接中断验证重试和熔断 |

### 2.4 约束

- `BusinessManager` 是同步调用（routes 用 `run_in_executor`），装饰器需支持同步函数（内部用 `time.sleep`）
- **熔断器移至可选 follow-up**：v1 仅实现重试装饰器；熔断器在观察到 Redis 频繁不稳定后再引入
- v1 工期调整为 **0.5 天**（仅重试）

---

## 3. LLM Provider Retry 统一

### 3.1 现状

- 4 个 provider 实现各自独立的重试逻辑（`HTTPStatusError`, `TransportError`, backoff）
- `BaseLLMProvider` 协议无重试
- `LLMPortBridge._collect_stream` 有独立重试
- 4xx 和 5xx 统一重试（应区分 429 vs 400）

### 3.2 设计

**方案 B（推荐）：共享重试装饰器 + 429 智能退避**

```python
# llm/retry.py (新文件, ~60 行)

RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
NON_RETRYABLE_STATUSES = {400, 401, 403, 404, 422}

def llm_retry(max_retries: int = 3, respect_retry_after: bool = True):
    """Retry decorator for LLM API calls with 429-aware backoff."""
    def decorator(fn):
        async def wrapper(*args, **kwargs):
            for attempt in range(max_retries + 1):
                try:
                    return await fn(*args, **kwargs)
                except httpx.HTTPStatusError as e:
                    if e.response.status_code in NON_RETRYABLE_STATUSES:
                        raise  # 不可重试的客户端错误
                    if attempt == max_retries:
                        raise
                    wait = _compute_backoff(e, attempt, respect_retry_after)
                    await asyncio.sleep(wait)
                except (httpx.ConnectError, httpx.TimeoutException, ConnectionError) as e:
                    if attempt == max_retries:
                        raise
                    await asyncio.sleep(min(2 ** attempt, 10))
        return wrapper
    return decorator

def _compute_backoff(exc, attempt, respect_retry_after):
    if respect_retry_after and exc.response.status_code == 429:
        retry_after = exc.response.headers.get("Retry-After")
        if retry_after:
            return min(float(retry_after), 60)
    return min(2 ** attempt + random.uniform(0, 1), 10)  # jitter
```

应用方式：
- 各 provider 的 `_request` / `_call_api` 内部方法用 `@llm_retry()` 替代自写循环
- 删除各 provider 中重复的重试代码
- 添加 jitter 避免 thundering herd

### 3.3 影响范围

| 文件 | 改动 |
|------|------|
| `llm/retry.py` | 新增 (~60 行) |
| `llm/provider.py` | 删除重试循环，加装饰器 (-30 行) |
| `llm/openai_provider.py` | 同上 (-30 行) |
| `llm/azure_provider.py` | 同上 (-30 行) |
| `llm/custom_provider.py` | 同上 (-30 行) |
| 测试 | 验证 429 Retry-After、非可重试状态码、jitter |

### 3.4 约束

- Streaming 调用重试会重新发起完整请求（无断点续传）；`_collect_stream` 保留独立的流中断重试
- `complete_json` 的 `ValueError`（无效 JSON）不应重试——那是模型问题，不是网络问题
- **新增 `max_total_time` 参数**（默认 90s）：防止 retries × timeout 导致调用链超时
- **`complete_with_fallback` 交互**：使用 fallback 时，default provider 的 retry 应减少为 1 次（快速故障转移）
- 工期调整为 **1.5 天**（含 4 provider 重构 + fallback 交互测试）

---

## 4. 跨文件解析内存优化

### 4.1 现状

- `iter_directory_with_cross_file` 累积所有 `GraphNode` 到 `all_nodes`
- 每个节点含 `code_snippet`（平均 50-200 行代码字符串）
- 10 万个函数 × 平均 500 字节 snippet = ~50MB 仅 snippet
- 全部保留直到方法返回

### 4.2 设计

**方案 A（推荐，快速方案）：符号表瘦身 — 仅保留 cross-file 必需字段**

```python
@dataclass
class _SymbolEntry:
    """Lightweight entry for cross-file resolution (replaces full GraphNode retention)."""
    uid: str
    name: str
    fqn: str
    label: str
    file_path: str

def iter_directory_with_cross_file(self, directory, ...):
    symbol_entries: list[_SymbolEntry] = []  # 替代 all_nodes
    per_file_data: list[_CrossFileData] = []

    for rel, fpath in tasks:
        nodes, edges = self.build_from_file(...)
        # 仅保留 cross-file 需要的字段
        for node in nodes:
            symbol_entries.append(_SymbolEntry(
                uid=node.uid,
                name=node.properties.get("name", ""),
                fqn=node.properties.get("fqn", ""),
                label=node.label,
                file_path=node.properties.get("file", ""),
            ))
        per_file_data.append(self._cross_file_data_from_parse(...))
        yield rel, nodes, edges  # 完整节点仅 yield 出去，不长期持有

    symbol_tables = self._build_global_symbol_table_from_entries(symbol_entries)
    cross_edges = self._resolve_cross_file_edges(per_file_data, symbol_tables, symbol_entries)
    ...
```

内存节省估算：
- 原始 `all_nodes`：每节点 ~2KB（含 snippet, properties dict, 各种元数据）
- `_SymbolEntry`：每条目 ~200 bytes
- **~90% 内存减少**

### 4.3 影响范围

| 文件 | 改动 |
|------|------|
| `indexer/code_graph_builder.py` | 新增 `_SymbolEntry`，修改 `iter_directory_with_cross_file` (~60 行)，修改 `_build_global_symbol_table` 和 `_resolve_cross_file_edges` (~40 行) |
| 测试 | 验证 cross-file edges 仍正确生成 |

### 4.4 约束

- **实施前验证**：grep `all_nodes` 在 `_resolve_cross_file_edges` 和 `_build_global_symbol_table` 中的属性访问，确认仅用 uid/name/fqn/label/file
- 如发现其他属性需求，选择性添加到 `_SymbolEntry`（仍远比完整 GraphNode 轻量）
- 不影响 `build_from_directory()`（那是全量加载路径，用途不同）

---

## 5. TanStack Query staleTime 调优

### 5.1 现状

- 全局默认 `staleTime: 30_000` (30s)
- 很多 hooks 显式重复设置 30s（冗余）
- 慢变数据（graph stats、file tree、wiki coverage）也用 30s → 过度 refetch
- `refetchOnWindowFocus: false`（好）

### 5.2 设计

**方案 B（推荐）：定义缓存分层常量**

```typescript
// dashboard/src/api/cacheConfig.ts (新文件, ~20 行)
export const STALE_TIME = {
  REALTIME: 10_000,       // 10s - 健康检查、活跃连接
  FAST: 30_000,           // 30s - 搜索结果、wiki 页面内容
  NORMAL: 60_000,         // 60s - 仓库列表、业务列表
  SLOW: 5 * 60_000,       // 5min - 文件树、导航树
  STATIC: 30 * 60_000,    // 30min - 设置、schema 信息
} as const;
```

应用规则：
| 数据类型 | 分层 | 原因 |
|----------|------|------|
| 健康状态、编辑 presence | REALTIME | 需实时感知 |
| Wiki 页面、搜索结果 | FAST | 可能被编辑改变 |
| 仓库列表、业务列表、graph stats | NORMAL | 不频繁变化 |
| 文件树、wiki 导航树 | SLOW | 仅索引后变化 |
| 应用设置、auth 信息 | STATIC | 几乎不变 |

同时：
- 删除所有显式 `staleTime: 30_000`（与默认相同，冗余）
- 将全局默认改为 `STALE_TIME.FAST`（维持现有行为）
- 逐步为各 hook 设置合适分层

### 5.3 影响范围

| 文件 | 改动 |
|------|------|
| `dashboard/src/api/cacheConfig.ts` | 新增 (~20 行) |
| `dashboard/src/main.tsx` | 引用 `STALE_TIME.FAST` |
| ~15 hooks | 删除冗余 `staleTime: 30_000` 或设置合适分层 |
| 测试 | 无功能变化，仅缓存策略 |

### 5.4 约束

- `BusinessContext` 切换时已有 `invalidateQueries` 逻辑，staleTime 不影响切换时的刷新
- `useHealth` 用 `refetchInterval`，与 staleTime 独立
- **AuthContext 保持 120s**（不强制归入分层，介于 NORMAL 和 SLOW 之间）
- Graph stats 应从默认 30s 移至 NORMAL (60s)

---

## 6. 实施优先级

```
优先级  | 项目                    | 工期估算 | 风险
--------|------------------------|---------|-----
P0      | 跨文件内存优化          | 0.5天   | 低（仅内部数据结构）
P1      | TanStack staleTime     | 0.5天   | 极低（仅缓存策略）
P1      | Embedding 并发度        | 0.5天   | 低（新增配置字段）
P2      | LLM retry 统一         | 1.5天   | 中（4个provider重构 + fallback交互）
P2      | Redis 韧性（仅重试）    | 0.5天   | 低（装饰器 + 无架构变更）
```

---

## 7. Open Questions (审阅后更新)

1. ~~**Embedding GPU 并发安全**~~ → 已回答：默认配置安全（query_concurrency=2 用 CPU EP；CUDA 保持 1）。仅在用户显式调高时需注意。
2. ~~**Redis 熔断降级策略**~~ → 延迟至 follow-up：v1 仅做重试，无需回答降级策略。
3. **LLM 全局令牌桶**：当前单实例部署不需要；多实例/多 agent 部署时需要在 ProviderFactory 层加共享限流。记录为 known limitation，后续按需实现。

## 8. Sequential Thinking 审阅结论

**整体评价**：设计可靠，无根本性缺陷。修正事项：
- Redis 方案 v1 精简为仅重试（去掉熔断器），工期 0.5 天
- LLM retry 增加 `max_total_time` 参数 + fallback 交互说明，工期 1.5 天
- 跨文件内存方案需实施前验证属性访问
- staleTime 中 AuthContext 保持 120s，不强制归入分层
- 5 项提案互相独立，可并行实施
