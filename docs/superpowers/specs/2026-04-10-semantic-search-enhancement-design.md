# Knowledge Base 语义搜索增强设计

> **Status**: Approved  
> **Date**: 2026-04-10  
> **Author**: AI Architect  
> **Scope**: knowledge-base-service + acp-gateway (proxy layer only)

## 1. 背景与目标

### 1.1 现状问题

当前 knowledge-base-service 的搜索能力存在以下局限：

- **代码向量缺乏业务语义**: Embedding 输入为 `Name + Signature + Docstring + Code`，无法将"用户登录"匹配到 `authenticate()` 函数
- **Class 节点嵌入薄弱**: 仅 name + docstring，缺少类体、公共 API 摘要
- **Module 节点无向量索引**: 仅支持关键词和图查询
- **混合搜索无重排序**: 关键词 + 语义向量简单拼接，无 reranking
- **缺少业务流程关联**: 无法回答"下单流程涉及哪些代码"这类结构化问题
- **缺少领域知识**: 无法理解项目特有术语（如"私信"="IM消息"）

### 1.2 目标

构建多层次业务语义搜索体系：

1. **代码功能摘要**: LLM 为 Function/Class 生成业务语义描述
2. **业务流程映射**: 建立"业务流程 → 代码实现"关联图谱
3. **领域知识注入**: 项目特有术语/概念注入搜索和索引
4. **搜索质量提升**: Cross-encoder reranking + 6 类向量搜索
5. **Dashboard LLM 增强搜索**: 为人类用户提供自然语言深度搜索

### 1.3 消费端分层原则

| 消费端 | LLM 增强 | 原因 |
|--------|---------|------|
| Agent (MCP) | 不需要 | Agent 自带 LLM，可自行分解查询、多次调用工具 |
| Dashboard 用户 | 需要 | 人类用户需要系统理解自然语言、编排搜索、汇总结果 |
| CI/Review Agent | 不需要 | 通过 gateway proxy 调用 MCP 工具 |

## 2. 架构总览

```
┌─────────────────┐    ┌──────────────────────┐
│  Agent (MCP)    │    │  Dashboard 用户       │
│  自带 LLM 能力   │    │  需要 LLM 辅助理解    │
└────────┬────────┘    └──────────┬───────────┘
         │                       │
   MCP 工具调用              HTTP API
   (无 LLM 层)          (/api/v1/deep-search)
         │                       │
         │              ┌────────┴────────────┐
         │              │ LLM 增强搜索引擎      │
         │              │ • 查询理解            │
         │              │ • 多轮搜索编排         │
         │              │ • 结果汇总报告         │
         │              └────────┬────────────┘
         │                       │
    ┌────┴───────────────────────┴────┐
    │     KB Service 搜索引擎          │
    │  • enriched vectors (6 类)      │
    │  • cross-encoder reranking     │
    │  • 业务流程图谱查询              │
    │  • 混合搜索                     │
    └─────────────┬──────────────────┘
                  │
       FalkorDB (扩展 Schema)
       + BusinessFlow, BusinessConcept
       + IMPLEMENTS, RELATES_TO 边
```

## 3. Schema 扩展

### 3.1 新增节点类型

**BusinessFlow（业务流程）**

| 属性 | 类型 | 说明 |
|------|------|------|
| name | str | 流程名称（如"用户下单"） |
| description | str | 流程详细描述 |
| category | str | 分类（如"交易"、"用户"、"内容"） |
| source | str | 来源：`auto` / `doc` / `manual` |
| confidence_score | float | 置信度（0-1），用于过滤低质量推断 |
| embedding | vector[1024] | 语义向量 |

**BusinessConcept（业务概念）**

| 属性 | 类型 | 说明 |
|------|------|------|
| name | str | 概念名称（如"私信"） |
| description | str | 概念描述 |
| aliases | list[str] | 别名（如 `["IM消息", "direct_message"]`） |
| category | str | 分类 |
| source | str | 来源 |
| embedding | vector[1024] | 语义向量 |

### 3.2 现有节点扩展

| 节点 | 新增属性 | 说明 |
|------|---------|------|
| Function | `business_summary` (str) | LLM 生成的业务语义描述（≤200 字） |
| Class | `business_summary` (str) | LLM 生成的业务语义描述（≤200 字） |
| Module | `description` (str) + `embedding` (vector) | 模块级业务描述，新增向量搜索能力 |

### 3.3 新增边类型

