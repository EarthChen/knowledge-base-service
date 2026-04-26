# Wiki 树状知识库架构设计方案

> 在 [2026-04-24-wiki-enhancement-design.md](./2026-04-24-wiki-enhancement-design.md) 基础上，引入跨仓库业务级 Wiki、树状结构、交叉引用、导出推送等能力，使 Wiki 从单仓库文档升级为业务领域知识库。

## 背景与动机

### 现有提案（Phase 1-3）的局限性

[wiki-enhancement-design](./2026-04-24-wiki-enhancement-design.md) 定义了代码感知层、RAG 检索层和百科分层生成，但存在以下核心缺陷：

1. **单仓库孤岛**: 所有组件（SourceCodeReader、ImportanceScorer、ChunkRetriever、BusinessDomainPlanner）以单个 `repository` 为边界。微服务架构下，一个业务流（如用户注册）往往跨 user-service、auth-service、notification-service 多个仓库，单仓库 wiki 无法表达全局视图。
2. **无树状结构**: WikiPage 是平坦列表，没有层级导航。BusinessDomainPlanner 的"混合模式文档结构"仅是概念示意，缺少对应的数据模型。
3. **无交叉引用**: 页面之间没有链接关系，无法形成知识网络。当 UserController 调用 OrderService 时，各自的 wiki 页面完全独立。
4. **纯自动无人工干预**: 缺少人工编辑、标注、反馈机制，LLM 生成内容往往不够准确。
5. **无版本管理**: 重新生成后旧版本丢失，无法追踪变化。
6. **ImportanceScorer 片面**: 纯基于图谱结构评分，缺少变更频率、测试覆盖率等业务因素。
7. **无质量保障**: 缺少自动的一致性检查和过时检测。
8. **无导出能力**: 知识锁定在 FalkorDB 中，无法推送到 Git 仓库或导出为静态文档站。

### 竞品分析（code-review-graph）

| 维度 | knowledge-base-service | code-review-graph |
|------|----------------------|-------------------|
| 定位 | 企业级集中式知识库服务 | 本地 AI 编码助手图谱 |
| 存储 | FalkorDB (图数据库) | SQLite (本地文件) |
| 语言 | 5 种 | 23 种 + Jupyter |
| MCP 工具 | 15 个 | 28 个 |
| Wiki | 分层 LLM 生成, 业务领域规划 | 社区结构生成 markdown |
| 多仓库 | 同图谱多 repo + CrossRepoEnricher | 注册表 + 守护进程 + 跨仓搜索 |
| 检索 | 关键词 + 向量 + BM25 + RRF + 重排序 | FTS5 + sentence-transformers |

**可借鉴的 CRG 特性：**

1. **Obsidian Wikilinks**: Wiki 内容中自动插入 `[[PagePath]]` 交叉引用，持久化为图谱边，前端渲染为超链接。
2. **Memory Loop**: 用户 Q&A 和编辑结果作为"知识注入"持久化，下次重新生成时作为 LLM 上下文，知识随使用积累。
3. **Graph Diff**: Wiki 重新生成时与旧版对比，突出变更部分，支持审计和变更评审。
4. **Suggested Questions**: 基于图分析（bridges, hubs, surprises）自动生成探索问题，引导用户深入理解。
5. **Knowledge Gap Analysis**: Wiki 覆盖率报告，识别高调用度但文档薄弱的实体（高风险盲区）。
6. **Multi-repo Daemon**: 任何 repo 变更自动触发受影响 wiki 页面的增量更新。

## 目标

1. 支持**业务级 Wiki 空间**——一个 business 下所有仓库的知识统一组织
2. 提供**树状层级结构**——WikiSpace → WikiSection → WikiPage 多级嵌套
3. 实现**交叉引用网络**——页面间自动建立引用关系，支持跨仓库、跨视角引用
4. 支持**双视角导航**——业务领域树（面向业务理解）和代码结构树（面向开发维护）
5. 支持**导出和 Git 推送**——markdown 文件导出、自动推送到 GitHub/GitLab、Obsidian vault
6. 支持**人工知识注入**——人工编辑与自动生成内容的融合
7. 为 **Agent 提供高效的知识遍历 API**——让 Agent 能快速理解业务上下文

