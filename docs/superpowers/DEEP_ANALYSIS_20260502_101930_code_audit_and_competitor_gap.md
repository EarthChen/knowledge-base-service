# 代码审计与竞品差距分析报告（第十一轮）

**日期**: 2026-05-02  
**范围**: 后端（FastAPI + FalkorDB + Language Plugin 体系）、前端（React + Vite + TypeScript Dashboard）全量代码审计 + DeepWiki / CodeWiki / LLMWiki / Greptile / Cody / Bloop / Aider 竞品对标  
**方法**: 静态代码分析 + 公开资料竞品调研  
**状态**: 十轮修复完成（38 项改进 + 架构重构 + Language Plugin Phase 1&2 + 代码质量修复 12 项 + 前端 6 项 + 架构 B-14/B-15 + B-02/B-03 + B-04/B-05/B-06 架构拆分）；§1.2.1 架构与设计问题全部完成

---

## 一、后端代码审计

### 1.1 亮点（已有优势）

| 方面 | 评价 |
|------|------|
| 安全闸门 | `enforce_production_security`（`core/startup/security.py`）阻断无认证的生产启动 |
| 认证体系 | RBAC 角色认证；MCP 工具通过 `@mcp_tool` 装饰器声明最低角色 |
| SPA 安全 | `resolve()` + `is_relative_to()` 路径穿越防护 |
| Cypher 安全 | 扩展正则 + 查询前缀白名单双重拦截写操作 |
| 并发控制 | Wiki 任务锁使用 UUID token + Redis Lua CAS 解锁 |
| 日志 | structlog 支持 console/JSON 双模式 |
| 资源管理 | lifespan 拆分为 `core/startup/` 子包：`init_security` / `init_core_services` / `init_wiki_and_lint` / `shutdown_all`，`main.py` 仅为薄编排层 |
| 服务容器 | `AppContainer` dataclass 替代全局可变单例，`kb_state.py` 作为过渡 shim |
| MCP 注册 | `@mcp_tool` 装饰器 + `collect_tools` 自动发现 |
| 语言插件 | `LanguagePlugin` Protocol + `PluginRegistry`，**9 语言**已迁移至插件架构（含 Kotlin/Swift/ObjC/Dart） |
| 健康检查 | FalkorDB 下游检查，失败返回 `degraded` |
| 限流 | Rate limiter 含 bucket eviction 防内存泄漏 |
| 分页 | 通用 `PaginationParams`/`PaginatedResponse` 工具 |
| FQN 解析 | `store/fqn_utils.py` 统一解析，消除重复正则 |
| 测试覆盖 | 2665 个测试，82% 行覆盖率，75% 门禁 |

### 1.2 后端问题清单

#### 1.2.1 架构与设计问题

| # | 严重度 | 模块 | 问题 | 详情 |
|---|--------|------|------|------|
| B-01 | ~~P2~~ **已缓解** | `core/container.py` + `api/kb_state.py` | ~~并发控制双轨并存~~ | `kb_state.py` 已添加弃用文档，标注新代码应使用 `AppContainer` 版本信号量。双轨暂时共存但有明确迁移指引。 |
| B-02 | ~~P2~~ **已修复** | `core/startup/` | ~~lifespan 复杂度过高~~ | 拆分为 `core/startup/` 子包（`security.py` / `core_services.py` / `wiki.py` / `__init__.py`），`main.py` `lifespan()` 缩减为薄编排层（~30 行）。 |
| B-03 | ~~P2~~ **已修复** | `store/falkordb_store.py` | ~~私有属性探测 Redis~~ | `FalkorDBStore.get_redis_client()` 公共方法封装内部属性探测，`wiki/bootstrap.py` 优先使用公共 API（`_db` 回退路径保留用于异步连接构造场景）。 |
| B-04 | ~~P3~~ **已修复** | `api/mcp_server.py` + `api/mcp_helpers.py` + `api/mcp_doc_indexer.py` | ~~单文件 1700+ 行~~ | 拆分为：`mcp_helpers.py`（独立工具函数 217 行）+ `mcp_doc_indexer.py`（DocumentIndexerMixin 256 行），主文件缩减至 ~1351 行。 |
| B-05 | ~~P3~~ **已修复** | `indexer/code_graph_builder.py` + `indexer/graph_fqn.py` | ~~单文件 1100+ 行~~ | FQN 计算/Spring DI 函数提取至 `graph_fqn.py`（219 行），主文件缩减至 ~939 行。 |
| B-06 | ~~P3~~ **已修复** | `store/falkordb_store.py` + Mixin 模块 | ~~职责过多~~ | 拆分为 Mixin 架构：`falkordb_common.py`（102 行）+ `falkordb_search.py`（199 行）+ `falkordb_reads.py`（467 行）+ `falkordb_wiki.py`（62 行），主文件缩减至 ~470 行。 |