| 边 | Source → Target | 属性 | 语义 |
|----|----------------|------|------|
| IMPLEMENTS | BusinessFlow → Function/Class | `role` (str), `step_order` (int) | 此流程由这些代码实现 |
| RELATES_TO | BusinessConcept → Function/Class/Module/Document | `relevance_score` (float) | 此概念与这些实体相关 |
| PART_OF | BusinessFlow → BusinessFlow | `step_order` (int) | 子流程属于父流程 |
| CONCEPT_IN | BusinessConcept → BusinessFlow | — | 此概念属于此流程 |

### 3.4 向量索引配置

从 3 个扩展到 6 个：

| 索引 | 状态 |
|------|------|
| Function(embedding) | 现有 |
| Class(embedding) | 现有 |
| Document(embedding) | 现有 |
| BusinessFlow(embedding) | **新增** |
| BusinessConcept(embedding) | **新增** |
| Module(embedding) | **新增** |

全部使用 cosine 相似度，维度 1024（bge-m3）。

## 4. LLM 兼容层

### 4.1 设计原则

acp-gateway 已提供 OpenAI 兼容 API（`/api/v1/openai/*`），因此两种接入方式统一为基于 OpenAI 协议的 Provider，通过 `base_url` 切换。

### 4.2 接口定义

```python
class LLMProvider(Protocol):
    async def complete(self, messages: list[dict], **kwargs) -> str: ...
    async def complete_json(self, messages: list[dict], schema: dict, **kwargs) -> dict: ...
```

### 4.3 配置

```yaml
llm:
  base_url: "https://api.openai.com/v1"  # 或 acp-gateway URL
  api_key: "sk-xxx"                       # 或 business token
  model: "gpt-4o-mini"                    # enrichment 用的模型
  deep_search_model: "gpt-4o"             # deep_search 可用更强模型
  max_concurrent: 10
  timeout: 30
  retry_count: 3
```

### 4.4 acp-gateway 任务复用

知识库侧通过 **`LLM__GATEWAY__ENABLED=true`** 与 `GatewayConfig`（`ws_url`、`http_url`、`idle_timeout`）显式启用 Gateway 反馈模式；**不再**根据 `base_url` 的 URL 模式推断是否走 Gateway。

- **`RepoTaskManager`**：内部 `_tasks` 使用前缀区分用途——索引 enrichment 键为 **`enrich:{repo_name}`**（`repo_name` 为索引进程从目录路径取的最后一段）；Dashboard **`DeepSearchEngine`** 在 Gateway 启用且请求带 `business_id` 时，对 plan/synthesize 调用 **`prompt("search:{tenant_id}", ...)`**，每租户一个 **`_RepoTask`**。全量索引使用 **`enrich_stream`** 与解析流水线并发；增量索引使用 **`enrich`**（预填队列后同样走反馈循环）。
- **Standby 与清理**：每轮结束后向网关发送待命指令；后台 **`_cleanup_loop`** 定期扫描，**空闲超过 `idle_timeout`（默认 3600s，最小 60）** 则关闭连接。
- **`GatewayTaskClient`**：**`_run_feedback_loop`** 为 `enrich_batch` 与 `enrich_stream` 的共用核心；每轮最多 **`_MAX_ENTITIES_PER_ROUND`（50）** 个实体；队列批大小 **`_ENRICH_BATCH_SIZE`（50）**（固定常量，原 `enrichment_batch_size` 配置已移除）。
- **未启用 Gateway**（`LLM__GATEWAY__ENABLED=false`）：enrichment 走 `LLMProvider` HTTP；deep_search 全程 `LLMProvider`。
- **deep_search 与 Gateway**：启用 Gateway 且存在 `tenant_id` 时优先经 **`RepoTaskManager.prompt`**；解析失败或异常时**回退**到 `LLMProvider.complete_json`。

### 4.5 并发和容错

- `asyncio.Semaphore` 控制并发数
- 指数退避重试（tenacity 库）
- 速率限制（token bucket）
- 失败时记录 warning 并跳过，不阻塞整体流水线

## 5. Enrichment Pipeline

三个子管道，按依赖顺序执行。

### 5.1 子管道 A: 代码功能摘要生成（先行）

**输入**: Function/Class 节点的 name, signature, docstring, code_snippet, file  
**输出**: `business_summary` 属性  

**实现说明（与代码对齐）**：Gateway 模式下提示词以 `gateway_client._ENRICHMENT_PROMPT` 为准（中文业务摘要 + JSON 数组输出 + `request_feedback` 分批）。全量索引时解析与 enrichment **并发**：实体经 **`asyncio.Queue`** 流式送入 `enrich_stream`；队列单批缓冲 **`_ENRICH_BATCH_SIZE`（50）**，反馈循环每轮最多 **`_MAX_ENTITIES_PER_ROUND`（50）** 个实体。