## 使用场景

- **新人入职**: 从业务域树顶层开始，逐级下钻理解业务全貌
- **跨仓库需求开发**: Agent 搜索业务流 wiki → 理解跨仓库调用链 → 精准修改
- **架构评审**: 通过交叉引用和探索问题发现过度耦合和架构问题
- **团队知识沉淀**: 人工标注 + 自动生成，wiki 随使用越来越准确
- **文档站部署**: 导出为 MkDocs/Obsidian 格式，部署为团队内部文档站

## 数据模型设计

### path 语义与命名规则

`WikiPage.path` 是页面的**全局唯一标识符**，基于**业务域树**生成。代码结构树中的层级通过 `HAS_CHILD(view_type='code_structure')` 边动态计算，不单独存储 path。

**path 生成规则：**
- 格式: `/{业务领域}/{仓库名}/{实体名}` 或 `/{业务领域}/{子主题}/{实体名}`
- 同名实体用仓库名区分: `/用户管理/user-service/UserService` vs `/用户管理/auth-service/UserService`
- 领域概述页: `/{业务领域}/_overview`
- 业务流页面: `/{业务领域}/{流程名}/_flow`

**命名冲突解决：** 当多个仓库有同名类时，path 中必须包含仓库名作为中间层级。`WikiTreeBuilder` 在构建树时自动检测冲突并插入仓库名层级。

### 新增节点类型

```python
@dataclass
class WikiSpaceNode:
    """业务级 Wiki 根节点，一个 business 一个"""
    uid: str
    business_id: str
    title: str
    description: str
    created_at: str
    updated_at: str

@dataclass
class WikiSectionNode:
    """可嵌套的分组节点，表达树状层级"""
    uid: str
    title: str
    description: str
    icon: str | None         # emoji/图标
    section_type: str        # "business_domain" | "code_module" | "topic"
    sort_order: int
    auto_generated: bool     # 是否由 BusinessDomainPlanner 自动创建
```

### WikiPage 节点扩展

```python
@dataclass
class WikiPageNode:
    # === 现有字段 ===
    uid: str
    title: str
    content: str             # markdown 内容
    page_type: str           # "entity" | "domain_overview" | "business_flow" | "index"
    repository: str
    generated_at: str
    enrichment_level: str    # "base" | "enriched" | "encyclopedia"

    # === 新增字段 ===
    path: str                # 树状路径, 如 "/用户管理/user-service/UserController"
    repositories: list[str]  # 涉及的仓库列表（跨仓库页面会有多个）
    version: int             # 版本号，每次重新生成递增
    importance_tier: str     # "core" | "standard" | "skeleton"
    manual_sections: str     # JSON, 存储人工编辑的内容段
    content_hash: str        # 内容 hash, 用于变更检测
    previous_content_hash: str | None  # 上一版本的 content_hash, 用于变更检测
```

### 新增关系类型

```python
# 树状结构（带视角标签）
class HasChildEdge:
    """WikiSpace/WikiSection → WikiSection/WikiPage"""
    view_type: str      # "business_domain" | "code_structure"
    sort_order: int

# 交叉引用（全局的、跨视角的）
class WikiReferencesEdge:
    """WikiPage ↔ WikiPage，不属于任何树，是独立的引用关系"""
    relation_type: str  # "calls" | "inherits" | "cross_repo" | "imports" |
                        # "semantic" | "business_flow" | "manual"
    context: str        # 引用上下文描述
    auto_generated: bool
    confidence: float   # 自动生成的置信度

# 源码关联
class SourceEntityEdge:
    """WikiPage → Function/Class/Module"""
    pass
```

### 图谱 Schema 变更