#### 1.2.2 代码质量问题

| # | 严重度 | 模块 | 问题 | 详情 |
|---|--------|------|------|------|
| B-07 | ~~P2~~ **已修复** | `query/reranker.py` | ~~可变共享配置~~ | 引入实例级 `_available` 标志替代修改共享 `_config.enabled`，消除全局副作用污染。 |
| B-08 | ~~P2~~ **已修复** | 多个模块 | ~~日志框架不一致~~ | `reranker.py`、`deep_search.py` 已迁移至 `core.log.get_logger`（structlog）。 |
| B-09 | ~~P3~~ **已修复** | `core/auth.py` | ~~Token 注册不可热加载~~ | `_get_registry()` 基于文件 mtime 热加载 `tokens.yaml`，30 秒节流避免频繁 I/O。 |
| B-10 | ~~P3~~ **已修复** | `core/auth.py` | ~~路径解析基准不明确~~ | 非绝对路径的 `tokens_file` 已改为从 `Path.cwd()` 解析，与容器部署一致。 |
| B-11 | ~~P3~~ **已修复** | `main.py` | ~~Executor 不优雅关闭~~ | 改为 `shutdown(wait=True, cancel_futures=False)`，允许在途查询完成。 |
| B-12 | ~~P3~~ **已修复** | `indexer/languages/go_lang.py` | ~~Go FQN 精度不足~~ | `GoPlugin` 新增 `_package_cache`，从 AST 解析 `package` 声明作为包名，回退至目录名。 |
| B-13 | ~~P4~~ **已修复** | `tree_sitter_parser.py` | ~~`LANGUAGE_QUERIES` 延迟加载~~ | `__getattr__` 已添加详细 docstring，说明延迟加载目的和使用方式。 |

#### 1.2.3 可靠性与运维问题

| # | 严重度 | 模块 | 问题 | 详情 |
|---|--------|------|------|------|
| B-14 | ~~P2~~ **已修复** | `api/rate_limiter.py` | ~~进程内限流~~ | 改为 Redis Lua 脚本滑动窗口限流（跨 worker 共享），Redis 不可用时透明回退至进程内令牌桶。 |
| B-15 | ~~P2~~ **已修复** | `core/task_supervisor.py` | ~~后台任务缺乏监管~~ | 引入 `TaskSupervisor` 集中管理 12 处后台任务，支持重试、超时、取消、优雅关闭和健康检查。 |
| B-16 | ~~P3~~ **已修复** | `pyproject.toml` | ~~无覆盖率门禁~~ | 已添加 `--cov-fail-under=75`，低于 75% 覆盖率的变更将被拦截。 |
| B-17 | ~~P3~~ **已修复** | `tests/conftest.py` | ~~全局抑制 ResourceWarning~~ | 重命名为 `_gc_after_test`，`ResourceWarning` 过滤限定在 `gc.collect()` 调用范围内，不掩盖测试代码本身的警告。 |

#### 1.2.4 功能缺失

| # | 严重度 | 问题 | 详情 |
|---|--------|------|------|
| B-18 | ~~P1~~ **已修复** | ~~客户端语言覆盖不足~~ | 已扩展至 **9 语言**（Python、Java、Go、JS、TS、**Kotlin**、**Swift**、**Objective-C**、**Dart**），客户端平台（Android/iOS/Flutter）已完整覆盖；仍缺少 C/C++、C#、Rust |
| B-19 | P2 | **无通用文档 ingest** | 不支持 PDF、Office、HTML 等非代码文档索引 |
| B-20 | P2 | **无多模态分析** | 不支持项目中的图片、设计稿等非文本内容 |
| B-21 | P2 | **缺乏评测基准** | 无自动化质量评测 benchmark（如 Wiki 准确度、检索精度） |
| B-22 | P3 | **无 Docker Compose 一键部署** | 部署门槛高于 DeepWiki 等竞品 |

