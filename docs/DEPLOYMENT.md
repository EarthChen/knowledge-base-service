# Deployment and operations

## Prerequisites

| Requirement | Notes |
|-------------|--------|
| Python | **3.12+** (`requires-python` in `pyproject.toml`) |
| FalkorDB | Redis-compatible graph DB; network reachable from the app |
| Git | For clone/pull indexing (Dockerfile installs git) |
| Node / pnpm | Only on build hosts that compile the dashboard |
| Reverse proxy | Optional; see **Trust proxy** for rate limiting |

## Environment variables

Configuration uses **pydantic-settings** with `.env` and nested delimiter `__`. Below, nested keys map to `Section__FIELD` (e.g. `FALKORDB__HOST` → `settings.falkordb.host`).

### Core server

| Variable | Default | Description |
|----------|---------|-------------|
| `HOST` | `0.0.0.0` | Bind host |
| `PORT` | `8100` | Bind port |
| `LOG_LEVEL` | `INFO` | Logging level |

### FalkorDB

| Variable | Default | Description |
|----------|---------|-------------|
| `FALKORDB__HOST` | `localhost` | Redis/FalkorDB host |
| `FALKORDB__PORT` | `6379` | Port |
| `FALKORDB__PASSWORD` | `""` | Password inside nested config |
| `FALKORDB__GRAPH_NAME` | `code_knowledge` | Graph name |
| `FALKORDB_PASSWORD` | `""` | Top-level fallback applied when nested password is empty (`service.py`) |

### Embedding (`EMBEDDING__*`)

| Variable | Default | Description |
|----------|---------|-------------|
| `EMBEDDING__MODEL_NAME` | `BAAI/bge-m3` | Model id |
| `EMBEDDING__DIMENSION` | `1024` | Vector dimension |
| `EMBEDDING__DEVICE` | `auto` | `auto` resolves cuda → mps → cpu |
| `EMBEDDING__BACKEND` | `onnx` | `auto` picks `torch` on MPS, else `onnx` |
| `EMBEDDING__ONNX_PATH` | `""` | Optional ONNX model path |
| `EMBEDDING__BATCH_SIZE` | `32` | Batch size |
| `EMBEDDING__CHUNK_SIZE` | `64` | Chunk batching helper |
| `EMBEDDING__USE_FP16` | `true` | FP16 where supported |
| `EMBEDDING__MAX_LENGTH` | `8192` | Token/window limit |
| `EMBEDDING__QUERY_PREFIX` | `""` | Query prefix for asymmetric models |
| `EMBEDDING__TRUST_REMOTE_CODE` | `true` | HF hub flag |

### LLM (`LLM__*` and gateway)

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM__ENABLED` | `false` | Master LLM switch |
| `LLM__CONCEPT_EXTRACTION_ENABLED` | `false` | Extra indexing pass |
| `LLM__BUSINESS_FLOW_ENABLED` | `false` | Business flow inference |
| `LLM__DEFAULT_PROVIDER` | `gateway` | Provider key |
| `LLM__FALLBACK_PROVIDER` | `""` | Fallback provider |
| `LLM__BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible base |
| `LLM__API_KEY` | `""` | API key |
| `LLM__MODEL` | `gpt-4o-mini` | Default chat model |
| `LLM__DEEP_SEARCH_MODEL` | `gpt-4o` | Deep search model |
| `LLM__MAX_CONCURRENT` | `10` | Concurrency limit |
| `LLM__TIMEOUT` | `30` | Request timeout (s) |
| `LLM__RETRY_COUNT` | `3` | Retries |
| `LLM__TEMPERATURE` | `0.1` | Sampling temperature |
| `LLM__SYNTHESIS_MAX_TOKENS` | `2000` | Synthesis cap |
| `LLM__GATEWAY__ENABLED` | `false` | ACP gateway WebSocket mode |
| `LLM__GATEWAY__ENRICHMENT_ENABLED` | `true` | Gateway-driven enrichment |
| `LLM__GATEWAY__WS_URL` | `""` | Override WS URL |
| `LLM__GATEWAY__HTTP_URL` | `""` | Override HTTP URL |
| `LLM__GATEWAY__IDLE_TIMEOUT` | `3600` | Idle timeout (≥ 60) |

### Wiki feature flags (`WIKI__*`)

| Variable | Default | Description |
|----------|---------|-------------|
| `WIKI__COT_ENABLED` | `false` | Chain-of-thought style toggles |
| `WIKI__COT_ANALYSIS_MODEL` | `""` | Analysis model override |
| `WIKI__COT_GENERATION_MODEL` | `""` | Generation model override |
| `WIKI__AUTO_UPDATE_ON_INDEX` | `false` | Auto wiki refresh hooks |

### Hybrid search (`HYBRID_SEARCH__*`)