**Prompt 模板**:

```
你是一个代码分析专家。请为以下代码生成一个简洁的业务语义描述。
要求：
1. 用自然语言描述这个函数/类的业务用途（而非技术实现）
2. 包含它属于哪个业务领域
3. 它在业务流程中扮演的角色
4. 不超过 200 字

代码信息:
文件: {file}
名称: {name}
签名: {signature}
文档: {docstring}
代码片段: {code_snippet[:1000]}
```

**批处理策略**:
- Gateway：**反馈循环**分批，而非按文件单批；全量与解析流水线重叠
- 直连 LLM 时仍可按 `CodeSummaryEnricher` / `LLMProvider` 策略执行
- 失败时记录 warning 并跳过等策略见实现

**增量更新**: 与 git-diff 管道对齐，只对变更文件收集实体后 `_enrich_from_items` 批量 enrich。

### 5.2 子管道 B: 业务流程推断（依赖 A）

**输入**: CALLS 调用链 + 每个函数的 business_summary  
**输出**: BusinessFlow 节点 + IMPLEMENTS 边 + PART_OF 子流程关系

**流程**:
1. 识别"入口点"，按以下优先级：
   - **强入口点（注解/装饰器识别）**：
     - HTTP handler：`@RequestMapping`、`@GetMapping`、`@PostMapping`、`@app.route` 等
     - MOA RPC Provider：类上标注 `@MoaProvider` 注解的公开方法（内部 RPC 框架入口）
     - Kafka Consumer：`@KafkaListener`、`@KafkaHandler` 或其他消息消费入口
     - 定时任务：`@Scheduled`、`@Cron` 等
   - **弱入口点（图结构推断）**：同时满足 (a) 没有被其他函数 CALLS（无入边），且 (b) 自身有 CALLS 出边的函数（排除孤立工具函数）
   - 强入口点优先于弱入口点；MOA Consumer（`@MoaConsumer` 注解的调用点）不视为入口点，而是作为跨服务 CALLS 的起点（调用外部 RPC 服务）
2. 从入口点往下遍历 CALLS 链（深度 3-5）
3. 将调用链 + business_summary 发送给 LLM，推断业务流程
4. LLM 输出结构化 JSON：流程名称、描述、每个函数的角色和顺序、子流程
5. 创建 BusinessFlow 节点和 IMPLEMENTS 边

**去重策略**: LLM 输出的流程名称通过向量相似度去重（相似度 > 0.9 视为相同流程，合并）。

**Prompt 模板**:

```
以下是一条代码调用链。请分析它实现的业务流程。

调用链:
{caller_name} ({caller_summary})
  → {callee1_name} ({callee1_summary})
  → {callee2_name} ({callee2_summary})
  ...

请输出 JSON:
{
  "flow_name": "业务流程名称",
  "description": "流程描述",
  "category": "分类",
  "steps": [
    {"function": "函数名", "role": "entry_point|processor|validator|notifier|...", "order": 1}
  ],
  "sub_flows": [
    {"name": "子流程名", "description": "描述", "steps": [...]}
  ]
}
```

### 5.3 子管道 C: 文档概念提取（与 A 并行）

**输入**: Document 节点的内容  
**输出**: BusinessConcept 节点 + RELATES_TO 边 + CONCEPT_IN 边

**流程**:
1. 读取已索引的 Document 节点内容
2. 用 LLM 提取业务概念和流程描述
3. 将提取的概念通过名称匹配 + 向量相似度关联到代码节点
4. 创建 BusinessConcept 节点和关联边

### 5.4 整体流水线顺序

```
A (代码摘要)  ─────────────┐
                           ├─→ B (业务流程推断) ─→ 重新生成 Embeddings
C (文档概念提取) ──────────┘
```

C 的提取结果（业务概念列表）会作为 B 的辅助上下文：当 B 推断业务流程时，可引用已知的业务概念来提高命名一致性和准确性。

### 5.5 Embedding 生成变更

`_format_code_text` 函数修改为优先使用 `business_summary`：

```python
def _format_code_text(name, signature, docstring, code_snippet, business_summary=""):
    parts = []
    if business_summary:
        parts.append(f"Business: {business_summary}")
    if name:
        parts.append(f"Name: {name}")
    if signature:
        parts.append(f"Signature: {signature}")
    if docstring and not business_summary:
        parts.append(f"Description: {docstring[:500]}")
    if code_snippet:
        parts.append(f"Code: {code_snippet[:1000]}")
    return "\n".join(parts)
```