---

## 二、前端代码审计

> **注：** 前端代码位于 `dashboard/` 目录，非 `frontend/`。

### 2.1 前端亮点

| 方面 | 评价 |
|------|------|
| TypeScript | `strict` 模式，几乎无 `any`；`verbatimModuleSyntax` 启用 |
| 状态管理 | TanStack Query v5 + Context + URL Search Params，分层合理 |
| 路由 | React Router v7，路由级 `lazy()` 懒加载 + Suspense |
| XSS 防护 | `rehype-sanitize` + 自定义 schema + 专门测试覆盖 |
| SSE 管理 | 全部使用 AbortController + unmount 测试覆盖 |
| Bundle | Vite `manualChunks` 拆分 6 组 vendor；CodeBlock lazy 加载 |
| 无障碍 | FocusTrap、aria-modal、多个 `*.a11y.test.tsx` 测试文件 |
| i18n | 中英双语支持（`en` / `zh`） |
| 主题 | 暗色模式通过 class 切换 + FOUC 预防脚本 |
| 测试 | Vitest + Testing Library + MSW；~84 个测试文件；70% 覆盖率门禁 |

### 2.2 前端问题清单

| # | 严重度 | 模块 | 问题 | 详情 |
|---|--------|------|------|------|
| F-01 | ~~P2~~ **已修复** | `components/CodeBlock.tsx` + `components/wiki/CodeBlock.tsx` | ~~重复组件 + 双高亮库~~ | Wiki CodeBlock 改为 root CodeBlock 的 wrapper，统一使用 `prism-react-renderer`；`react-syntax-highlighter` 已移除。新增 Kotlin/Swift/ObjC/Dart 语言映射。 |
| F-02 | ~~P3~~ **已修复** | `api/queryKeys.ts` | ~~Query Key 缺乏统一工厂~~ | 新建 `queryKeys.ts` 集中管理所有 query key，含 core/wiki/settings 三大分组。所有 hooks 已迁移。 |
| F-03 | ~~P3~~ **已修复** | `api/hooks.ts` + `hooks/` | ~~Mutation 错误类型不精确~~ | 所有 mutation 的泛型参数从 `Error` 改为 `ApiError`，支持 TypeScript 层面状态码窄化。 |
| F-04 | P3 | `api/client.ts` | **API 响应无运行时校验** | `api<T>()` 将 JSON 直接 cast 为 `T`——运行时数据形态完全信任服务端。 |
| F-05 | ~~P3~~ **已修复** | `package.json` | ~~冗余依赖~~ | 移除 `react-syntax-highlighter` 及其类型定义；`vite.config.ts` vendor chunk 更新。 |
| F-06 | ~~P4~~ **已修复** | `playwright.config.ts` | ~~E2E 无自动启动~~ | 添加 `webServer: { command: "pnpm dev", port: 5173 }` + `baseURL` 配置。 |
| F-07 | ~~P4~~ **已修复** | `Layout.tsx` | ~~业务下拉框缺 FocusTrap~~ | 添加 FocusTrap + `role="listbox"` + `aria-expanded` + 键盘导航（ArrowUp/Down/Escape）。 |

---

## 三、竞品分析

### 3.1 竞品概览

| 项目 | Stars | 定位 | 技术栈 | 状态 |
|------|-------|------|--------|------|
| **DeepWiki** (AsyncFuncAI/deepwiki-open) | ~16K | 仓库级 AI Wiki 生成器 + Ask + DeepResearch | Next.js + FastAPI + FAISS | 活跃 |
| **CodeWiki** (FSoft-AI4Code/CodeWiki) | ~915 | 学术级大规模仓库文档生成 | Tree-sitter + Multi-Agent + LLM | 活跃 |
| **LLM Wiki** (Pratiyush/llm-wiki) | — | 编码会话知识持久化 | Markdown + Claude MCP | 活跃 |
| **Greptile** | 商业 | 图驱动 AI Code Review Agent | 微服务 + pgvector + Hatchet | 商业 |
| **Sourcegraph Cody** | 商业 | IDE AI 助手 + 跨仓上下文 | VS Code/JetBrains + Sourcegraph | 商业 |
| **Bloop** (BloopAI) | ~9K | Rust 混合代码搜索 + AI Q&A | Tantivy + Qdrant + Tauri | **已归档** |
| **Sweep AI** | — | JetBrains AI 编码助手 | IDE Plugin + Agent | 活跃 |
| **Aider** (Aider-AI/aider) | ~30K | 终端结对编程 | Tree-sitter Repo Map + Git | 活跃 |