| Variable | Default | Description |
|----------|---------|-------------|
| `HYBRID_SEARCH__QUERY_EXPANSION_ENABLED` | `true` | Graph-based query expansion |
| `HYBRID_SEARCH__INCLUDE_RAW_DOCS_IN_RESULTS` | `false` | Include raw doc payloads |
| `HYBRID_SEARCH__USE_CHILD_CHUNKS` | `true` | Prefer chunk-level retrieval path |
| `HYBRID_SEARCH__CHILD_CHUNK_WINDOW_CHARS` | `800` | Chunk window |
| `HYBRID_SEARCH__CHILD_CHUNK_STRIDE_CHARS` | `600` | Stride |
| `HYBRID_SEARCH__CHILD_CHUNK_MIN_PARENT_CHARS` | `400` | Minimum parent size to chunk |

### Reranker (`RERANK__*`)

| Variable | Default | Description |
|----------|---------|-------------|
| `RERANK__ENABLED` | `false` | Cross-encoder rerank after RRF |
| `RERANK__MODEL_NAME` | `BAAI/bge-reranker-v2-m3` | Reranker model |
| `RERANK__DEVICE` | `auto` | Device |
| `RERANK__BATCH_SIZE` | `32` | Batch size |
| `RERANK__TOP_N` | `30` | Candidates passed to reranker |

### Git / clone (`GIT__*`)

| Variable | Default | Description |
|----------|---------|-------------|
| `GIT__GITLAB_URL` | `""` | GitLab base URL for token injection |
| `GIT__GITLAB_TOKEN` | `""` | HTTPS token |
| `GIT__SSH_KEY_PATH` | `""` | SSH key for git@ remotes |
| `GIT__CLONE_BASE_PATH` | `./data/repos` | Clone root |
| `GIT__CLONE_TIMEOUT` | `600` | Clone timeout (s) |
| `GIT__PULL_TIMEOUT` | `120` | Pull timeout (s) |
| `GIT__SSL_VERIFY` | `false` | TLS verify for GitLab HTTPS |

### Indexing lists

| Variable | Description |
|----------|-------------|
| `SUPPORTED_LANGUAGES` | Comma-separated or JSON list (default python, java, go, javascript, typescript) |
| `FILE_EXTENSIONS` | Complex mapping; prefer config file / defaults |
| `EXCLUDE_DIRS` | Skipped directory names (node_modules, .git, …) |

### Rate limiting

| Variable | Default | Description |
|----------|---------|-------------|
| `RATE_LIMIT_RPM` | `120` | Requests per minute per IP; **0** disables |
| `RATE_LIMIT_TRUST_PROXY` | `false` | Use `X-Forwarded-For` first hop when true |

Excluded paths (no token consumption): `/health`, `/assets/*`, `/api/v1/hooks/*`, `/favicon.ico`.

### Auth

| Variable | Default | Description |
|----------|---------|-------------|
| `REQUIRE_AUTH` | `false` | If true, service refuses start without tokens; unauthenticated requests get 403 on protected routes |
| `API_TOKEN` | `""` | Single token mapped to **admin** |
| `API_TOKENS` | `""` | `viewer:tok1,editor:tok2` comma list |
| `TOKENS_FILE` | `tokens.yaml` | Structured tokens (resolved relative to project root if not absolute) |

**tokens.yaml** format (see `auth.py`): list under `tokens:` with `token`, `role` (`viewer` \| `editor` \| `admin`), optional `business` binding.

## Production deployment

### Docker

The repository `Dockerfile` uses Python 3.12-slim, installs **uv**, runs `uv pip install --system`, preloads Tree-sitter grammars, runs as non-root `kbuser`, exposes **8100**, and sets `EMBEDDING__DEVICE=cpu` and `EMBEDDING__BACKEND=onnx`.

Build and run (example):

```bash
docker build -t kb-service .
docker run --rm -p 8100:8100 \
  -e FALKORDB__HOST=host.docker.internal \
  -e FALKORDB_PASSWORD=secret \
  kb-service
```

Mount volumes for `./data/repos` if using git clones; persist FalkorDB data via its own deployment.

### Reverse proxy

- Terminate TLS at nginx/Traefik/Caddy.
- Set `RATE_LIMIT_TRUST_PROXY=true` **only** when the app sees the proxy’s forwarded client IP correctly.
- For SSE (`/api/v1/deep-search/stream`), disable buffering (`X-Accel-Buffering: no` is already set).

## Security checklist

- [ ] Configure `TOKENS_FILE` or `API_TOKEN` / `API_TOKENS`; set `REQUIRE_AUTH=true` in production.
- [ ] Restrict FalkorDB to private network; use strong `FALKORDB_PASSWORD`.
- [ ] Rotate `LLM__API_KEY` and Git tokens (`GIT__GITLAB_TOKEN`, SSH keys).
- [ ] Do not expose admin routes anonymously; use separate admin tokens.
- [ ] Review `GIT__SSL_VERIFY` for your GitLab (enable in production when possible).

## Monitoring and health

| Endpoint | Purpose |
|----------|---------|
| `GET /health` | Registry readiness; **503** while initializing |
| `GET /api/v1/stats` | Graph statistics (viewer) |
| `GET /api/v1/stats/health` | Knowledge health metrics |
| `GET /api/v1/auth/me` | Token role introspection |

Structured logs use `structlog`; tune `LOG_LEVEL` for verbosity.
