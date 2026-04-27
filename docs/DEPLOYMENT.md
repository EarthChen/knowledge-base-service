# 部署与运维

## 前置条件

| 要求 | 说明 |
|------|------|
| Python | **3.12+**（`pyproject.toml` 中 `requires-python`） |
| FalkorDB | Redis 兼容图数据库；确保应用可网络访问 |
| Git | 用于克隆/拉取索引（Dockerfile 中已安装 git） |
| Node / pnpm | 仅在需要编译仪表盘的构建主机上 |
| 反向代理 | 可选；参见下方**信任代理**部分 |

## 环境变量

配置使用 **pydantic-settings**，支持 `.env` 文件和嵌套分隔符 `__`。嵌套键映射为 `Section__FIELD`（如 `FALKORDB__HOST` → `settings.falkordb.host`）。

### 核心服务

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `HOST` | `0.0.0.0` | 绑定主机 |
| `PORT` | `8100` | 绑定端口 |
| `LOG_LEVEL` | `INFO` | 日志级别 |

### FalkorDB

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `FALKORDB__HOST` | `localhost` | Redis/FalkorDB 主机 |
| `FALKORDB__PORT` | `6379` | 端口 |
| `FALKORDB__PASSWORD` | `""` | 嵌套配置中的密码 |
| `FALKORDB__GRAPH_NAME` | `code_knowledge` | 图名称 |
| `FALKORDB_PASSWORD` | `""` | 顶层回退密码，当嵌套密码为空时生效（`service.py`） |

### 嵌入（`EMBEDDING__*`）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `EMBEDDING__MODEL_NAME` | `BAAI/bge-m3` | 模型 ID |
| `EMBEDDING__DIMENSION` | `1024` | 向量维度 |
| `EMBEDDING__DEVICE` | `auto` | `auto` 按 cuda → mps → cpu 顺序解析 |
| `EMBEDDING__BACKEND` | `onnx` | `auto` 在 MPS 上选择 `torch`，否则 `onnx` |
| `EMBEDDING__ONNX_PATH` | `""` | 可选 ONNX 模型路径 |
| `EMBEDDING__BATCH_SIZE` | `32` | 批大小 |
| `EMBEDDING__CHUNK_SIZE` | `64` | 分块批处理辅助 |
| `EMBEDDING__USE_FP16` | `true` | 支持时启用 FP16 |
| `EMBEDDING__MAX_LENGTH` | `8192` | Token/窗口限制 |
| `EMBEDDING__QUERY_PREFIX` | `""` | 非对称模型的查询前缀 |
| `EMBEDDING__TRUST_REMOTE_CODE` | `true` | HuggingFace Hub 标志 |

### LLM（`LLM__*` 及网关）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LLM__ENABLED` | `false` | LLM 总开关 |
| `LLM__CONCEPT_EXTRACTION_ENABLED` | `false` | 额外索引阶段的概念提取 |
| `LLM__BUSINESS_FLOW_ENABLED` | `false` | 业务流推断 |
| `LLM__DEFAULT_PROVIDER` | `gateway` | 提供者标识 |
| `LLM__FALLBACK_PROVIDER` | `""` | 备用提供者 |
| `LLM__BASE_URL` | `https://api.openai.com/v1` | OpenAI 兼容基础 URL |
| `LLM__API_KEY` | `""` | API 密钥 |
| `LLM__MODEL` | `gpt-4o-mini` | 默认聊天模型 |
| `LLM__DEEP_SEARCH_MODEL` | `gpt-4o` | 深度搜索模型 |
| `LLM__MAX_CONCURRENT` | `10` | 并发限制 |
| `LLM__TIMEOUT` | `30` | 请求超时（秒） |
| `LLM__RETRY_COUNT` | `3` | 重试次数 |
| `LLM__TEMPERATURE` | `0.1` | 采样温度 |
| `LLM__SYNTHESIS_MAX_TOKENS` | `2000` | 合成输出上限 |
| `LLM__GATEWAY__ENABLED` | `false` | ACP 网关 WebSocket 模式 |
| `LLM__GATEWAY__ENRICHMENT_ENABLED` | `true` | 网关驱动丰富化 |
| `LLM__GATEWAY__WS_URL` | `""` | 覆盖 WebSocket URL |
| `LLM__GATEWAY__HTTP_URL` | `""` | 覆盖 HTTP URL |
| `LLM__GATEWAY__IDLE_TIMEOUT` | `3600` | 空闲超时（≥ 60） |

### Wiki 功能开关（`WIKI__*`）