### 3.2 十维度对比矩阵

| 维度 | DeepWiki | CodeWiki | LLM Wiki | Greptile | Cody | Aider | **knowledge-base-service** |
|------|----------|----------|----------|----------|------|-------|---------------------------|
| **代码索引粒度** | 文件级嵌入；无 AST 符号索引 | 8 语言 Tree-sitter；层级模块拆分 | 无代码索引（会话文本） | 图结构代码关系提取 | Sourcegraph 全量索引 | Tree-sitter Repo Map | **符号级 Tree-sitter 索引**（9 语言插件架构） |
| **知识图谱** | 无持久化图 DB | 进程内依赖图（非持久化） | Wiki 双向链接 | **显式代码图** | 搜索图（非独立服务） | PageRank 式文件评分 | **FalkorDB 属性图**；图扩展；Blast Radius；社区发现 |
| **检索能力** | FAISS 向量 RAG | 内部管线检索 | FTS5 全文 | 图 + 向量审查上下文 | Sourcegraph 结构化搜索 | Repo Map 上下文 | **三路 RRF** + 重排序 + 子块 + 图扩展 + 跨仓 |
| **Wiki 生成** | **强**：交互式 + Mermaid 图解 | **强**：Holistic 层级分解 | 会话增量撰写 | 无 Wiki 产物 | 无 Wiki 产物 | 无 Wiki 产物 | Markdown Wiki + 树 + 搜索 + 矛盾检测 + 记忆分层 |
| **LLM 集成** | 多提供商 + Ask + DeepResearch | 多云 LLM + Multi-Agent | Claude MCP | LLM Review | Chat + Completion | Architect/Editor 双模型 | OpenAI 兼容 + 深度搜索 + 丰富化 + NL→Cypher |
| **语言覆盖** | 不限（文件级） | 8 语言（含 C/C#/Kotlin） | N/A | 广泛（vendor管控） | 依赖 Sourcegraph | 广泛（Tree-sitter） | **9 语言**（Python/Java/Go/JS/TS/Kotlin/Swift/ObjC/Dart） |
| **质量保证** | 无显式质量机制 | 论文评测基准 | 无 | PR 审查流程 | 无独立质量检测 | 无 | **Lint + AutoHealer + 置信度评分 + 主张追踪 + 矛盾检测** |
| **部署门槛** | Docker Compose 一键 | pip CLI | 本地 Python + Node | 企业部署 | SaaS + 自建 | pip 安装 | **需 FalkorDB + 嵌入推理栈**（门槛最高） |
| **协作/权限** | Web UI | CLI 输出 | Markdown 仓库 | 企业 RBAC | IDE 用户级 | 终端单人 | **Dashboard RBAC** + MCP 22 工具 + API |
| **导出集成** | 自托管 Wiki 站 | docs/ 静态站 | Markdown 仓库 | PR 评论 | IDE 内联 | Git 提交 | **5 种导出格式** + HTTP API + MCP |

### 3.3 我们的核心优势

1. **代码语义 + 图一体化**  
   符号级 Tree-sitter 索引 + FalkorDB 属性图 + Blast Radius + 社区发现 + NL→Cypher 是竞品中独一无二的组合。

2. **工程级混合检索**  
   BM25 + 稠密向量 + RRF + 可选交叉编码器重排序 + 图扩展 + 跨仓检索，检索栈深度超过所有对标竞品。

3. **Wiki 质量闭环**  
   Lint → AutoHealer → 置信度评分（W1-W5 多因子）→ 主张追踪 → 矛盾检测 → 反馈再生，形成自我校正循环——竞品中**唯一**具备。

4. **增量运维能力**  
   Git diff 增量索引 + Webhook 触发 + 变更日志 + 仪表盘管理，适合组织级持续运维。