```cypher
-- 新增节点标签
CREATE INDEX ON :WikiSpace(uid)
CREATE INDEX ON :WikiSpace(business_id)
CREATE INDEX ON :WikiSection(uid)
CREATE INDEX ON :WikiPage(path)
CREATE INDEX ON :WikiPage(version)

-- 新增关系类型
-- (:WikiSpace)-[:HAS_CHILD {view_type, sort_order}]->(:WikiSection)
-- (:WikiSection)-[:HAS_CHILD {view_type, sort_order}]->(:WikiSection|:WikiPage)
-- (:WikiPage)-[:WIKI_REFERENCES {relation_type, context, auto_generated}]->(:WikiPage)
-- (:WikiPage)-[:SOURCE_ENTITY]->(:Function|:Class|:Module)
```

## 双视角导航

同一个 WikiPage 通过不同 `view_type` 的 `HAS_CHILD` 边出现在不同的树中。**交叉引用（WIKI_REFERENCES）是全局的、跨视角的，不受树结构限制。**

### 业务领域树（面向业务理解）

按"用户能做什么"组织，一个领域可能横跨多个仓库。适合产品经理、新入职员工、Agent 理解全局业务。

```
📖 XX 业务线知识库 (WikiSpace)
├── 📂 用户管理 (WikiSection)
│   ├── 📄 领域总览 (WikiPage — 聚合 user-service + auth-service 描述)
│   ├── 📂 用户注册流程 (WikiSection)
│   │   ├── 📄 注册表单校验 (WikiPage → user-service/UserValidator)
│   │   ├── 📄 账号创建逻辑 (WikiPage → user-service/UserService.register)
│   │   ├── 📄 验证码发送 (WikiPage → notification-service/SmsService)
│   │   └── 📄 流程时序图 (WikiPage — 跨 3 个仓库的调用链)
│   ├── 📂 用户认证机制 (WikiSection)
│   │   ├── 📄 JWT Token 签发 (WikiPage → auth-service/TokenProvider)
│   │   └── 📄 OAuth2 对接 (WikiPage → auth-service/OAuth2Handler)
│   └── 📂 权限模型 (WikiSection)
├── 📂 订单处理 (WikiSection)
│   ├── 📄 领域总览
│   ├── 📂 下单流程
│   └── 📂 退款机制
└── 📂 基础设施 (WikiSection — 兜底)
    ├── 📄 通用工具库
    └── 📄 消息队列配置
```

### 代码结构树（面向开发维护）

按仓库 → 包/模块 → 类/方法组织，与代码目录一一对应。适合开发者日常编码、Code Review。

```
📖 XX 业务线知识库 (WikiSpace)
├── 📦 user-service (WikiSection)
│   ├── 📄 仓库概览 (WikiPage)
│   ├── 📂 controller/ (WikiSection)
│   │   ├── 📄 UserController (WikiPage — core, 百科级)
│   │   └── 📄 AdminController (WikiPage — standard)
│   ├── 📂 service/ (WikiSection)
│   │   └── 📄 UserService (WikiPage — core, 百科级)
│   └── 📂 model/ (WikiSection)
│       └── 📄 UserDTO (WikiPage — skeleton)
├── 📦 auth-service (WikiSection)
└── 📦 order-service (WikiSection)
```

### 跨视角引用

**WIKI_REFERENCES 边是 WikiPage 之间的直接关系，与树视角无关。** 无论在哪个视角浏览，都能看到同样的引用链接。

```
WikiPage("UserController") --WIKI_REFERENCES(type="calls")--> WikiPage("UserService")
WikiPage("UserController") --WIKI_REFERENCES(type="cross_repo")--> WikiPage("OrderAPI")

# 以上引用在两个视角中都可见，Agent 沿引用边自由跳转不受视角限制
```

对 Agent 而言，**整个 Wiki 就是一个连通的有向图**，`WIKI_REFERENCES` 边是图的边，WikiPage 是图的节点。树结构只是前端展示的组织方式。

## 交叉引用自动生成

基于图谱中的已有关系自动推断 `WIKI_REFERENCES` 边：