## 6. 增强搜索引擎

### 6.1 向量搜索扩展

`SemanticQueryService.search_all` 从 3 类扩展到 6 类（Function, Class, Document + BusinessFlow, BusinessConcept, Module），全部并行执行。

### 6.2 Cross-Encoder Reranking

- **模型**: `BAAI/bge-reranker-v2-m3`（与 bge-m3 同系列）
- **流程**: 向量搜索取 top-20~30 → query + 候选配对 → cross-encoder 打分 → 重排 → 取 top-k
- **延迟**: ~50-100ms，对所有消费端生效（不是 LLM，是轻量级模型）

### 6.3 业务流程图查询

新增到 `GraphQueryService`：

| 方法 | Cypher 模板 | 功能 |
|------|------------|------|
| `find_business_flow(name)` | `MATCH (bf:BusinessFlow)-[:IMPLEMENTS]->(f) WHERE bf.name CONTAINS $name` | 查找流程及关联代码 |
| `find_flows_for_function(name)` | `MATCH (f:Function)<-[:IMPLEMENTS]-(bf:BusinessFlow) WHERE f.name = $name` | 反向查询函数所属流程 |
| `find_related_concepts(name)` | `MATCH (bc:BusinessConcept)-[:RELATES_TO]->(n) WHERE n.name = $name` | 查询相关业务概念 |
| `explore_business_domain(category)` | `MATCH (bf:BusinessFlow) WHERE bf.category = $category` | 浏览业务领域 |
| `find_flow_dependencies(flow_name)` | `MATCH path=(bf:BusinessFlow)-[:PART_OF*1..3]->(parent)` | 流程层级关系 |

### 6.4 增强 Hybrid Search 流程

```
keyword_search ──┐
                 ├→ fusion ──→ cross-encoder rerank ──→ graph_expansion ──→ 结果
vector_search ───┘                                      (+ 业务流程上下文)
(6 类并行)
```

变化点：
- fusion 后增加 reranking 步骤
- graph_expansion 阶段新增：命中 Function → 查找所属 BusinessFlow，注入 `business_context`
- 返回结果包含 `business_flows` 和 `business_concepts` 字段

## 7. MCP 工具集（Agent 使用，无 LLM 层）

### 7.1 现有工具增强

**rag_query** — 混合搜索（增强版）

```json
{
  "name": "rag_query",
  "inputSchema": {
    "properties": {
      "query": {"type": "string", "description": "搜索查询"},
      "k": {"type": "integer", "default": 5},
      "expand_depth": {"type": "integer", "default": 2},
      "include_business_context": {"type": "boolean", "default": true}
    },
    "required": ["query"]
  }
}
```

返回新增字段：`business_flows`, `business_concepts`。

**rag_graph** — 图查询（扩展）

新增 `query_type` 选项：
- `business_flow`: 查询业务流程
- `flows_for_function`: 查询函数所属流程
- `related_concepts`: 查询相关概念
- `explore_domain`: 浏览业务领域
- `flow_dependencies`: 流程依赖关系

### 7.2 新增工具

**rag_business_search** — 业务语义专用搜索

```json
{
  "name": "rag_business_search",
  "description": "搜索业务流程和业务概念，支持自然语言查询",
  "inputSchema": {
    "properties": {
      "query": {"type": "string", "description": "业务语义查询"},
      "search_type": {"type": "string", "enum": ["flow", "concept", "all"], "default": "all"},
      "k": {"type": "integer", "default": 5},
      "include_code": {"type": "boolean", "default": true}
    },
    "required": ["query"]
  }
}
```

## 8. Dashboard LLM 增强搜索

### 8.1 定位

位于 KB service 内部，专门服务 Dashboard 人类用户。Agent 不使用此接口。

### 8.2 API

```
POST /api/v1/deep-search
{
  "query": "支付回调失败可能影响哪些业务流程？",
  "max_iterations": 3,
  "include_code": true
}
```

**Response**:

```json
{
  "analysis": "综合分析文本...",
  "business_flows": [...],
  "code_locations": [...],
  "search_trace": [...]
}
```

### 8.3 内部流程