以下由 `config.py` 中 `WikiConfig` 定义；与既有 Phase 1–4、导出、覆盖率等开关并列，未重复列出者仍以代码为准。

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `WIKI__COT_ENABLED` | `false` | 链式思维风格开关 |
| `WIKI__COT_ANALYSIS_MODEL` | `""` | 分析模型覆盖 |
| `WIKI__COT_GENERATION_MODEL` | `""` | 生成模型覆盖 |
| `WIKI__AUTO_UPDATE_ON_INDEX` | `false` | 索引后自动刷新 Wiki |
| `WIKI__MCP_SERVER_ENABLED` | `false` | 为 true 时启用独立 Wiki MCP：`GET /api/v1/mcp/tools/list`、`POST /api/v1/mcp/tools/call`（五工具） |
| `WIKI__LINT_SCHEDULER_ENABLED` | `true` | 为 true 时启动后台 `LintScheduler`，按间隔周期跑 Wiki lint + AutoHeal（需 `WIKI__AUTO_HEAL_ENABLED`） |
| `WIKI__LINT_SCHEDULER_INTERVAL_HOURS` | `6` | 调度周期间隔（小时） |
| `WIKI__AUTO_HEAL_ENABLED` | `true` | 为 true 时 lint 运行后自动执行 AutoHealer（清理断裂引用、标记孤立页为 deprecated） |
| `WIKI__FEEDBACK_ENABLED` | `true` | 用户反馈与置信度输入相关逻辑的总开关（`WikiConfig`；与 `GET/POST .../feedback` 及 `confidence_inputs` 的联动以当前代码为准） |
| `WIKI__DEEP_RESEARCH_ENABLED` | `false` | 为 true 时开放 `POST /api/v1/wiki/research`（多轮研究管线） |
| `WIKI__CONCEPT_MERGING_ENABLED` | `false` | 为 true 时启用跨仓实体相似与合并候选（如 `GET /api/v1/wiki/merge-candidates`） |
| `WIKI__CONCEPT_MERGE_SIMILARITY_THRESHOLD` | `0.9` | 概念合并相似度阈值（0.0–1.0） |
| `WIKI__CONFIDENCE_SCORING_ENABLED` | `true` | 为 true 时计算并回写 `WikiPage.confidence_score`（0.0–1.0，来源/新鲜度/反馈等综合；与 `config.WikiConfig` 默认一致） |
| `WIKI__CONTRADICTION_DETECTION_ENABLED` | `true` | 为 true 时启用跨页矛盾检测、列表与状态流转 API（与 `config.WikiConfig` 默认一致） |
| `WIKI__SUPERSESSION_TRACKING_ENABLED` | `false` | 为 true 时持久化主张/版本/替代并开放 `GET /api/v1/wiki/pages/claim-history` |
| `WIKI__MEMORY_TIERS_ENABLED` | `false` | 为 true 时启用四层记忆模型与 `WikiQA` 上的分层晋升逻辑 |
| `WIKI__FORGETTING_ENABLED` | `false` | 为 true 时按保留曲线降低低稳定性记忆的检索优先级（不删除图节点） |
| `WIKI__SCHEMA_VALIDATION_ENABLED` | `false` | 为 true 时在 lint 中按 YAML 校验 Wiki 页结构 |
| `WIKI__SCHEMA_PATH` | `wiki/schema.yaml` | 结构定义文件路径（相对仓库工作目录或部署约定根） |
| `WIKI__FORGETTING_INITIAL_STABILITY` | `7.0` | 遗忘曲线初始稳定性参数（天尺度，与实现一致） |

**可选权重与矛盾调参**（与 `WikiConfig` 一致）：`WIKI__CONFIDENCE_WEIGHT_W1` … `WIKI__CONFIDENCE_WEIGHT_W5`（默认约 0.30 / 0.25 / 0.25 / 0.20，**W5 默认 1.0** 为惩罚系数用途）、`WIKI__CONTRADICTION_SIMILARITY_THRESHOLD`（默认 `0.75`）。生产环境请结合 `LLM__ENABLED` 与具体 Provider 再开启深度研究、矛盾裁决等能力。

**配置示例**（开发机启用 Wiki MCP、周期 lint、置信度与矛盾检测）：

```bash
WIKI__MCP_SERVER_ENABLED=true
WIKI__LINT_SCHEDULER_ENABLED=true
WIKI__LINT_SCHEDULER_INTERVAL_HOURS=6
WIKI__CONFIDENCE_SCORING_ENABLED=true
WIKI__CONTRADICTION_DETECTION_ENABLED=true
LLM__ENABLED=true
```

### 混合搜索（`HYBRID_SEARCH__*`）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `HYBRID_SEARCH__QUERY_EXPANSION_ENABLED` | `true` | 基于图的查询扩展 |
| `HYBRID_SEARCH__INCLUDE_RAW_DOCS_IN_RESULTS` | `false` | 结果中包含原始文档载荷 |
| `HYBRID_SEARCH__USE_CHILD_CHUNKS` | `true` | 优先使用子块级检索路径 |
| `HYBRID_SEARCH__CHILD_CHUNK_WINDOW_CHARS` | `800` | 分块窗口 |
| `HYBRID_SEARCH__CHILD_CHUNK_STRIDE_CHARS` | `600` | 步长 |
| `HYBRID_SEARCH__CHILD_CHUNK_MIN_PARENT_CHARS` | `400` | 最小父块长度阈值 |
| `HYBRID_SEARCH__ENABLE_BM25` | `true` | 启用 BM25 全文搜索路径（基于 FalkorDB RediSearch） |
| `HYBRID_SEARCH__BM25_WEIGHT` | `1.2` | BM25 在 RRF 融合中的权重 |