| 代码图谱关系 | Wiki 引用类型 | 说明 |
|------------|-------------|------|
| `CALLS` | `calls` | A 调用 B → A 的 wiki 引用 B 的 wiki |
| `CROSS_REPO_CALLS` | `cross_repo` | 跨仓库调用 |
| `INHERITS` | `inherits` | 继承关系 → 父子类互相引用 |
| `IMPORTS` | `imports` | 导入关系 |
| `BusinessFlow` 步骤 | `business_flow` | 业务流中涉及的实体互相引用 |
| RAG 语义相似性 | `semantic` | 语义相关页面推荐（置信度较低） |

```python
class WikiReferenceGenerator:
    async def generate_references(
        self,
        business_id: str,
        wiki_pages: list[WikiPageNode],
    ) -> list[WikiReferencesEdge]:
        """基于代码图谱关系自动生成 Wiki 页面间的交叉引用"""
        ...
```

引用在 LLM 生成 wiki 内容时自动插入为 `[[path]]` 标记，前端渲染为可点击链接。每个页面同时展示"引用了"（出向）和"被引用于"（入向反向链接）。

## 跨仓库 BusinessDomainPlanner

将 `BusinessDomainPlanner.classify()` 的输入从单仓库 modules 扩展为 business 下所有仓库的 modules：

```python
class CrossRepoBusinessDomainPlanner:
    async def classify(
        self,
        business_id: str,
        all_modules: dict[str, list[GraphNode]],  # repo -> modules
    ) -> dict[str, list[tuple[str, str]]]:
        """
        输入: business 下所有仓库的模块列表
        输出: {业务领域: [(repository, module_uid), ...]}
        """
        ...
```

两遍过程：
1. **第一遍（无需 LLM）**: 扫描所有仓库的代码结构，收集模块元数据（名称、business_summary、docstring、跨仓库调用关系）
2. **第二遍（需要 LLM）**: 将模块映射到业务领域。LLM prompt 显式要求输出 `__infrastructure__` 兜底分类

**大规模场景的分批策略：** 当模块总数超过 100 时，先按仓库分组独立分类（每组一次 LLM 调用），然后用一次合并调用将各仓库的分类结果统一到全局业务领域。避免单次 LLM 输入超过上下文窗口。

## 前端展示设计

### 三栏式布局

```
┌──────────────────┬───────────────────────────────────┬──────────────────┐
│  左侧：树状导航    │  中间：页面内容                      │  右侧：引用面板    │
│                  │                                   │                  │
│ [业务视角][代码视角]│  面包屑: 用户管理 > 注册流程 > UC     │  引用了:           │
│ ──────────────── │  🏠 user-service  ● 百科级           │  → UserService   │
│ ▼ 用户管理        │  ─────────────────────────────────  │  → UserDTO       │
│   ▼ 用户注册流程  │                                     │  → OrderAPI (跨仓)│
│     ● UC (当前)   │  # UserController                  │  ──────────────  │
│     ○ UserService│  ## 概述                            │  被引用于:        │
│     ○ SmsService │  处理用户注册的 HTTP 请求,            │  ← GatewayFilter │
│   ▶ 用户认证机制  │  依赖 [[UserService]] 完成...        │  ← UserTest      │
│ ▶ 订单处理       │  ## 核心方法                         │                  │
│ ▶ 基础设施       │  ## 调用关系图 (Mermaid)              │                  │
│                  │  ## 代码引用                         │                  │
│ 🔍 搜索...       │  ## 探索问题                         │                  │
└──────────────────┴───────────────────────────────────┴──────────────────┘
```

关键交互：
- **视角切换**: 顶部 Tab 切换业务域树/代码结构树，页面内容不变，左侧树结构重新组织
- **引用点击**: content 中的 `[[path]]` 渲染为超链接，点击跳转，左侧树自动展开高亮
- **引用面板**: 显示出向引用和入向引用（反向链接），跨仓库引用特殊标记
- **面包屑**: 根据当前视角显示不同路径

### 搜索体验

搜索结果带上足够的上下文：

