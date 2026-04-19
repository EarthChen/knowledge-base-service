# 用户指南

## 这个系统是什么？

**Knowledge Base Service** 将你的代码仓库索引为**图**（函数、类、模块、调用关系、导入关系等）和**语义向量**，支持自然语言搜索、关系探索，以及（可选的）Wiki 风格文档生成。**Web 仪表盘**提供无需编写代码的搜索和探索界面。

## 仪表盘导览

启动服务后（`uv run uvicorn main:app …`），打开根 URL（默认 **http://localhost:8100**）。

| 区域 | 功能说明 |
|------|----------|
| **搜索** | 执行**混合**自然语言查询（底层调用 `POST /hybrid`）：结果融合关键词 + 语义 + **BM25 全文搜索**三路 RRF 融合与图扩展上下文。可按仓库或语言过滤。支持**分页**和按分数/名称/路径**排序**。 |
| **深度搜索** | 多步骤 **LLM** 推理调查（需 `LLM__ENABLED` 及可用 Provider）。使用 SSE 端点时在界面流式展示各阶段。 |
| **图 / 探索器** | 探索实体及其邻域（Dagre 布局、实体详情）。支持**渐进式加载**：双击节点展开邻居，支持撤销。侧栏包含 **Blast Radius 面板**（变更影响分析）和**社区发现面板**（代码模块自动聚类）。对应 `rag_graph`、`/graph/explore`、`/graph/expand`、`/graph/blast-radius`、`/graph/communities` API。 |
| **文件浏览器** | 路由 **`/files`**：分栏浏览目录与源码（**prism-react-renderer** 语法高亮）；实体徽章可跳转图探索、搜索或 Wiki。使用 **`/api/v1/files/*`** API，**须先选择已索引仓库**。详见下文。 |
| **仓库** | 查看已索引仓库、统计信息及状态；"索引中有什么"的入口。 |
| **索引** | 触发**全量**或**增量**索引任务；远程仓库需配置 Git 并通过 API 传入 `git_url`。 |
| **Wiki** | 浏览和搜索**生成的** Wiki 页面（需启用 Wiki 管道且已生成页面）。 |
| **架构** | 查看按层和端点分类的架构分解（丰富化已分类服务时可用）。 |
| **同步 / 设置** | 定时 git pull + 重新索引、Webhook、LLM/Provider 设置。 |

界面是 **React + Vite** SPA：重型图表和图形代码仅在打开对应路由时加载。

## 文件浏览器

在导航进入 **文件浏览器**，先选仓库，再按树形结构打开源文件。右侧面板展示高亮源码；解析出的函数/类等实体在行旁显示，可从快捷入口前往图谱、混合搜索或 Wiki。**须已完成该仓库索引**，且服务端能解析到检出路径（与同仓库其它能力一致）。

通过 **MCP**，Agent 可用 **`get_file_content`** 读取完整文件或行范围（避免检索片段长度上限），或 **`rag_graph`** 的 **`nl_query`** 以自然语言问图（需启用 LLM）。详见 [MCP-INTEGRATION.md](MCP-INTEGRATION.md)。

## 索引你的第一个仓库

### 方式 A：本地目录（API）

使用 **Editor** Token。调用：

`POST /api/v1/index`，JSON 请求体如下：

```json
{
  "directory": "/absolute/path/to/repo",
  "repository": "my-repo",
  "mode": "full"
}
```

返回 **`task_id`**。轮询 `GET /api/v1/index/tasks/{task_id}` 直到状态为 `completed` 或 `failed`。

### 方式 B：Git URL

按需设置 `GIT__GITLAB_URL` / `GIT__GITLAB_TOKEN`（或 SSH），然后：

```json
{
  "git_url": "https://gitlab.example.com/group/myproject.git",
  "branch": "main",
  "repository": "myproject",
  "mode": "full"
}
```

服务会在 `GIT__CLONE_BASE_PATH` 下克隆并索引检出内容。

### 方式 C：MCP Agent

使用 **`rag_index`** 工具（需 **Editor** 角色），字段与 HTTP 请求体相同。

## 搜索技巧

- 当知道具体标识符时，在查询中使用**具体的**类名/函数名；混合栈通过 RRF 提升**关键词**和 **BM25** 匹配权重。
- 使用 `repository` 和 `language` 缩小**范围**以减少噪声。
- 对于**大文件**，启用子块行为（参见 `HYBRID_SEARCH__USE_CHILD_CHUNKS` 和 MCP `use_child_chunks`）以获取更细粒度的命中。
- 对于**架构类问题**，使用架构视图或 MCP `search_architecture`（`mode: layers` 或 `endpoints`）。

已废弃的全局搜索端点已移除；使用 **`POST /api/v1/hybrid`** 并配合 `entity_type` 查询业务实体（`flow`、`concept`）。

## 与 AI Agent 集成（MCP）

1. **Token** — 创建 `viewer` 或 `editor` Token（`tokens.yaml` 或 `API_TOKENS`）。
2. **列出工具** — `GET /api/v1/mcp/tools`，带 `Authorization: Bearer <token>`。
3. **调用** — `POST /api/v1/mcp/tool`，请求体 `{"tool_name":"rag_query","arguments":{...}}`。
4. **租户** — 使用多租户图时，通过无绑定 Admin Token 传入 `X-Business-Id: your-tenant`。

完整工具列表和 Schema：[MCP-INTEGRATION.md](MCP-INTEGRATION.md)。

## 认证快速参考

| 模式 | 行为 |
|------|------|
| 未配置 Token | 开放访问（不适合生产环境）；`REQUIRE_AUTH` 在无 Token 时强制启动失败 |
| `tokens.yaml` / 环境变量 Token | 受保护路由需 Bearer；角色控制 Viewer / Editor / Admin 路由访问 |

检查你的角色：`GET /api/v1/auth/me`。
