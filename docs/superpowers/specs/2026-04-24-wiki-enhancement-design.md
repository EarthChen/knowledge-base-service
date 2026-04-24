# Wiki 生成增强设计方案

> 基于 DeepWiki 架构思路，为 knowledge-base-service 的 wiki 生成系统引入代码感知、RAG 检索和智能分层生成能力。

## 背景

当前 wiki 生成系统的 LLM 仅接收图谱元数据（name、signature、docstring 片段），不包含实际代码内容。DeepWiki 通过 RAG 检索源码片段实现了高质量文档生成。我们的优势在于已有图谱结构关系（调用链、继承、模块层级），增强方向是**在保留图谱优势的同时引入代码检索**。

### 现有基础设施

- FalkorDB 图谱已有 **67,627 个 Chunk 节点**，包含 `text`（代码文本，平均 733 bytes）、`file`/`start_line`/`end_line`、`parent_uid`/`parent_label`
- Chunk label 的**向量索引已创建**，但 0 个 Chunk 有 embedding
- 现有 `vector_search()` 和 `set_node_embedding()` 方法可直接复用
- FalkorDB 当前内存 1.30 GB，添加 embedding 预计增加 ~200 MB（768 维）

## 目标

1. 让 LLM 在生成 wiki 时能看到**实际代码内容**，而非仅看元数据
2. 通过 RAG 向量检索发现**跨文件语义关联**的代码
3. 根据实体重要度**智能分配生成资源**，避免简单 DTO 获得百科级文档
4. 支持**分层异步生成**，先推送基础版再逐步丰富
5. 支持**业务领域组织**，顶层按业务维度、下钻回代码结构

## 使用场景

- 新人入职：快速了解项目结构、核心模块职责、业务流程
- 代码审查/维护：深入理解每个类/方法的实现细节和调用关系
- 技术架构决策：高层面的设计模式、数据流、系统边界理解

## 实施方案：渐进增强（三阶段）

### Phase 1: 代码感知层（~2 天）

立刻让 LLM 看到实际代码，质量大幅提升。目录结构不变，仅增强页面内容。

#### 1.1 SourceCodeReader

精准代码读取组件。优先级递减策略：

1. **Chunk.text** — 通过 `parent_uid` 关联查找目标节点的 CHUNK 子节点，直接使用 text 属性（零 IO）
2. **文件读取** — 用节点的 `file` + `start_line`/`end_line` 属性从仓库路径读取（需配置 `WIKI__REPO_BASE_PATH`，仅在 Chunk.text 不可用时使用）
3. **降级为签名** — Chunk 和文件均不可访问时退回 signature + docstring（现有行为）

Token 预算控制（使用 `tiktoken` 或简单的 `len(text) / 4` 近似估算）：
- core 实体：最多 8000 tokens 代码
- standard 实体：最多 3000 tokens 代码
- skeleton 实体：仅签名，~500 tokens
- 超长函数自动截断：保留首部（~60%预算）+ 尾部（~40%预算），中间用 `... [truncated N lines] ...` 占位

```python
@dataclass
class CodeSnippet:
    source: str
    file_path: str
    start_line: int
    end_line: int
    origin: str  # "chunk" | "file" | "signature"

class SourceCodeReader:
    async def read(
        self,
        node: GraphNode,
        repo_path: str,
        budget_tokens: int = 3000,
    ) -> list[CodeSnippet]: ...
```

#### 1.2 ImportanceScorer

实体重要度评分，基于图谱数据自动计算，百分位排名分层。

评分公式：
```
score = (in_degree × 3) + (out_degree × 1) + (children_count × 2) + log2(code_lines + 1) × 2
if label == MODULE: score += 5
if label == CLASS and has_subclasses: score += 3
```

分层（百分位）：
- **core**（Top 20%）→ 百科模式，多层 LLM 生成
- **standard**（中间 50%）→ 标准模式，单次 LLM 生成
- **skeleton**（底部 30%）→ 骨架模式，模板填充，不调用 LLM