```
🔍 搜索: "密码加密"

📄 PasswordEncoder                                          core ⭐
📍 用户管理 > 用户认证机制
🏠 auth-service
"...使用 BCrypt 算法对用户密码进行加密存储..."
🔗 引用: 5 | 被引用: 8
────────────────────────────────────────────────────────────────
📄 用户注册流程 - 流程时序图                                  领域概述
📍 用户管理 > 用户注册流程
🏠 跨仓库 (user-service, auth-service)
"...步骤3: 调用 PasswordEncoder 对密码进行加密..."
🔗 引用: 7 | 被引用: 3
```

每条结果包含：页面标题 + 重要度标签、业务域路径（面包屑）、来源仓库、匹配片段（高亮）、引用统计。

搜索过滤器：按仓库、按业务领域、按重要度层级（只看 core）、按页面类型（领域概述 / 代码实体 / 业务流）。

## Wiki 导出与 Git 推送

### 导出目录结构

WikiSection 映射为目录，WikiPage 映射为 `.md` 文件，交叉引用转换为标准 markdown 相对链接：

```
wiki/
├── README.md                        # Wiki 首页（业务线概览）
├── _index/                          # 索引目录
│   ├── by-domain.md                 # 业务域树形索引（带链接）
│   ├── by-repository.md             # 仓库结构索引（带链接）
│   └── cross-references.md          # 交叉引用全局地图
├── 用户管理/                         # 业务领域目录
│   ├── README.md                    # 领域概述
│   ├── 用户注册流程/
│   │   ├── README.md                # 流程概述 + 时序图
│   │   ├── UserController.md
│   │   ├── UserService.md
│   │   └── SmsService.md
│   └── 用户认证机制/
│       ├── README.md
│       └── TokenProvider.md
├── 订单处理/
│   └── ...
└── 基础设施/
    └── ...
```

### 交叉引用转换

| 内部存储 | 导出格式（标准 Markdown） | 导出格式（Obsidian） |
|---------|------------------------|---------------------|
| `[[/用户管理/UserService]]` | `[UserService](./UserService.md)` | `[[用户管理/UserService]]` |
| `[[/订单处理/OrderService]]` | `[OrderService](../../订单处理/OrderService.md)` | `[[订单处理/OrderService]]` |

标准 Markdown 相对链接在 GitHub/GitLab 仓库中可直接浏览和跳转。

### 四种导出格式

| 格式 | 适用场景 | 特殊处理 |
|------|---------|---------|
| **ZIP** | 一次性下载分享 | 标准 markdown + 相对链接 |
| **Git 推送** | 持续自动化同步 | 增量 commit + 追溯信息 |
| **Obsidian vault** | 本地知识图谱浏览 | 保留 `[[wikilink]]` + `.obsidian/` 配置 |
| **MkDocs** | 部署为静态文档站 | 生成 `mkdocs.yml` 导航配置 |

### Git 推送流程

```
代码仓库 push
  → webhook → KBS 索引更新
  → 受影响 WikiPage 重新生成
  → WikiExporter.export_to_filesystem()
    ├── [[path]] → 相对 markdown 链接
    ├── 生成 _index/ 索引文件
    └── 跳过未变更的页面
  → GitPublisher.publish()
    ├── git add (仅变更文件)
    ├── git commit -m "docs(wiki): update UserController,
    │        UserService (triggered by user-service@abc1234)"
    └── git push origin main
```

commit message 包含追溯信息：
- `docs(wiki): update 用户管理/UserController, UserService (triggered by user-service@abc1234)` — 增量更新
- `docs(wiki): add 订单处理/领域概述 (new domain detected)` — 新增领域
- `docs(wiki): full regeneration for business 'xxx-platform'` — 全量重建

### 同步策略：单向推送 + 人工标注回流

初期采用**单向推送**（FalkorDB → Git），支持人工标注回流：

1. KBS 自动推送 → Git 仓库中的 `UserController.md`
2. 用户可在 Git 仓库中创建 `UserController.annotations.md`（人工标注文件）
3. KBS 推送前检查是否有新的 `.annotations.md` 文件，拉取并合并到 `WikiPage.manual_sections`
4. 下次 wiki 重新生成时，LLM 上下文包含 `manual_sections`，人工知识被保留

