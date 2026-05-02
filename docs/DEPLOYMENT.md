# 部署与运维（Knowledge Base Service）

本文档与仓库根目录 [`config.py`](../config.py) 中的 **Pydantic Settings** 定义一致；部署前请对照源码核对默认值与校验规则。

---

## 1. 概述

Knowledge Base Service 为基于 **FastAPI** 的独立 HTTP 服务：依赖 **FalkorDB**（Redis 兼容图数据库）存储代码知识图谱与向量检索相关数据；可选启用 **LLM**（OpenAI 兼容协议）、**交叉编码器重排序**、**Wiki 生成与运维流水线**。仪表盘为 **`dashboard/`** 下的 React（Vite）前端，构建产物通常置于 **`static/`** 由后端托管。

---

## 2. 前置条件

| 组件 | 版本 / 说明 |
|------|-------------|
| **Python** | **3.12+**（[`pyproject.toml`](../pyproject.toml) `requires-python >= 3.12`） |
| **FalkorDB** | Redis 兼容图数据库；须保证应用进程网络可达 |
| **Git** | 远程索引需克隆/拉取仓库（官方 [`Dockerfile`](../Dockerfile) 已安装 `git`） |
| **Node.js / pnpm** | **Node.js 20+** 与 **pnpm**——仅在需要**本地构建仪表盘**时使用 |
| **反向代理** | 生产环境建议置于 nginx / Traefik / Caddy 之后终止 TLS；SSE 需关闭缓冲（见 [§8](#8-反向代理与-sse)） |

**可选 PyTorch：** 若嵌入后端选择 `torch` 或需在 GPU/MPS 上使用句子向量，可安装可选依赖：`pip install ".[torch]"`（见 `pyproject.toml` `[project.optional-dependencies]`）。

---

## 3. 配置机制

- **库：** `pydantic-settings`，默认读取项目根目录 **`.env`**（UTF-8）。
- **嵌套：** 环境变量分隔符为 **`__`**。例如 `FALKORDB__HOST` → `settings.falkordb.host`。
- **大小写：** 顶层字段名在环境中通常为大写蛇形（如 `CORS_ORIGINS`、`RATE_LIMIT_RPM`）。
- **复杂类型：** `list`、`dict` 等字段一般由 Pydantic Settings 按 **JSON 字符串**解析（见各表说明）；若解析失败请以 `.env` 外置或直接在 [`config.py`](../config.py) 默认值为准并在镜像构建阶段覆盖。
- **未在 Settings 中的变量：**
  - **`KB_ENV`**：读取于 [`main.py`](../main.py) `_enforce_production_security`，**不在** `Settings` 模型内。
  - **`LOG_FORMAT`**：读取于 [`log.py`](../log.py) `setup_logging`，控制 structlog 渲染器。

---

## 4. 环境变量完整参考

下列表格默认值均来自 **`Settings(..., _env_file=None)`** 等价默认（即未加载 `.env` 时的代码默认值）。布尔值在环境中常用 `true`/`false`（不区分大小写）。

### 4.1 核心服务

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `HOST` | `0.0.0.0` | Uvicorn 绑定地址 |
| `PORT` | `8100` | Uvicorn 绑定端口 |
| `LOG_LEVEL` | `INFO` | Python/logging 数值级别传入 structlog 过滤 |
| `LOG_FORMAT` | （见 [`log.py`](../log.py)）默认 **`console`** | 取值 **`console`**（人类可读）或 **`json`**（JSON 行，便于日志采集）；非 Settings 字段 |
| `CORS_ORIGINS` | `""`（空字符串） | 逗号分隔的浏览器 **`Origin`** 白名单；**空则不挂载** `CORSMiddleware` |
| `KB_ENV` | 未设置时按 **`development`** 处理 | 设为 **`production`** 时强制执行生产门禁（见 [§9](#9-生产环境与安全清单)）；非 Settings 字段 |

### 4.2 FalkorDB

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `FALKORDB__HOST` | `localhost` | FalkorDB / Redis 主机 |
| `FALKORDB__PORT` | `6379` | 端口 |
| `FALKORDB__PASSWORD` | `""` | 嵌套密码 |
| `FALKORDB__GRAPH_NAME` | `code_knowledge` | 默认图名 |
| `FALKORDB_PASSWORD` | `""` | **顶层回退**：当嵌套 `falkordb.password` 为空且本变量非空时，由 [`services/kb_service.py`](../services/kb_service.py) / [`services/service_registry.py`](../services/service_registry.py) 合并进配置 |

### 4.3 嵌入 `EMBEDDING__*`

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `EMBEDDING__MODEL_NAME` | `BAAI/bge-m3` | HuggingFace 模型 ID |
| `EMBEDDING__DIMENSION` | `1024` | 向量维度 |
| `EMBEDDING__DEVICE` | `auto` | `auto`、`cpu`、`cuda`、`mps`；`auto` 时优先级 **cuda → mps → cpu**（见 `EmbeddingConfig.resolve_device`） |
| `EMBEDDING__BACKEND` | `onnx` | `onnx`、`torch`、`auto`；`auto` 时在 MPS 上选 **`torch`**，否则 **`onnx`** |
| `EMBEDDING__ONNX_PATH` | `""` | 自定义 ONNX 模型路径 |
| `EMBEDDING__BATCH_SIZE` | `32` | 批大小 |
| `EMBEDDING__CHUNK_SIZE` | `64` | 编码侧分块辅助参数 |
| `EMBEDDING__USE_FP16` | `True` | 半精度（在支持的后端上） |
| `EMBEDDING__MAX_LENGTH` | `8192` | 最大序列长度 |
| `EMBEDDING__QUERY_PREFIX` | `""` | 非对称模型的查询前缀 |
| `EMBEDDING__TRUST_REMOTE_CODE` | `True` | `transformers` 加载 Hub 模型时是否信任远程代码 |

官方 Docker 镜像中预置：`EMBEDDING__DEVICE=cpu`、`EMBEDDING__BACKEND=onnx`。

### 4.4 LLM `LLM__*`

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LLM__ENABLED` | `False` | LLM 功能总开关 |
| `LLM__BASE_URL` | `https://api.openai.com/v1` | OpenAI 兼容 API 根路径 |
| `LLM__API_KEY` | `""` | API Key |
| `LLM__MODEL` | `gpt-4o-mini` | 默认对话/主用模型 |
| `LLM__DEEP_SEARCH_MODEL` | `gpt-4o` | 深度搜索等较重任务用模型 |
| `LLM__MAX_CONCURRENT` | `10` | 最大并发；别名为 **`LLM__MAX_CONCURRENCY`**（`AliasChoices`） |
| `LLM__TIMEOUT` | `30` | 单次请求超时（秒） |
| `LLM__RETRY_COUNT` | `3` | 失败重试次数 |
| `LLM__TEMPERATURE` | `0.1` | 采样温度 |
| `LLM__SYNTHESIS_MAX_TOKENS` | `2000` | 合成类输出 token 上限 |
| `LLM__MAX_CONTEXT_TOKENS` | `128000` | 上下文窗口安全上限（预算计算） |
| `LLM__ENRICHMENT_STRATEGY` | `disabled` | **`disabled`** 或 **`core_only`**（索引阶段 LLM 丰富化策略；非法值启动失败） |
| `LLM__CONCEPT_EXTRACTION_ENABLED` | `False` | 概念提取（索引相关） |
| `LLM__BUSINESS_FLOW_ENABLED` | `False` | 业务流推断（索引相关） |
| `LLM__DEFAULT_PROVIDER` | `gateway` | 默认提供者标识 |
| `LLM__FALLBACK_PROVIDER` | `""` | 回退提供者 |
| `LLM__PROVIDERS` | `{}` | 多提供者配置，通常为 **JSON 对象**（结构以业务代码为准） |

#### 4.4.1 LLM 网关 `LLM__GATEWAY__*`

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LLM__GATEWAY__ENABLED` | `False` | ACP 网关模式（WebSocket 等） |
| `LLM__GATEWAY__ENRICHMENT_ENABLED` | `True` | 关闭时索引可跳过丰富化；网关仍可用于其他路径（见 [`GatewayConfig`](../config.py) 文档字符串） |
| `LLM__GATEWAY__WS_URL` | `""` | 显式 WebSocket URL；空则自 `base_url` 推导 |
| `LLM__GATEWAY__HTTP_URL` | `""` | 显式 HTTP URL；空则自 `base_url` 推导 |
| `LLM__GATEWAY__IDLE_TIMEOUT` | `3600` | 空闲超时（秒），**≥ 60**（`Field(ge=60)`） |

### 4.5 混合检索 `HYBRID_SEARCH__*`

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `HYBRID_SEARCH__QUERY_EXPANSION_ENABLED` | `True` | 查询扩展 |
| `HYBRID_SEARCH__USE_CHILD_CHUNKS` | `True` | 子块检索路径 |
| `HYBRID_SEARCH__CHILD_CHUNK_WINDOW_CHARS` | `800` | 子块窗口字符数 |
| `HYBRID_SEARCH__CHILD_CHUNK_STRIDE_CHARS` | `600` | 步长（重叠约 25% 量级） |
| `HYBRID_SEARCH__CHILD_CHUNK_MIN_PARENT_CHARS` | `400` | 父文本过小时不切子块 |
| `HYBRID_SEARCH__ENABLE_BM25` | `True` | BM25 / 全文路径（FalkorDB RediSearch） |
| `HYBRID_SEARCH__BM25_WEIGHT` | `1.2` | RRF 中 BM25 权重 |
| `HYBRID_SEARCH__INCLUDE_RAW_DOCS_IN_RESULTS` | `False` | 是否在结果中包含原始文档载荷 |

### 4.6 重排序 `RERANK__*`

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `RERANK__ENABLED` | `False` | 交叉编码器重排序 |
| `RERANK__MODEL_NAME` | `BAAI/bge-reranker-v2-m3` | 模型 ID |
| `RERANK__DEVICE` | `auto` | 设备 |
| `RERANK__BATCH_SIZE` | `32` | 批大小 |
| `RERANK__TOP_N` | `30` | 参与重排的候选数上限 |

### 4.7 Git `GIT__*`

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `GIT__GITLAB_URL` | `""` | GitLab 实例基 URL（HTTPS 注入 Token 等场景） |
| `GIT__GITLAB_TOKEN` | `""` | GitLab 访问令牌 |
| `GIT__GITHUB_TOKEN` | `""` | GitHub 令牌（如解析 PR URL 等 API 调用） |
| `GIT__SSH_KEY_PATH` | `""` | SSH 私钥路径（`git@` 远程） |
| `GIT__CLONE_BASE_PATH` | `./data/repos` | 克隆根目录 |
| `GIT__CLONE_TIMEOUT` | `600` | 克隆超时（秒） |
| `GIT__PULL_TIMEOUT` | `120` | 拉取超时（秒） |
| `GIT__SSL_VERIFY` | **`True`** | GitLab HTTPS **TLS 校验**；生产建议保持启用 |

### 4.8 认证与限流

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `REQUIRE_AUTH` | `False` | `True` 时未配置 Token 会**拒绝启动**；受保护路由未带 Token 返回 **403** |
| `API_TOKEN` | `""` | 单一 Token，角色为 **admin** |
| `API_TOKENS` | `""` | 格式 `viewer:tok1,editor:tok2` 逗号列表 |
| `TOKENS_FILE` | `tokens.yaml` | YAML 令牌文件路径；**非绝对路径时**，[`auth.py`](../auth.py) 相对于 **`auth.py` 所在目录（仓库根）**解析 |
| `RATE_LIMIT_RPM` | `120` | 每 IP 每分钟请求数；**`0`** 关闭限流 |
| `RATE_LIMIT_TRUST_PROXY` | `False` | `True` 时使用 `X-Forwarded-For` **第一跳**作为客户端 IP |

**注意（生产门禁与路径）：** `KB_ENV=production` 时，[`main.py`](../main.py) 使用 `Path(settings.tokens_file).exists()` 判断是否存在 YAML 令牌文件——该检查相对于**进程当前工作目录**。而运行时加载令牌时 [`auth.py`](../auth.py) 对相对路径相对于**项目根**。建议在 systemd / K8s / Docker 中 **`cd` 到项目根**启动，或对 `TOKENS_FILE` 使用**绝对路径**，避免误判。

**`tokens.yaml` 格式（摘要）：** 根键 `tokens:`，列表项含 `token`、`role`（`viewer` | `editor` | `admin`），可选 `business`。

### 4.9 索引语言、扩展名与排除目录

| 变量 | 默认值 / 类型 | 说明 |
|------|----------------|------|
| `SUPPORTED_LANGUAGES` | `["python","java","go","javascript","typescript"]` | 一般为 **JSON 数组**字符串 |
| `FILE_EXTENSIONS` | 见 [`config.py`](../config.py) 内嵌 `dict` | 语言 → 扩展名列表；环境覆盖多为 **JSON 对象** |
| `EXCLUDE_DIRS` | 见 [`config.py`](../config.py) | 跳过的目录名列表；环境覆盖多为 **JSON 数组** |

### 4.10 Wiki 应用级功能开关 `WIKI__*`（`AppWikiFlags`）

以下全部来自 [`config.py`](../config.py) 中 **`AppWikiFlags`**，经 `settings.wiki` 暴露。与单次 Wiki 运行的 **`wiki.models.WikiConfig`**（请求体/任务参数）不同：后者不在此表中。

#### 通用与展示

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `WIKI__REASONING_EFFORT` | `None` | 可选；字符串，供部分 OpenAI 兼容栈的推理深度等 |
| `WIKI__AUTO_UPDATE_ON_INDEX` | `False` | 索引完成后是否自动触发 Wiki 更新类逻辑 |
| `WIKI__TREE_ENABLED` | `True` | 目录树相关能力 |
| `WIKI__DUAL_VIEW_ENABLED` | `True` | 双视图类 UI/数据支持 |
| `WIKI__CODE_STRUCTURE_SEMANTIC_GROUP` | `False` | 代码结构语义分组 |
| `WIKI__CODE_STRUCTURE_SEMANTIC_GROUP_THRESHOLD` | `8` | 分组阈值 |
| `WIKI__CROSS_REFERENCE_ENABLED` | `True` | 交叉引用 |
| `WIKI__CROSS_REFERENCE_MIN_CONFIDENCE` | `0.5` | 交叉引用最小置信度 |
| `WIKI__CROSS_REPO_DOMAIN_ENABLED` | `False` | 跨仓域级能力 |
| `WIKI__DOMAIN_CLASSIFICATION_CACHE_ENABLED` | `True` | 域分类缓存 |
| `WIKI__KNOWLEDGE_INJECTION_ENABLED` | `True` | 知识注入 |
| `WIKI__SNAPSHOT_ENABLED` | `True` | Wiki 持久化后运行编译快照 |
| `WIKI__SNAPSHOT_LAYER_PAGE_THRESHOLD` | `100` | 页数达阈值时生成全局索引 + 按模块子快照 |

#### Git 发布与导出

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `WIKI__GIT_PUBLISH_ENABLED` | `False` | Wiki 发布到 Git |
| `WIKI__GIT_PUBLISH_MODE` | `incremental` | 发布模式 |
| `WIKI__GIT_PUBLISH_TRIGGER` | `manual` | 触发方式 |
| `WIKI__GIT_PUBLISH_SCHEDULE` | `0 2 * * *` | 计划表达式（配合调度实现） |
| `WIKI__GIT_REMOTE_URL` | `""` | 远程 URL |
| `WIKI__GIT_BRANCH` | `main` | 分支 |
| `WIKI__GIT_AUTHOR_NAME` | `KBS Wiki Bot` | 提交作者名 |
| `WIKI__GIT_AUTHOR_EMAIL` | `wiki-bot@company.com` | 提交作者邮箱 |
| `WIKI__GIT_TOKEN` | `""` | 推送用 Token |
| `WIKI__EXPORT_DEFAULT_VIEW` | `business_domain` | 导出默认视图 |
| `WIKI__EXPORT_MIN_TIER` | `standard` | 导出最低层级 |
| `WIKI__EXPORT_DIR_NAMING` | `original` | 导出目录命名策略 |

#### 报告与交互

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `WIKI__COVERAGE_REPORT_ENABLED` | `True` | 覆盖率报告 |
| `WIKI__STALE_DETECTION_ENABLED` | `True` | 过期检测 |
| `WIKI__SUGGESTED_QUESTIONS_ENABLED` | `True` | 推荐问题 |

#### Phase 1：代码预算与骨架

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `WIKI__CODE_BUDGET_ENABLED` | `True` | 代码 token 预算开关 |
| `WIKI__CORE_CODE_BUDGET` | `20000` | Core 层代码 budget |
| `WIKI__STANDARD_CODE_BUDGET` | `8000` | Standard 层 |
| `WIKI__SKELETON_CODE_BUDGET` | `1000` | Skeleton 层 |
| `WIKI__IMPORTANCE_CORE_PERCENTILE` | `80` | Core 百分位 |
| `WIKI__IMPORTANCE_STANDARD_PERCENTILE` | `30` | Standard 百分位 |
| `WIKI__SKELETON_STRATEGY` | `template` | 骨架策略 |
| `WIKI__SKELETON_LIGHT_MODEL` | `""` | 轻量模型覆盖 |
| `WIKI__WIKILINK_CACHE_ENABLED` | `True` | WikiLink 缓存 |

#### 社区上下文与 RAG

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `WIKI__COMMUNITY_CONTEXT_ENABLED` | `True` | 仓库概览页注入社区检测结果 |
| `WIKI__RAG_ENABLED` | `True` | Wiki 侧 RAG |
| `WIKI__RAG_TOP_K` | `5` | Top-K |
| `WIKI__RAG_MIN_SCORE` | `0.3` | 最低分 |
| `WIKI__RAG_EXCLUDE_SAME_PARENT` | `True` | 排除同父块重复 |
| `WIKI__CHUNK_EMBEDDING_BATCH_SIZE` | `64` | 块嵌入批大小 |
| `WIKI__CHUNK_EMBEDDING_MAX_LENGTH` | `512` | 块嵌入最大长度 |

**说明（迭代式 RAG）：** Wiki 问答实现中可使用迭代式 RAG 管线；历史上独立的 `iterative_rag_enabled` 开关已从应用 flags 移除（参见 `tests/integration/test_search_unification.py`）。是否走迭代路径由当前代码与请求模式决定，**无单独环境变量**。

#### 渐进式持久化与并发

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `WIKI__PROGRESSIVE_PERSIST_ENABLED` | `True` | 渐进式落盘 |
| `WIKI__PROGRESSIVE_PERSIST_BATCH_SIZE` | `20` | 批大小 |
| `WIKI__COMPOSE_CONCURRENCY` | `3` | 组合子树并发（≥ 1） |

#### 业务流聚合与委托

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `WIKI__BUSINESS_FLOW_AGGREGATION_ENABLED` | `True` | 业务流聚合 |
| `WIKI__BUSINESS_FLOW_MIN_COMMUNITY_SIZE` | `3` | 最小区间规模 |
| `WIKI__DELEGATION_ENABLED` | `True` | 委托生成 |
| `WIKI__DELEGATION_MAX_CHILDREN` | `30` | 最大子节点 |
| `WIKI__DELEGATION_MAX_CODE_LINES` | `5000` | 最大代码行数 |
| `WIKI__DELEGATION_GROUPING_STRATEGY` | `graph` | 分组策略 |

#### Phase 3 丰富化与业务域

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `WIKI__ENRICHMENT_ENABLED` | `True` | Wiki 侧丰富化总开关（与 LLM `enrichment_strategy` 不同层） |
| `WIKI__ENRICHMENT_ROUND1_ENABLED` | `True` | 第一轮丰富化 |
| `WIKI__ENRICHMENT_ROUND2_ENABLED` | `True` | 第二轮丰富化 |
| `WIKI__BUSINESS_DOMAIN_ENABLED` | `False` | 业务域分类等 |
| `WIKI__BUSINESS_DOMAIN_INFRASTRUCTURE_LABEL` | `__infrastructure__` | 基础设施标签 |
| `WIKI__BUSINESS_WIKI_BATCH_THRESHOLD` | `100` | 跨仓业务 Wiki 批阈值 |
| `WIKI__BUSINESS_DOMAIN_SUB_BATCH_SIZE` | `80` | 单仓子批模块数上限 |
| `WIKI__BUSINESS_DOMAIN_CLASSIFY_TIMEOUT` | `600` | 单仓分类等待超时（秒） |
| `WIKI__BUSINESS_DOMAIN_MAX_CONCURRENCY` | `3` | 并行仓库数上限 |
| `WIKI__BUSINESS_DOMAIN_CACHE_TTL` | `3600` | 进程内分类缓存 TTL（秒） |

#### MCP、Lint、反馈、自愈

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `WIKI__MCP_SERVER_ENABLED` | `True` | Wiki HTTP MCP 工具接口等 |
| `WIKI__LINT_SCHEDULER_ENABLED` | `True` | 后台 Lint 调度 |
| `WIKI__LINT_SCHEDULER_INTERVAL_HOURS` | `6` | 周期间隔（小时） |
| `WIKI__FEEDBACK_ENABLED` | `True` | 用户反馈相关能力 |
| `WIKI__AUTO_HEAL_ENABLED` | `True` | Lint 后 AutoHeal（断裂引用、孤立页等） |
| `WIKI__FEEDBACK_REGEN_ENABLED` | `True` | 反馈驱动再生成 |
| `WIKI__FEEDBACK_REGEN_THRESHOLD` | `3` | 负面反馈触发阈值 |
| `WIKI__FEEDBACK_REGEN_CRITICAL_IMMEDIATE` | `True` | critical 严重度是否立即再生 |
| `WIKI__FEEDBACK_REGEN_TOKEN_MULTIPLIER` | `1.5` | critical 再生 token 倍率 |
| `WIKI__FEEDBACK_REGEN_BATCH_TOKEN_MULTIPLIER` | `1.2` | 达阈再生 token 倍率 |
| `WIKI__FEEDBACK_REGEN_COOLDOWN_HOURS` | `24` | 同页自动再生冷却（小时） |

#### 深度研究、概念合并、置信与矛盾

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `WIKI__DEEP_RESEARCH_ENABLED` | `True` | `POST /api/v1/wiki/research` 等 |
| `WIKI__CONCEPT_MERGING_ENABLED` | `True` | 跨仓实体合并候选等 |
| `WIKI__CONCEPT_MERGE_SIMILARITY_THRESHOLD` | `0.9` | 合并相似度阈值 [0,1] |
| `WIKI__CONFIDENCE_SCORING_ENABLED` | `True` | `confidence_score` 回写 |
| `WIKI__CONFIDENCE_WEIGHT_W1` | `0.30` | 置信度加权 W1 |
| `WIKI__CONFIDENCE_WEIGHT_W2` | `0.25` | W2 |
| `WIKI__CONFIDENCE_WEIGHT_W3` | `0.25` | W3 |
| `WIKI__CONFIDENCE_WEIGHT_W4` | `0.20` | W4 |
| `WIKI__CONFIDENCE_WEIGHT_W5` | `1.0` | W5（惩罚等用途） |
| `WIKI__CONTRADICTION_DETECTION_ENABLED` | `True` | 矛盾检测 |
| `WIKI__CONTRADICTION_SIMILARITY_THRESHOLD` | `0.75` | 矛盾相似度阈值 [0,1] |
| `WIKI__SUPERSESSION_TRACKING_ENABLED` | `True` | 主张替代/版本历史 |
| `WIKI__CLAIM_TRACKING_CONCURRENCY` | `5` | 主张提取并发（≥ 1） |

#### 记忆层级、增量与预算

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `WIKI__MEMORY_TIERS_ENABLED` | `True` | 分层记忆模型 |
| `WIKI__FORGETTING_ENABLED` | `True` | 遗忘曲线调权（不删图节点） |
| `WIKI__INCREMENTAL_ENABLED` | `False` | 增量组合路径 |
| `WIKI__RESUME_FROM_SAVED` | `False` | 与上次基线比对跳过未变页（全量组合场景） |
| `WIKI__DEFAULT_LLM_BUDGET` | `30000` | 基线 token 预算，各组件按比例派生 |
| `WIKI__FORGETTING_INITIAL_STABILITY` | `7.0` | 遗忘曲线初始稳定性 |
| `WIKI__SCHEMA_VALIDATION_ENABLED` | `True` | Lint 中 YAML 结构校验 |
| `WIKI__SCHEMA_PATH` | `wiki/schema.yaml` | Schema 文件路径 |
| `WIKI__DECOMPOSITION_MAX_TOKENS_PER_BATCH` | `30000` | **弃用**：请优先使用 `DEFAULT_LLM_BUDGET` |

#### 解析、实体过滤与域树

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `WIKI__CROSS_FILE_RESOLUTION_ENABLED` | `True` | 跨文件解析 |
| `WIKI__ENTITY_FILTER_ENABLED` | `True` | 实体过滤 |
| `WIKI__LARGE_CLASS_METHOD_THRESHOLD` | `30` | 大类方法数阈值 |
| `WIKI__LARGE_CLASS_TOP_METHODS` | `20` | 大类保留方法 Top N |
| `WIKI__MAX_DOMAIN_DEPTH` | `4` | 域树最大深度 |
| `WIKI__MIN_MODULES_FOR_NESTING` | `3` | 嵌套所需最小区块数 |
| `WIKI__HUB_DETECTION_PERCENTILE` | `90.0` | Hub 检测百分位 |

#### 文档质量评估（Phase 4）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `WIKI__QUALITY_EVALUATION_MODE` | `quick` | 质量评估模式 |
| `WIKI__QUALITY_MIN_SCORE` | `0.6` | 最低分 |
| `WIKI__QUALITY_AUTO_HEAL` | `False` | 质量驱动自动修复 |
| `WIKI__QUALITY_JUDGE_MODEL` | `""` | 裁判模型（空则用默认链路） |
| `WIKI__QUALITY_SAMPLE_SIZE` | `20` | 抽样规模 |

---

## 5. Docker

### 5.1 官方镜像构建要点

[`Dockerfile`](../Dockerfile) 基于 **`python:3.12-slim`**，使用 **uv** 安装依赖，预解析 Tree-sitter 多语言语法，以非 root 用户 **`kbuser`** 运行，暴露 **`8100`**，默认嵌入 **`cpu` + `onnx`**。

```bash
docker build -t kb-service:latest /path/to/knowledge-base-service
docker run --rm -p 8100:8100 \
  -e FALKORDB__HOST=host.docker.internal \
  -e FALKORDB__PORT=6379 \
  -e FALKORDB_PASSWORD='your-secret' \
  -v kb-repos:/app/data/repos \
  kb-service:latest
```

- 需要 Git 克隆时，挂载 **`GIT__CLONE_BASE_PATH`** 对应目录（默认在容器内为 `/app/data/repos`）。
- FalkorDB 数据卷由 **FalkorDB 镜像/ chart** 自行持久化。

### 5.2 docker-compose 示例（FalkorDB + 服务）

以下为最小可运行示例；生产请补上 **`KB_ENV`、`REQUIRE_AUTH`、Token、资源限制、健康检查与密钥管理**。

```yaml
services:
  falkordb:
    image: falkordb/falkordb-server:latest
    ports:
      - "6379:6379"
    volumes:
      - falkordb-data:/data

  kb-service:
    build: .
    ports:
      - "8100:8100"
    environment:
      FALKORDB__HOST: falkordb
      FALKORDB__PORT: 6379
      # FALKORDB__PASSWORD: ...
      KB_ENV: production
      REQUIRE_AUTH: "true"
      API_TOKEN: ${API_TOKEN:?set API_TOKEN in .env}
      CORS_ORIGINS: "https://wiki.example.com"
      LOG_FORMAT: json
    volumes:
      - kb-repos:/app/data/repos
    depends_on:
      - falkordb

volumes:
  falkordb-data:
  kb-repos:
```

镜像名也可选用带浏览器的 **`falkordb/falkordb`**（通常另暴露 **3000**），以官方文档为准：[Docker and Docker Compose | FalkorDB Docs](https://docs.falkordb.com/operations/docker.html)。

---

## 6. 仪表盘构建（可选）

仓库 [`dashboard/`](../dashboard/)：

```bash
cd dashboard
pnpm install
pnpm run build
```

构建产物需落在后端可托管的 **`static/`**（具体以项目构建脚本或 CI 为准）。仅运行 API、不需要 SPA 时可跳过本节。

---

## 7. 监控与运维端点

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/v1/health` | 就绪检查；注册表未就绪 **503**；成功时内含组件状态，并对 **FalkorDB** ping，不可达时整体可能为 **degraded** |
| `GET` | `/api/v1/stats` | 图统计（需 **viewer** 角色，见路由依赖） |
| `GET` | `/api/v1/stats/health` | 知识库健康指标（覆盖率、陈旧度、孤立比等） |
| `GET` | `/api/v1/auth/me` | 自省认证状态：未启用 Token 时返回 `auth_enabled: false`；启用时可不带 Bearer（`role: null`）或带 `Authorization: Bearer …` |

**限流：** [`api/rate_limiter.py`](../api/rate_limiter.py) 默认跳过 **`/health`**（根路径）、**`/assets/*`**、`/favicon.ico`。**`/api/v1/health` 不在默认跳过列表中**，高频探活会占用 `RATE_LIMIT_RPM` 配额（若需豁免需改代码或降频探测）。

---

## 8. 反向代理与 SSE

以下端点使用 **Server-Sent Events** 或长连接流式响应（示例，非穷尽）：

- `POST /api/v1/deep-search/stream`（响应头含 **`X-Accel-Buffering: no`**，见 [`search_routes.py`](../api/routes/search_routes.py)）
- `POST` / `GET` `/api/v1/wiki/ask/stream` 等（部分流式端点**未**统一加该头，代理层仍建议关闭缓冲）

**Nginx 要点：**

```nginx
location /api/v1/deep-search/stream {
    proxy_pass http://kb_backend;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 3600s;
    chunked_transfer_encoding on;
}
```

对其它 SSE 路径套用相同 **`proxy_buffering off`** 模式。Caddy / Traefik 需关闭等价响应缓冲或启用流式友好配置。

---

## 9. 生产环境与安全清单

### 9.1 `KB_ENV=production` 门禁

当 **`KB_ENV=production`**（不区分大小写）时：

1. 必须 **`REQUIRE_AUTH=true`**，否则进程启动失败。
2. 必须至少配置一种 Token：**`API_TOKEN`**、**`API_TOKENS`** 或非空 **`tokens.yaml`**（存在性检查注意 [§4.8](#48-认证与限流) 中的**工作目录**问题）。

### 9.2 建议项

- **认证：** 禁止将管理类能力暴露在无 Token 环境；轮换 Token 与 LLM Key、Git Token。
- **FalkorDB：** 置于内网；强密码；限制源 IP。
- **Git：** 默认 **`GIT__SSL_VERIFY=True`**，仅在确知风险时关闭。
- **CORS：** 仅配置可信 **`CORS_ORIGINS`**，勿用 `*` 与-credentials 不当组合。
- **限流：** 反代后若需按真实客户端 IP 限流，在信任链正确时设 **`RATE_LIMIT_TRUST_PROXY=true`**。
- **SPA：** [`main.py`](../main.py) 对静态文件使用 **`resolve()` + `is_relative_to`**，缓解路径穿越（仅托管 `static/` 内资源）。
- **Cypher：** 自然语言转 Cypher 路径在 [`query/nl_cypher.py`](../query/nl_cypher.py) 对 **CREATE / MERGE / DELETE / SET / … / FOREACH / LOAD CSV** 等做只读校验；属性更新接口对可写属性 **白名单**（见 [`store/falkordb_store.py`](../store/falkordb_store.py)）。
- **Wiki 任务锁：** [`wiki/task_store.py`](../wiki/task_store.py) 使用 Redis **`SET NX`** 获取锁，**UUID** 令牌 + **`EVAL` Lua** 脚本做**安全释放**，降低并发写 Wiki 任务的竞态风险。

---

## 10. 日志

- **库：** **structlog**（[`log.py`](../log.py)）。
- **级别：** `LOG_LEVEL`（Settings）。
- **格式：** **`LOG_FORMAT=console|json`**；`json` 适合接入 ELK / Loki / CloudWatch 等。

---

## 11. 快速配置片段

开发环境启用 LLM + Wiki MCP + 周期 Lint（示例）：

```bash
LLM__ENABLED=true
WIKI__MCP_SERVER_ENABLED=true
WIKI__LINT_SCHEDULER_ENABLED=true
WIKI__LINT_SCHEDULER_INTERVAL_HOURS=6
WIKI__CONFIDENCE_SCORING_ENABLED=true
WIKI__CONTRADICTION_DETECTION_ENABLED=true
```

生产环境最小集合（示例，请替换秘密）：

```bash
KB_ENV=production
REQUIRE_AUTH=true
API_TOKEN=replace-with-strong-secret
FALKORDB__HOST=falkordb.internal
FALKORDB_PASSWORD=replace-with-strong-secret
LOG_FORMAT=json
CORS_ORIGINS=https://app.example.com
```

---

**文档与代码一致性：** 若环境变量行为与本文不符，以 [`config.py`](../config.py)、[`main.py`](../main.py)、[`auth.py`](../auth.py) 及实际路由实现为准。