```python
class ImportanceTier(Enum):
    CORE = "core"
    STANDARD = "standard"
    SKELETON = "skeleton"

class ImportanceScorer:
    async def score_all(
        self,
        repository: str,
        nodes: list[GraphNode],
    ) -> dict[str, ImportanceTier]: ...
```

#### 1.3 PageData 扩展

```python
@dataclass
class PageData:
    # 现有字段
    node: GraphNode
    edges: list[GraphEdge]
    children: list[GraphNode]
    source_location: SourceLocation
    method_locations: list[SourceLocation]
    business_summary: str | None
    methods: list[GraphNode]
    # 新增
    code_snippets: list[CodeSnippet]
    importance_tier: ImportanceTier
    related_chunks: list[ChunkSnippet]  # Phase 2 填充
```

#### 1.4 增强 _entity_digest

在 LLM prompt 中嵌入实际代码：
- 当前：纯属性列表（name, signature, docstring 片段）
- 增强后：属性列表 + 关键代码片段（按 token 预算裁剪）

### Phase 2: RAG 检索层（~3 天）

为 Chunk 生成 embedding，实现语义检索。不改变目录结构，增强页面的跨文件关联。

#### 2.1 CodeChunkIndexer

为现有 67K Chunk 节点批量生成 embedding。

- 执行方式：独立批量任务（CLI 或 API 触发）
- 利用已有 `set_node_embedding()` 和 VECTOR INDEX
- 批量处理（batch=64），可中断续跑（跳过已有 embedding 的节点）
- 预计耗时 ~20 分钟

#### 2.2 ChunkRetriever

语义检索组件。

```python
@dataclass
class ChunkSnippet:
    text: str
    file_path: str
    score: float
    parent_name: str

class ChunkRetriever:
    async def retrieve(
        self,
        entity_name: str,
        entity_fqn: str,
        repository: str,
        k: int = 5,
        exclude_uids: set[str] | None = None,
    ) -> list[ChunkSnippet]: ...
```

检索策略（按实体类型）：
- MODULE：用模块名 + 描述检索 → 找到跨文件相关逻辑
- CLASS：用类名 + 方法签名检索 → 找到使用示例和调用方
- FUNCTION：用函数名 + docstring 检索 → 找到相关函数和测试

去重：排除已在 code_snippets（Phase 1 精准代码）中的内容。

#### 2.3 EnrichedContextAssembler

统一上下文组装。

```python
@dataclass
class EnrichedContext:
    graph_data: PageData
    code_snippets: list[CodeSnippet]
    related_chunks: list[ChunkSnippet]
    related_docs: list[str]
    importance: ImportanceTier

class EnrichedContextAssembler:
    async def assemble(
        self,
        repository: str,
        node: GraphNode,
        tier: ImportanceTier,
        repo_path: str | None = None,
    ) -> EnrichedContext: ...
```

合并四路数据：
1. 图谱结构数据（WikiDataCollector）
2. 精准代码（SourceCodeReader）
3. 语义关联代码（ChunkRetriever）
4. 相关文档（doc_wiki_fusion）

### Phase 3: 百科分层生成（~3 天）

引入多层 Prompt 模板、异步丰富管道和业务领域组织。

#### 3.1 TieredComposer

增强 WikiComposer，根据 importance_tier 选择不同生成策略。

**基础层（同步）**— 所有非 skeleton 实体：
- 概述 + 职责描述
- 核心方法/组件列表
- 关系图（Mermaid）
- 关键代码引用

**丰富层（异步 Round 1）**— 仅 core + standard 实体：
- 业务流程分析
- 设计模式识别
- 调用链路追踪
- 关键决策点解释

**百科层（异步 Round 2）**— 仅 core 实体：
- 使用示例
- 常见问题（FAQ）
- 变更历史注意事项
- 性能考虑

