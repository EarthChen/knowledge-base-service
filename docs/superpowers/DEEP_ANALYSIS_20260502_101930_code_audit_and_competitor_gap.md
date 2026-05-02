# 代码审计与竞品差距分析报告

**日期**: 2026-05-02  
**范围**: 后端（FastAPI + FalkorDB）、前端（React + Vite + TypeScript）全量代码审计 + DeepWiki / CodeWiki / LLMWiki 竞品对标  
**方法**: 静态代码分析 + 公开资料竞品调研  
**状态**: 三轮代码修复 + 一轮架构重构，共完成 38 项改进。待修复项已清零。

---

## 一、当前代码质量评价

### 1.1 后端亮点

| 方面 | 评价 |
|------|------|
| 安全闸门 | `_enforce_production_security` 阻断无认证的生产启动 |
| 认证体系 | RBAC 角色认证；MCP 工具通过 `@mcp_tool` 装饰器声明最低角色 |
| SPA 安全 | `resolve()` + `is_relative_to()` 路径穿越防护 |
| Cypher 安全 | 扩展正则 + 查询前缀白名单双重拦截写操作 |
| 并发控制 | Wiki 任务锁使用 UUID token + Redis Lua CAS 解锁 |
| 日志 | structlog 支持 console/JSON 双模式 |
| 资源管理 | lifespan 分解为 `_init_security` / `_init_core_services` / `_init_wiki_and_lint` / `_shutdown_all` |
| 服务容器 | `AppContainer` dataclass 替代全局可变单例，`kb_state.py` 作为过渡 shim |
| MCP 注册 | `@mcp_tool` 装饰器 + `collect_tools` 自动发现，无需维护大字典 |
| 健康检查 | FalkorDB 下游检查，失败返回 `degraded` |
| 限流 | Rate limiter 含 bucket eviction 防内存泄漏 |
| 分页 | 通用 `PaginationParams`/`PaginatedResponse` 工具 |
| 代码复用 | `store/fqn_utils.py` 统一 FQN 解析，消除重复正则 |
| 类型安全 | `WikiService` 使用 Protocol 跨模块类型注解 |

### 1.2 前端亮点

| 方面 | 评价 |
|------|------|
| 目录组织 | `api/`、`pages/`、`components/`、`hooks/`、`contexts/` 分层清晰 |
| 状态管理 | TanStack Query + Context + URL Search Params |
| 路由 | 路由级 `lazy()` 懒加载 |
| TypeScript | `strict` 模式，几乎无 `any` |
| XSS 防护 | `rehype-sanitize` + 自定义 schema + 专门测试覆盖 |
| SSE 资源管理 | 全部使用 AbortController + unmount 测试覆盖 |
| Bundle 优化 | Vite `manualChunks` 拆分 6 组 vendor；CodeBlock lazy 加载 |
| 工具统一 | `utils/wikiPath.ts` 统一 Wiki 路径编码 |
| 页面测试 | Overview 和 Wiki 页面冒烟测试 |
| 无障碍 | 移动端侧栏 `role="dialog"` + `aria-modal` + ESC 关闭 |

---

## 二、竞品分析

### 2.1 竞品概览

| 项目 | Stars | 定位 | 技术栈 |
|------|-------|------|--------|
| **DeepWiki** (AsyncFuncAI/deepwiki-open) | ~16,046 | 仓库级 AI Wiki 生成器 + Ask + DeepResearch | Next.js + FastAPI + FAISS |
| **CodeWiki** (FSoft-AI4Code/CodeWiki) | ~915 | 学术级大规模仓库文档自动生成 | Tree-sitter + OpenAI 兼容 LLM + CLI |
| **LLM Wiki** (lucasastorian/llmwiki) | ~764 | 个人/研究文档沉积 + Claude MCP | Next.js + FastAPI + SQLite FTS5 |

### 2.2 八维度对比