自动生成内容和人工标注分文件存储，避免合并冲突。

### 导出 API

```
POST /api/v1/wiki/export
{
  "format": "git" | "zip" | "obsidian" | "mkdocs",
  "view_type": "business_domain" | "code_structure" | "both",

  "git_config": {
    "remote_url": "git@gitlab.com:team/wiki.git",
    "branch": "main",
    "commit_message_prefix": "docs(wiki):"
  },

  "repositories": ["user-service", "auth-service"],  // null = 全部
  "domains": ["用户管理"],                             // null = 全部
  "min_tier": "standard"                              // 跳过 skeleton 级别
}
```

## Agent MCP 工具设计

| 工具名 | 功能 | 返回内容 |
|-------|------|---------|
| `wiki_get_tree` | 获取树结构概览 | 轻量级树（标题+path+子节点数），不含 content |
| `wiki_get_page` | 获取单页内容 | content + 引用列表 + 被引用列表 + 面包屑路径 |
| `wiki_search` | 语义搜索 | 匹配页面 + 业务域路径 + 摘要 + 引用统计 |
| `wiki_get_related` | 获取关联页面 | 所有 WIKI_REFERENCES 的目标，按 relation_type 分组 |
| `wiki_get_domain_overview` | 获取业务领域概述 | 领域概述页 + 涉及的仓库和模块列表 |

Agent 典型工作流：

```
Agent 任务: "在用户注册时增加邮箱验证"

1. wiki_search("用户注册流程")
   → 找到 "/用户管理/用户注册流程/流程时序图"

2. wiki_get_page("/用户管理/用户注册流程/流程时序图")
   → 理解完整注册链路: UserController → UserService → SmsService
   → 发现引用: [[UserService]], [[SmsService]], [[NotificationConfig]]

3. wiki_get_page("/用户管理/user-service/UserService")
   → 理解 register() 方法的实现细节和调用的下游服务

4. wiki_get_related("/用户管理/user-service/UserService")
   → 发现 notification-service 已有邮件发送能力

5. Agent 完全理解业务上下文, 精准实施修改
```

## 质量保障机制

### Wiki 覆盖率报告

```python
class WikiCoverageAnalyzer:
    async def analyze(self, business_id: str) -> CoverageReport:
        """
        扫描所有 core/standard 重要度的实体,
        检查哪些还没有 wiki 页面或只有 skeleton 级别。
        """
        ...

@dataclass
class CoverageReport:
    total_entities: int
    covered_entities: int           # 有 wiki 的实体数
    core_coverage: float            # core 实体的覆盖率
    stale_pages: list[str]          # 代码变了但 wiki 没更新的页面
    knowledge_gaps: list[str]       # 高调用度但文档薄弱的实体
```

API: `GET /api/v1/wiki/coverage-report`

### 探索问题自动生成

每个 Wiki 页面底部自动生成 3-5 个探索问题：
- 基于调用关系: "UserController 为什么直接调用了 CacheService 而不经过 UserService？"
- 基于业务流: "用户注册失败后的补偿逻辑在哪里实现？"
- 基于架构: "此模块的 7 个调用方中，有 3 个来自非本领域，是否存在过度耦合？"

### 过时检测

当代码实体的 commit_sha 与 WikiPage 生成时的 commit_sha 不一致时，标记页面为"可能过时"。前端显示提示："此页面的源代码已更新，文档可能不是最新的。"

## 配置