异步丰富实现机制：
1. 同步生成基础层 WikiPage 并立即返回/推送给前端
2. 后台启动异步任务，每层独立调用 LLM，prompt 中包含已有基础层内容作为上下文
3. LLM 生成新 section 后，追加（append）到 WikiPage.content 末尾
4. 更新 WikiPage 的 `generated_at` 和新增 `enrichment_level` 属性（base / enriched / encyclopedia）
5. 前端通过轮询 WikiPage 的 `enrichment_level` 或 SSE 事件感知内容更新

#### 3.2 BusinessDomainPlanner

业务领域识别与文档目录重组。

```python
class BusinessDomainPlanner:
    async def classify(
        self,
        repository: str,
        modules: list[GraphNode],
    ) -> dict[str, list[str]]: ...
```

两遍过程：
1. **第一遍（无需 LLM）**：扫描代码结构，生成骨架页面
2. **第二遍（需要 LLM）**：一次 LLM 调用，将模块映射到业务领域

混合模式文档结构：
```
📖 项目概览
├── 📂 用户管理（业务领域）        ← LLM 识别
│   ├── 📄 领域概述                 ← 跨模块业务流程
│   ├── 📦 user-service/            ← 代码模块
│   │   ├── UserController          ← core → 百科
│   │   ├── UserService             ← core → 百科
│   │   └── UserDTO                 ← skeleton → 骨架
│   └── 📦 auth-module/
├── 📂 订单处理（业务领域）
└── 📂 基础设施（技术通用）
```

业务领域概述页包含：宏观业务流程、模块间协作关系、数据流图。
代码实体页包含：方法级业务逻辑、设计决策、异常处理逻辑。

无法归类的模块（如纯工具库、配置模块）统一归入"基础设施"领域。BusinessDomainPlanner 的 LLM prompt 显式要求输出一个 `__infrastructure__` 兜底分类。

#### 3.3 无 LLM 降级

当 LLM 不可用时：
- 所有实体走骨架模式：代码片段 + 关系图 + 签名列表 + 调用关系表
- 不生成业务领域概述页
- 等效于增强版 Javadoc/Doxygen 输出

## 配置

```env
# Phase 1
WIKI__REPO_BASE_PATH=/path/to/repos
WIKI__CODE_TOKEN_BUDGET=3000
WIKI__IMPORTANCE_CORE_PERCENTILE=80
WIKI__IMPORTANCE_STANDARD_PERCENTILE=30

# Phase 2
WIKI__CHUNK_EMBEDDING_BATCH_SIZE=64

# Phase 3
WIKI__ENRICHMENT_ENABLED=true
WIKI__BUSINESS_DOMAIN_ENABLED=false
```

## 向后兼容

- `mode=structure` 行为不变
- `scope="module:xxx"` 保持代码结构目录
- `scope="repo"` 可选启用 BusinessDomainPlanner
- 现有 API 参数不变，新功能通过环境变量控制

## 内存影响

- 为 67K Chunk 添加 768 维 embedding：~200 MB
- 当前 FalkorDB 1.30 GB → 预计 1.50 GB
- 在开发机可承受范围内

## 完整数据流

```
请求 → WikiStructurePlanner.plan()
     → ImportanceScorer.score_all()
     → 分流: core / standard / skeleton
     
skeleton → _tier3_skeleton (模板) → WikiPage

core/standard → EnrichedContextAssembler.assemble()
    ├── WikiDataCollector (图谱结构)
    ├── SourceCodeReader (精准代码)
    ├── ChunkRetriever (语义代码) [Phase 2]
    └── doc_wiki_fusion (相关文档)
    → EnrichedContext
    → TieredComposer
    ├── 基础层 (同步) → WikiPage v1
    ├── 丰富层 (异步) → WikiPage v2 [Phase 3, core+standard]
    └── 百科层 (异步) → WikiPage v3 [Phase 3, core only]

[Phase 3] BusinessDomainPlanner.classify()
    → 领域概述页 + 导航重组
```