```
Step 1: LLM 分析查询意图 → 生成搜索策略（子查询列表）
Step 2: 内部调用 hybrid_search + graph_query 执行子查询
Step 3: LLM 评估结果充分性（判断标准：查询意图中的所有实体是否都有对应的搜索结果，且结果包含代码位置信息）
  ├── 不充分 → 识别缺失的实体或关联，生成针对性追加查询 → 回到 Step 2（最多 max_iterations 次）
  └── 充分 → Step 4
Step 4: LLM 汇总生成结构化分析报告
```

### 8.4 LLM 配置

复用 LLM 兼容层的 `deep_search_model` 配置，可使用比 enrichment 更强的模型。

## 9. acp-gateway 变更（最小化）

### 9.1 rag_router 扩展

在现有 `rag_router.py` 中新增 deep-search 代理路由：

```python
@router.post("/deep-search")
async def deep_search(request: DeepSearchRequest, ...):
    # 代理转发到 KB service 的 /api/v1/deep-search
    ...
```

### 9.2 RagPromptInjector 更新

更新 Agent 提示中的工具说明，包含 `rag_business_search` 工具的使用说明。

## 10. 分阶段实施计划

### Phase 1: LLM 基础 + 代码 Enrichment（立竿见影）

**目标**: 提升现有搜索质量，无需改变搜索 API  
**预计工期**: 3-5 天

- [ ] LLM 兼容层实现（LLMProvider + 配置）
- [ ] 代码摘要生成器（Code Summary Enricher）
- [ ] Function/Class 节点扩展 business_summary 属性
- [ ] `_format_code_text` 增强，优先使用 business_summary
- [ ] 增量索引集成：git-diff 触发时自动重新 enrich 变更的函数
- [ ] 全量 enrichment 命令（CLI / API）

**交付价值**: 搜索"用户登录"能匹配到 `authenticate()` 函数。

### Phase 2: 业务语义图谱层（核心能力）

**目标**: 增加业务流程和概念的结构化查询  
**依赖**: Phase 1  
**预计工期**: 5-7 天

- [ ] Schema 扩展（BusinessFlow, BusinessConcept, 新边类型）
- [ ] 向量索引扩展（3 → 6 个）
- [ ] 业务流程推断器（Business Flow Inferencer）
- [ ] 文档概念提取器（Document Concept Extractor）
- [ ] 业务流程图查询（GraphQueryService 扩展）
- [ ] Module 节点向量索引支持
- [ ] rag_business_search MCP 工具

**交付价值**: 可回答"下单流程涉及哪些代码"。

### Phase 3: 搜索引擎增强（质量跳跃）

**目标**: 搜索结果精准度大幅提升  
**依赖**: Phase 2  
**预计工期**: 4-6 天

- [ ] Cross-encoder reranking 模块（bge-reranker-v2-m3）
- [ ] Hybrid search 扩展（6 类向量搜索 + 业务流程上下文）
- [ ] rag_query 增强（返回业务流程/概念关联）
- [ ] rag_graph 扩展（新增业务流程查询类型）
- [ ] Dashboard 搜索 UI 更新（展示业务流程关联）
- [ ] RagPromptInjector 更新

**交付价值**: 搜索精度显著提升，结果包含业务上下文。

### Phase 4: Dashboard LLM 增强搜索（顶层能力）

**目标**: 为 Dashboard 用户提供深度搜索  
**依赖**: Phase 3  
**预计工期**: 4-6 天

- [ ] DeepSearchEngine 实现（查询理解 → 搜索编排 → 结果汇总）
- [ ] /api/v1/deep-search HTTP API
- [ ] 查询跟踪和可观测性（search_trace）
- [ ] Dashboard deep-search UI 组件
- [ ] acp-gateway rag_router 新增 deep-search 代理

**交付价值**: Dashboard 用户可用自然语言问"支付回调失败影响哪些业务"。

### 总工期估算: 16-24 天

每个 Phase 独立交付价值，可在任意 Phase 后暂停。

## 11. 成本估算

### LLM Enrichment 成本（索引时，一次性）

假设中型代码库 20,000 个函数/类，GPT-4o-mini（$0.15/1M input, $0.6/1M output）：

| 子管道 | 预计成本 |
|--------|---------|
| A: 代码摘要（20K 实体） | ~$2.7 |
| B: 业务流程推断（~200 调用链） | ~$0.1 |
| C: 文档概念提取（~50 文档） | ~$0.02 |
| **全量总计** | **~$3** |

### 增量更新成本

每次 git push 改动 ~50 个函数: ~$0.01

### 查询时成本

- Cross-encoder reranking: 无 LLM 成本（本地模型）
- Dashboard deep_search: ~$0.002/次（2-3 次 LLM 调用）