```env
# === Phase 0: Wiki 元模型 ===
WIKI__TREE_ENABLED=true                     # 启用树状结构
WIKI__DUAL_VIEW_ENABLED=true                # 启用双视角导航
WIKI__CROSS_REFERENCE_ENABLED=true          # 启用交叉引用自动生成
WIKI__CROSS_REFERENCE_MIN_CONFIDENCE=0.5    # 语义引用的最低置信度

# === Phase 4: 跨仓库业务级 Wiki ===
WIKI__CROSS_REPO_DOMAIN_ENABLED=false       # 启用跨仓库 BusinessDomainPlanner
WIKI__KNOWLEDGE_INJECTION_ENABLED=true      # 启用人工知识注入

# === 导出 / Git 推送 ===
WIKI__GIT_PUBLISH_ENABLED=false
WIKI__GIT_PUBLISH_MODE=incremental          # full | incremental
WIKI__GIT_PUBLISH_TRIGGER=on_wiki_update    # on_wiki_update | scheduled | manual
WIKI__GIT_PUBLISH_SCHEDULE=0 2 * * *        # cron (仅 scheduled 模式)
WIKI__GIT_REMOTE_URL=
WIKI__GIT_BRANCH=main
WIKI__GIT_AUTHOR_NAME=KBS Wiki Bot
WIKI__GIT_AUTHOR_EMAIL=wiki-bot@company.com
WIKI__GIT_TOKEN=
WIKI__EXPORT_DEFAULT_VIEW=business_domain   # 默认导出视角
WIKI__EXPORT_MIN_TIER=standard              # 默认最低导出层级
WIKI__EXPORT_DIR_NAMING=original            # original(保留原文) | slug(ASCII slug)

# === 质量保障 ===
WIKI__COVERAGE_REPORT_ENABLED=true
WIKI__STALE_DETECTION_ENABLED=true
WIKI__SUGGESTED_QUESTIONS_ENABLED=true
```

## 现有数据迁移策略

引入树状结构后，现有 WikiPage 节点需要迁移：

1. **自动创建 WikiSpace**: 为每个 business 创建一个 WikiSpace 根节点
2. **按仓库创建 WikiSection**: 为每个已有 wiki 的 repository 创建一个 WikiSection（view_type="code_structure"）
3. **挂载现有 WikiPage**: 将现有 WikiPage 通过 `HAS_CHILD` 边挂载到对应仓库的 WikiSection 下
4. **补充 path 属性**: 为每个 WikiPage 生成 path（格式: `/{repository}/{entity_name}`）
5. **补充 version**: 所有现有页面 version 设为 1

迁移脚本在 Phase 0 实施时执行，作为一次性操作。迁移后 `WIKI__TREE_ENABLED=false` 可以退回平坦列表行为。

## 测试策略

- **单元测试**: WikiTreeBuilder（树构建/path 生成/冲突解决）、WikiReferenceGenerator（引用推断/去重）、WikiExporter（格式转换/链接转换）、GitPublisher（增量检测/commit 生成）、WikiCoverageAnalyzer（覆盖率计算/过时检测）
- **集成测试**: 对多仓库已索引项目触发业务级 wiki 生成，验证树结构完整性、交叉引用正确性、导出文件可浏览性
- **端到端测试**: 代码变更 → webhook → 增量 wiki 更新 → Git 推送 → 验证 commit 内容
- **质量验证**: 人工审阅跨仓库领域概述页，对比增强前后的业务理解准确度

## 内存影响

在原提案估算基础上：

- WikiSpace 节点：每个 business 1 个，可忽略
- WikiSection 节点：约 `业务领域数 × 仓库数` 个，估计 ~100-500 个，约 ~1 MB
- HAS_CHILD 边：约等于 WikiSection + WikiPage 总数，约 ~50 KB
- WIKI_REFERENCES 边：约等于代码图谱中 CALLS + IMPORTS 边数的子集，估计 ~10,000 条，约 ~5 MB
- WikiPage 新增属性（path, version, manual_sections 等）：约 ~2 MB
- **总计新增约 ~10 MB**，在 FalkorDB 1.50 GB 基础上影响可忽略

## 实施阶段（在现有 Phase 1-3 基础上扩展）

### Phase 0: Wiki 元模型重设（~2 天）

在 Phase 1 之前执行，奠定树状结构基础。

- 引入 WikiSpace、WikiSection 节点类型
- WikiPage 新增 `path`、`version`、`manual_sections`、`repositories` 属性
- 引入 `HAS_CHILD` 边（带 `view_type`）和 `WIKI_REFERENCES` 边
- 修改现有 `WikiStore` 支持树状 CRUD
- 新增树结构 API: `GET /wiki/tree?view=business_domain`