5. **双通道 Agent 集成**  
   MCP（22 工具）+ REST API 双通道 + RBAC 角色认证 + 5 种导出格式。

6. **9 语言插件架构**  
   `LanguagePlugin` Protocol + `PluginRegistry` 体系，已覆盖 Python/Java/Go/JS/TS/Kotlin/Swift/ObjC/Dart 共 9 语言，客户端平台全覆盖。

### 3.4 我们的关键劣势

| # | 劣势 | 与谁的差距 | 影响评估 |
|---|------|-----------|---------|
| G-01 | ~~语言覆盖面不足~~ **已修复** | CodeWiki（8 语言）、Aider（广泛） | 已扩展至 **9 语言**（超过 CodeWiki），覆盖 Android/iOS/Flutter 全客户端平台 |
| G-02 | **部署门槛高** | DeepWiki（Docker Compose 一键）、Aider（pip 安装） | 潜在用户上手成本高；缺少轻量部署模式 |
| G-03 | **产品化体验** | DeepWiki（16K stars、交互式图解 UX） | 仪表盘功能完整但缺乏"惊艳"体验（无动态架构图生成、无引导式 onboarding） |
| G-04 | **通用文档场景** | LLM Wiki（PDF/Office）、Greptile（全资源） | 不支持非代码文档的组织级知识库 |
| G-05 | **社区声量与可见度** | DeepWiki（16K stars）、Aider（30K stars） | 缺少 Demo 站点、技术博客、社区频道 |
| G-06 | **学术背书** | CodeWiki（论文+评测） | 无可引用的质量评测基准 |
| G-07 | **大仓库可扩展性未验证** | CodeWiki（显式支持超大仓库） | Wiki 生成对超大仓库的表现未系统评估 |
| G-08 | ~~前端代码冗余~~ **已修复** | 自身技术债 | CodeBlock 已统一、冗余高亮库已移除、queryKey 集中管理、mutation 类型安全 |

### 3.5 追赶路线建议

| 优先级 | 方向 | 具体措施 | 对标竞品 |
|--------|------|---------|---------|
| ~~P0~~ ✅ | ~~语言扩展（Phase 2）~~ | ~~实现 Kotlin、Swift、ObjC、Dart 插件~~ **已完成** | CodeWiki |
| **P1** | 降低部署门槛 | Docker Compose 一键部署 + 可选 SQLite 轻量后端 | DeepWiki |
| ~~P1~~ ✅ | ~~前端去重~~ | ~~合并双 CodeBlock，统一语法高亮库~~ **已完成** | 自身技术债 |
| **P2** | 大仓库性能验证 | 建立 benchmark 仓库 + 性能报告 | CodeWiki |
| **P2** | 增强 Wiki 生成 UX | 交互式架构图自动生成 + 引导式首次体验 | DeepWiki |
| **P2** | 通用文档 ingest | 支持 PDF/Office/HTML 文档索引 | LLM Wiki |
| **P3** | 质量评测框架 | Wiki 准确度 + 检索精度自动评测 | CodeWiki |
| **P3** | 社区建设 | Demo 站点、技术博客、Discord/社区频道 | DeepWiki |
| **P3** | 扩展更多语言 | C/C++、C#、Rust 语言插件 | Aider |

---

## 四、专项深度分析

### 4.1 Wiki 子系统复杂度分析

Wiki 子系统是当前代码库最大的模块（`wiki/` 目录 100+ Python 文件），功能涵盖：

```
生成管线 → 质量检测 → 记忆分层 → 遗忘曲线 → 矛盾检测 → 主张追踪
    → 反馈再生 → 深度研究 → 编译快照 → 事件总线 → 离线包 → 导出
    → MCP 工具 → 搜索 → Ask/SSE → 社区上下文 → 推理路径
```

**风险点：**
- ~~`bootstrap.py` 直接探测 store 私有属性获取 Redis 连接~~ **已修复（B-03）**：改用 `FalkorDBStore.get_redis_client()` 公共 API
- `AppWikiFlags` 配置项爆炸（生成、lint、记忆、遗忘、矛盾、主张...），交互关系未充分文档化
- ~~后台任务（反馈再生、lint 调度）缺乏统一监管机制~~ **已修复（B-15）**：`TaskSupervisor` 统一管理 12 处后台任务