### 重排序器（`RERANK__*`）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `RERANK__ENABLED` | `false` | RRF 后启用交叉编码器重排序 |
| `RERANK__MODEL_NAME` | `BAAI/bge-reranker-v2-m3` | 重排序模型 |
| `RERANK__DEVICE` | `auto` | 设备 |
| `RERANK__BATCH_SIZE` | `32` | 批大小 |
| `RERANK__TOP_N` | `30` | 传入重排序器的候选数 |

### Git / 克隆（`GIT__*`）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `GIT__GITLAB_URL` | `""` | GitLab 基础 URL，用于 Token 注入 |
| `GIT__GITLAB_TOKEN` | `""` | HTTPS Token |
| `GIT__SSH_KEY_PATH` | `""` | git@ 远程的 SSH 密钥路径 |
| `GIT__CLONE_BASE_PATH` | `./data/repos` | 克隆根目录 |
| `GIT__CLONE_TIMEOUT` | `600` | 克隆超时（秒） |
| `GIT__PULL_TIMEOUT` | `120` | 拉取超时（秒） |
| `GIT__SSL_VERIFY` | `false` | GitLab HTTPS 的 TLS 验证 |

### 索引列表

| 变量 | 说明 |
|------|------|
| `SUPPORTED_LANGUAGES` | 逗号分隔或 JSON 列表（默认 python, java, go, javascript, typescript） |
| `FILE_EXTENSIONS` | 复杂映射；建议使用配置文件/默认值 |
| `EXCLUDE_DIRS` | 跳过的目录名（node_modules、.git 等） |

### 限流

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `RATE_LIMIT_RPM` | `120` | 每 IP 每分钟请求数；**0** 表示禁用 |
| `RATE_LIMIT_TRUST_PROXY` | `false` | 为 true 时使用 `X-Forwarded-For` 的第一跳 |

免限流路径（不消耗令牌桶）：`/health`、`/assets/*`、`/api/v1/hooks/*`、`/favicon.ico`。

### 认证

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `REQUIRE_AUTH` | `false` | 为 true 时，无 Token 则拒绝启动；未认证请求在受保护路由上返回 403 |
| `API_TOKEN` | `""` | 单个 Token，映射为 **admin** |
| `API_TOKENS` | `""` | `viewer:tok1,editor:tok2` 逗号分隔列表 |
| `TOKENS_FILE` | `tokens.yaml` | 结构化 Token 文件（非绝对路径时相对于项目根目录） |

**tokens.yaml** 格式（参见 `auth.py`）：`tokens:` 下的列表，每项包含 `token`、`role`（`viewer` \| `editor` \| `admin`），可选 `business` 绑定。

## 生产部署

### Docker

仓库中的 `Dockerfile` 使用 Python 3.12-slim，安装 **uv**，运行 `uv pip install --system`，预加载 Tree-sitter 语法，以非 root 用户 `kbuser` 运行，暴露 **8100** 端口，设置 `EMBEDDING__DEVICE=cpu` 和 `EMBEDDING__BACKEND=onnx`。

构建与运行示例：

```bash
docker build -t kb-service .
docker run --rm -p 8100:8100 \
  -e FALKORDB__HOST=host.docker.internal \
  -e FALKORDB_PASSWORD=secret \
  kb-service
```

若使用 git 克隆，请挂载 `./data/repos` 卷；FalkorDB 数据通过其自身部署持久化。

### 反向代理

- 在 nginx/Traefik/Caddy 终止 TLS。
- **仅当**应用能正确获取代理转发的客户端 IP 时，设置 `RATE_LIMIT_TRUST_PROXY=true`。
- 对于 SSE（`/api/v1/deep-search/stream`），禁用缓冲（`X-Accel-Buffering: no` 已在响应头中设置）。

## 安全检查清单

- [ ] 配置 `TOKENS_FILE` 或 `API_TOKEN` / `API_TOKENS`；生产环境设置 `REQUIRE_AUTH=true`。
- [ ] 将 FalkorDB 限制在私有网络；使用强密码 `FALKORDB_PASSWORD`。
- [ ] 定期轮换 `LLM__API_KEY` 和 Git Token（`GIT__GITLAB_TOKEN`、SSH 密钥）。
- [ ] 不要匿名暴露管理路由；使用独立的 Admin Token。
- [ ] 审查 `GIT__SSL_VERIFY` 配置（生产环境尽可能启用）。

## 监控与健康检查

| 端点 | 用途 |
|------|------|
| `GET /health` | 注册中心就绪状态；初始化期间返回 **503** |
| `GET /api/v1/stats` | 图统计（Viewer） |
| `GET /api/v1/stats/health` | 知识库健康指标 |
| `GET /api/v1/auth/me` | Token 角色自省 |

结构化日志使用 `structlog`；通过 `LOG_LEVEL` 调整日志详细程度。