| 维度 | DeepWiki | CodeWiki | LLM Wiki | **knowledge-base-service** |
|------|----------|----------|----------|---------------------------|
| **索引能力** | 仓库文件级 ingest + 嵌入；无细粒度 AST 符号索引 | **8 语言** Tree-sitter；层级模块拆分；支持超大仓库 | 通用文档索引（PDF/Office/MD）；非代码 AST | **Tree-sitter 代码索引**（5 语言）；配置文件节点；git diff 增量；跨文件 import 解析 |
| **知识图谱** | 无持久化图 DB | 内部依赖/调用图（进程内，非持久化服务） | Wiki 双向链接/引用；非代码调用图 | **FalkorDB 属性图**；图扩展检索；Blast Radius；社区发现；NL→Cypher |
| **AI/LLM** | 多提供商 + 多嵌入；Ask / DeepResearch | 多云 LLM；主用于生成文档 | Claude + MCP 读写 Wiki | OpenAI 兼容 LLM：深度搜索、丰富化、问答、NL→Cypher |
| **Wiki 生成** | **强项**：交互式 Wiki UI + 图解 + 缓存 | **强项**：Holistic 仓库文档与图示产物 | LLM 持续撰写 Markdown Wiki | Markdown Wiki 生成 + 浏览 + 搜索 + MCP 工具 |
| **搜索能力** | FAISS 向量检索驱动 RAG | 侧重文档可读性，非通用检索 | FTS5 全文；hosted 有 PGroonga | **三路 RRF** + 可选重排序 + 父子块 + 跨仓聚合 |
| **协作交互** | Web UI + 聊天；Discord 社区 | CLI；GitHub Pages | 人编辑 + Claude MCP | Dashboard（搜索/图探索/文件树）；RBAC |
| **导出集成** | 自托管 Wiki | `./docs/` + 静态站点 | MCP + Markdown 仓库即产物 | HTTP API + MCP（~22 工具）；Obsidian/MkDocs/Git 导出 |
| **部署运维** | Docker Compose；低门槛 | pip CLI；批量任务形态 | 本地 Python + Node；可选托管 | Python 3.12 + FalkorDB + 嵌入推理；**运维复杂度最高** |

### 2.3 我们的优势

1. **代码语义 + 图一体化**：符号级索引 + FalkorDB 图查询 + Blast Radius + 社区发现 + NL→Cypher
2. **工程级检索栈**：BM25 + 稠密向量 + RRF + 可选 rerank + 图扩展 + 跨仓检索
3. **增量与仓库运维**：git diff 增量索引、仪表盘管理，适合组织级 KB
4. **Agent 集成面**：MCP + REST 双通道、RBAC 角色认证、~22 个 MCP 工具

### 2.4 我们的劣势

1. **语言覆盖面不足**：仅 5 语言，CodeWiki 覆盖 8 语言
2. **产品化体验与社区声量**：DeepWiki 16K+ Star，产品化体验更吸睛
3. **通用文档场景弱**：不支持 PDF/Office 等非代码资料
4. **部署门槛高**：依赖 FalkorDB + 嵌入推理栈
5. **学术背书缺失**：无论文/评测基准加持

### 2.5 竞品追赶路线

| 优先级 | 方向 | 说明 |
|--------|------|------|
| P1 | 扩展语言支持 | 补充 C/C++/C#/Kotlin/Rust 的 Tree-sitter 查询规则 |
| P1 | 降低部署门槛 | 提供 Docker Compose 一键部署；支持 SQLite 轻量模式 |
| P2 | 增强 Wiki 生成体验 | 学习 DeepWiki 的交互式图解生成体验 |
| P2 | 通用文档 ingest | 支持 PDF/Office/HTML 等非代码文档 |
| P3 | 社区建设 | 完善 README、Demo、Discord/社区频道 |
| P3 | 学术材料 | 发布技术 Blog 或白皮书 |

---

## 附录：竞品仓库链接

- DeepWiki: https://github.com/AsyncFuncAI/deepwiki-open
- CodeWiki: https://github.com/FSoft-AI4Code/CodeWiki
- LLM Wiki: https://github.com/lucasastorian/llmwiki
- LLM Wiki spec (Karpathy gist): https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