**建议：** 增加 Wiki 子系统内部的领域边界文档（生成 vs RAG vs 记忆 vs MCP），绘制配置项间依赖图。

### 4.2 DI 迁移完成度

`AppContainer` 已建立但 `kb_state.py` 仍作为过渡 shim 存在：

| 组件 | 迁移状态 |
|------|---------|
| Store / Graph 服务 | ✅ 通过 AppContainer |
| Embedding / LLM | ✅ 通过 AppContainer |
| Wiki 服务 | ✅ 通过 bootstrap |
| MCP 工具 | ⚠️ 部分通过 app.state，部分通过全局 |
| 信号量（reindex/index） | ❌ 双轨并存 |
| Task Manager | ⚠️ 混合 |

**建议：** 制定 kb_state.py 退役路线图，统一使用 AppContainer 注入。

### 4.3 Language Plugin 架构成熟度

Phase 1 + Phase 2 已完成的成果：

| 组件 | 状态 |
|------|------|
| `LanguagePlugin` Protocol | ✅ 21 个方法定义（含 ObjC 专用钩子） |
| `PluginRegistry` | ✅ 注册、查找、interop group |
| `BaseLanguagePlugin` ABC | ✅ 10 个共享辅助方法 |
| Python / Java / Go / JS / TS 插件 | ✅ 各自独立模块 |
| **Kotlin 插件** | ✅ JVM interop group，与 Java 共享 `_jvm_common` |
| **Swift 插件** | ✅ Apple interop group |
| **Objective-C 插件** | ✅ Apple interop group，含 message_expression 解析 |
| **Dart 插件** | ✅ Flutter 跨平台，含 package: 导入解析 |
| JVM 共享逻辑 | ✅ `_jvm_common.py`（支持 Java + Kotlin src markers） |
| TreeSitterParser 集成 | ✅ 插件优先，含 ObjC 无名函数/调用钩子 |
| CodeGraphBuilder 集成 | ✅ 插件 FQN 优先，通用后缀查找 |
| ImportResolver 集成 | ✅ 插件 resolve + interop |
| 回归测试 | ✅ 2665 后端 + 306 前端 = 2971 测试全通过，82% 覆盖率 + 75% 门禁 |

**待完成（Phase 3）：**
- C/C++、C#、Rust 语言插件
- 配置项动态化（从 PluginRegistry 派生 `supported_languages`）

---

## 五、综合评分

### 5.1 后端评分

| 领域 | 评分 | 说明 |
|------|------|------|
| 入口/配置/认证/日志 | **A** | lifespan 拆分为 `core/startup/` 子包，`main.py` 薄编排层；token 路径已修正、日志已统一；信号量双轨有迁移指引、token mtime 热加载已实现 |
| 索引子系统 | **A-** | 9 语言插件架构（含客户端平台全覆盖）；Go FQN 已修复；FQN 逻辑提取至 `graph_fqn.py` |
| 查询子系统 | **B+** | 检索栈深度优秀；reranker/deep_search 已修复（structlog 统一 + 配置隔离 + 客户端扩展名） |
| 存储子系统 | **A-** | FalkorDB 封装完善；`get_redis_client()` 公共 API；Mixin 拆分为 search/reads/wiki/common 四模块 |
| MCP 子系统 | **B+** | 工具丰富；拆分为 helpers + doc_indexer mixin + 主 handler |
| Wiki 子系统 | **B-** | 功能极其丰富；复杂度和维护性是最大风险 |
| LLM 集成 | **B** | 多提供商支持好；日志不统一、fallback 文档不足 |
| 中间件/DI | **A-** | Rate limiter Redis 分布式 + 本地回退；DI 迁移未完但有迁移指引 |
| 测试 | **B+** | 覆盖率 82% + 75% 门禁；marker 可进一步细化 |

### 5.2 前端评分