### Phase 1-3: 按原提案执行（~8 天）

代码感知层、RAG 检索层、百科分层生成按 [wiki-enhancement-design](./2026-04-24-wiki-enhancement-design.md) 执行，但在以下地方整合 Phase 0 的元模型：

- `WikiComposer` 生成内容时自动插入 `[[path]]` 交叉引用
- `WikiDataCollector` 写入 WikiPage 时同时创建 `HAS_CHILD` 边
- `BusinessDomainPlanner` 创建 WikiSection 节点并建立树结构

### Phase 4: 跨仓库业务级 Wiki（~4 天）

- 实现 `CrossRepoBusinessDomainPlanner`
- 实现 `WikiReferenceGenerator` 自动交叉引用生成
- 实现 `WikiTreeBuilder` 全局树构建
- 实现跨仓库领域概述页生成
- 前端双视角导航 + 引用面板

### Phase 5: 导出与 Git 推送（~3 天）

- 实现 `WikiExporter` 四种导出格式
- 实现 `GitPublisher` 增量推送
- 实现人工标注回流（`.annotations.md`）
- 导出 API + 定时推送调度

### Phase 6: 质量保障（~2 天）

- 实现 `WikiCoverageAnalyzer` 覆盖率报告
- 实现过时检测
- 实现探索问题自动生成
- 前端覆盖率仪表盘

## 错误处理原则

继承原提案的可选降级策略，新增：

- **交叉引用生成失败**: 页面仍可独立展示，缺少引用不阻断
- **跨仓库分类失败**: 降级为按仓库独立组织（现有行为）
- **Git 推送失败**: 记录错误日志，不影响 wiki 生成流程，下次推送时自动重试
- **Obsidian/MkDocs 导出失败**: 降级为纯 markdown 文件导出

## 向后兼容

- 现有 WikiPage API 保持兼容，新增字段为可选
- `WIKI__TREE_ENABLED=false` 时完全退回平坦列表行为
- 现有 `scope="repo"` 参数继续支持单仓库 wiki 生成
- 新增 `scope="business"` 支持业务级全量 wiki 生成

## 建议改进（不在本提案强制范围内）

以下改进建议来自竞品分析和审阅，可在后续迭代中考虑：

1. **ImportanceScorer 增强**: 在原提案的结构评分基础上，引入 git log 变更频率、测试覆盖率等因素（需额外数据源）
2. **Wiki 版本历史 UI**: 前端支持查看页面的历史版本和 diff（类似 Git blame）
3. **语言覆盖扩展**: 参考 CRG 的 23 种语言支持，优先扩展 Rust、C#、Kotlin 等
4. **MCP Workflow Prompts**: 参考 CRG 的 5 个预设工作流，为 wiki 场景提供 `wiki_onboard`（新人入职引导）、`wiki_review`（架构评审引导）等组合工作流

## Git 推送安全实践

- Git token 通过环境变量或 secrets manager 注入，禁止硬编码
- 推送目标仓库应使用专用 bot 账号，权限仅限 wiki 分支的写入
- 支持 SSH key 和 HTTPS token 两种认证方式
- 推送失败时记录错误日志并通过告警通道通知（如 Hubble），不静默吞掉

## 与原提案（Phase 1-3）的关系

本提案是原提案的**上层扩展**，不修改原提案的核心组件设计。关系如下：

```
本提案 (Phase 0, 4-6)
  ├── Phase 0: 数据模型基础 (在 Phase 1 之前)
  ├── Phase 1-3: 按原提案执行 (代码感知 + RAG + 百科分层)
  ├── Phase 4: 跨仓库 + 交叉引用 (在 Phase 3 之后)
  ├── Phase 5: 导出 + Git 推送
  └── Phase 6: 质量保障
```

Phase 0 必须在 Phase 1 之前完成（元模型是基础），其余 Phase 可以独立实施。