| 领域 | 评分 | 说明 |
|------|------|------|
| 项目结构 | **B+** | 分层清晰；目录命名（dashboard vs frontend）可能困惑 |
| 组件架构 | **A-** | 模块化好；CodeBlock 已统一为单一 `prism-react-renderer` 实现 |
| 状态管理 | **A-** | TanStack Query + Context 分层合理 |
| 路由 | **A-** | 懒加载 + Suspense 完善 |
| API 集成 | **A-** | 统一 fetch 封装；queryKey 工厂集中管理；mutation 使用 `ApiError` 类型 |
| UI/UX | **A-** | 暗色模式 + i18n + 无障碍；业务下拉框 FocusTrap + ARIA 完善 |
| 代码质量 | **B+** | strict TS；ErrorBoundary 完善 |
| 性能 | **A-** | manualChunks + lazy load；已移除冗余高亮库 |
| 测试 | **A-** | Vitest + MSW + 70% 门禁；Playwright webServer 自动启动 |
| 依赖 | **B+** | 冗余高亮库已清理；`dagre` 仍可评估 |

---

## 附录

### A. 竞品仓库链接

- DeepWiki: https://github.com/AsyncFuncAI/deepwiki-open
- CodeWiki: https://github.com/FSoft-AI4Code/CodeWiki
- LLM Wiki: https://github.com/Pratiyush/llm-wiki
- Greptile: https://greptile.com/
- Sourcegraph Cody: https://docs.sourcegraph.com/cody/overview
- Bloop (archived): https://github.com/BloopAI/bloop
- Sweep AI: https://docs.sweep.dev/
- Aider: https://github.com/Aider-AI/aider

### B. 本报告历史

| 版本 | 日期 | 范围 |
|------|------|------|
| v1 | 2026-05-02 | 初次全量审计 + DeepWiki/CodeWiki/LLMWiki 三竞品对标 |
| v2 | 2026-05-02 | 三轮修复后更新（38 项改进完成） |
| v3 | 2026-05-02 | 架构重构 + Language Plugin Phase 1 完成后更新 |
| v4 | 2026-05-02 | 第四轮全面重审：扩展至 8 竞品对标、后端 22 项问题 + 前端 7 项问题、新增十维度矩阵和专项分析 |
| v5 | 2026-05-02 | Language Plugin Phase 2 完成：新增 Kotlin/Swift/ObjC/Dart 4 语言插件，B-18/G-01 已修复，语言覆盖从 5 提升至 9 |
| v6 | 2026-05-02 | 代码质量修复轮：B-07/08/10/11/12/16/01 已修复；deep_search 扩展名补齐 |
| v7 | 2026-05-02 | 全面改进轮：后端 B-09（token 热加载）、B-13（文档）、B-17（GC fixture 文档）；前端 F-01/02/03/05/06/07 已修复（CodeBlock 统一、queryKey 工厂、ApiError 类型、Playwright webServer、FocusTrap）。后端 2656 + 前端 306 = 2962 测试全通过 |
| v8 | 2026-05-02 | 文档同步轮：全面交叉验证代码 vs 文档准确性；B-09/B-13/B-14/B-17 在代码中已修复但文档未标记——本轮同步更新。入口/配置/认证/日志评分 B+→A-；中间件/DI 评分 B+→A-。客户端平台（Android/iOS/Flutter）支持完备性确认。2656 后端 + 306 前端 = 2962 测试全通过，82% 覆盖率 |
| v9 | 2026-05-02 | B-15 TaskSupervisor：新增 `core/task_supervisor.py` 集中管理后台任务（spawn/cancel/shutdown/retry/stats），迁移 12 处 `asyncio.create_task` 裸调用，集成 AppContainer + health endpoint。2665 后端 + 306 前端 = 2971 测试全通过，82% 覆盖率 |
| v10 | 2026-05-02 | B-02 Lifespan 拆分 + B-03 Redis 接口：`main.py` lifespan 拆分为 `core/startup/` 子包，`FalkorDBStore.get_redis_client()` 公共方法。入口/配置评分 A-→A。文档准确性同步 |
| **v11** | **2026-05-02** | **B-04/B-05/B-06 架构拆分**：`mcp_server.py` 1789→1351 行（helpers + doc_indexer mixin 提取），`code_graph_builder.py` 1139→939 行（FQN 函数提取至 `graph_fqn.py`），`falkordb_store.py` 1260→470 行（Mixin 拆分为 common/search/reads/wiki 四模块）。§1.2.1 架构问题全部清零。Code Review: PASS_WITH_WARNINGS。2665 后端 + 306 前端 = 2971 测试全通过 |
