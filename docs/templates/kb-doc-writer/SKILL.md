---
name: kb-doc-writer
description: 基于知识库编写/更新项目文档，确保文档内容与真实代码一致。手动激活。支持 MCP 和 Shell curl 双模式。
---

# KB Doc Writer

基于知识库（Knowledge Base）为项目编写或更新技术文档。通过查询真实代码定义，杜绝文档中的臆造引用。

## 环境适配

本 Skill 同时支持两种 KB 查询方式，Agent 根据运行环境自动选择：

| 环境 | 检测方式 | 查询方式 |
|------|----------|----------|
| Cursor IDE（MCP 可用） | Prompt 中**未**包含 `[KNOWLEDGE BASE - SHELL QUERY TOOLS]` | MCP 工具调用 |
| ACP Gateway / CI 环境 | Prompt 中包含 `[KNOWLEDGE BASE - SHELL QUERY TOOLS]` | Shell curl 命令 |

下文每个查询步骤同时提供两种写法，使用 `MCP:` 和 `Shell:` 标签区分。

## 前提条件

- 项目已被知识库索引（`GET /api/v1/repositories` 可查到）
- MCP 模式：Cursor MCP 已配置 `knowledge-base` 连接（`.cursor/mcp.json`）
- Shell 模式：Prompt 中已注入 KB curl 命令模板

## 工作流

### Step 1: 查询服务全貌

获取项目的索引统计，了解代码规模和结构：

**MCP:**
```
rag_graph(query_type="graph_stats")
```

**Shell:**
```bash
curl -s -X POST '{kb_url}/graph' \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer {api_token}' \
  -d '{"query_type": "graph_stats"}'
```

如有多仓库，确认当前仓库名：

**MCP:**
```
rag_query(query="<项目名>", k=1, entity_type="all")
```

**Shell:**
```bash
curl -s -X POST '{kb_url}/search' \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer {api_token}' \
  -d '{"query": "<项目名>", "k": 1, "entity_type": "all"}'
```

### Step 2: 获取接口与核心类列表

列出关键文件中的代码实体：

**MCP:**
```
rag_graph(query_type="file_entities", file="src/main/java/.../controller/XxxController.java")
rag_graph(query_type="class_methods", name="XxxService")
```

**Shell:**
```bash
curl -s -X POST '{kb_url}/graph' \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer {api_token}' \
  -d '{"query_type": "file_entities", "file": "src/main/java/.../controller/XxxController.java"}'

curl -s -X POST '{kb_url}/graph' \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer {api_token}' \
  -d '{"query_type": "class_methods", "name": "XxxService"}'
```

对于需要了解继承关系的场景：

**MCP:**
```
rag_graph(query_type="inheritance_tree", name="BaseService")
```

**Shell:**
```bash
curl -s -X POST '{kb_url}/graph' \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer {api_token}' \
  -d '{"query_type": "inheritance_tree", "name": "BaseService"}'
```

### Step 3: 获取调用关系

追踪核心方法的调用链，理解业务流程：

**MCP:**
```
rag_graph(query_type="call_chain", name="handleRequest", depth=3, direction="downstream")
```

**Shell:**
```bash
curl -s -X POST '{kb_url}/graph' \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer {api_token}' \
  -d '{"query_type": "call_chain", "name": "handleRequest", "depth": 3, "direction": "downstream"}'
```

查看谁调用了某个公共方法（影响范围分析）：

**MCP:**
```
rag_graph(query_type="call_chain", name="saveOrder", depth=2, direction="upstream")
```

**Shell:**
```bash
curl -s -X POST '{kb_url}/graph' \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer {api_token}' \
  -d '{"query_type": "call_chain", "name": "saveOrder", "depth": 2, "direction": "upstream"}'
```

### Step 4: 搜索已有文档

避免重复编写，检查是否已有相关文档：

**MCP:**
```
rag_query(query="<功能关键词> 文档", k=5, entity_type="document")
```

**Shell:**
```bash
curl -s -X POST '{kb_url}/search' \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer {api_token}' \
  -d '{"query": "<功能关键词> 文档", "k": 5, "entity_type": "document"}'
```

如果已有文档，基于现有内容更新而非重写。

### Step 5: 生成/更新文档

基于 Step 1-4 的查询结果编写文档。

#### 文档结构标准

推荐的项目文档结构（8 维度）：

```
project-root/
├── README.md                    # P0 项目概览: 功能描述、技术栈、快速开始
└── docs/
    ├── architecture.md          # P3 架构设计: 模块职责、数据流、技术选型 (含 Mermaid 图)
    ├── api.md                   # P1 API 参考: 接口定义、参数、返回值、错误码
    ├── database.md              # P2 数据库设计: ER图、表结构概览、分库分表策略
    ├── configuration.md         # P5 配置指南: 环境变量表、配置文件说明、默认值
    ├── business-flows.md        # P4 核心业务流程: 流程图、状态机、业务规则
    ├── deployment.md            # 部署指南: Docker/K8s、依赖服务、健康检查
    ├── development.md           # 开发指南: 本地环境搭建、测试运行、代码规范
    └── changelog.md             # 变更日志: Keep a Changelog 格式
```

#### 规模自适应拆分

当内容过多时，按以下规则拆分为目录：

| 维度 | 单文件阈值 | 拆分策略 |
|------|-----------|----------|
| API/RPC 接口 | ≤ 20 个方法 → `api.md` | 20-50 → 按可见性拆分（internal/external）；50+ → 按业务域拆分 `api/` |
| 配置项 | ≤ 30 项 → `configuration.md` | 30-80 → 静态/动态拆分；80+ → 按中间件类型拆分 `config/` |
| 业务流程 | ≤ 5 个流程 → `business-flows.md` | 5-15 → 按业务域拆分 `flows/`；15+ → 按业务域 + 子目录 |

#### 内容质量要求

- **代码引用**必须来自 KB 查询结果，不得凭记忆编写类名、方法签名
- **流程图**使用 Mermaid 语法，数据来自 `call_chain` 图查询
- **配置表格**从代码中 Grep 获取，用 KB 确认字段含义
- 代码示例必须使用项目实际使用的编程语言
- 架构图使用 Mermaid 语法
- 保持与项目现有文档相同的语言和风格

### Step 6: 交叉验证

文档编写完成后，验证其中每个关键引用：

1. 提取文档中提到的所有类名、方法名
2. 对每个名称执行语义搜索确认在代码中真实存在
3. 对签名有疑问的，用图查询 `find_entity` 获取精确定义
4. 修正任何不匹配的引用

**MCP:**
```
rag_query(query="<类名或方法名>", k=3, entity_type="function")
rag_graph(query_type="find_entity", name="<实体名>", entity_type="any")
```

**Shell:**
```bash
curl -s -X POST '{kb_url}/search' \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer {api_token}' \
  -d '{"query": "<类名或方法名>", "k": 3, "entity_type": "function"}'

curl -s -X POST '{kb_url}/graph' \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer {api_token}' \
  -d '{"query_type": "find_entity", "name": "<实体名>", "entity_type": "any"}'
```

### Step 7: 索引新文档

将新编写/更新的文档索引到知识库：

**MCP:**
```
rag_index(directory="<项目路径>", mode="incremental")
```

**Shell:**
```bash
curl -s -X POST '{kb_url}/../index' \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer {api_token}' \
  -d '{"directory": "<项目路径>", "mode": "incremental"}'
```

## 与 code-review-bot doc-maintenance 的分工

| 场景 | 执行者 | 触发方式 |
|------|--------|----------|
| PR 触发的增量文档维护 | code-review-bot | 自动（PR webhook） |
| 开发者主动编写/大改文档 | **本 Skill** | 手动激活 |
| 新项目文档初始化 | **本 Skill** | 手动激活 |

## 降级策略

KB 不可用时（MCP 连接失败/curl 超时），退回到 Grep + Read 方式获取代码信息，不阻塞文档编写。但完成后应在 KB 恢复时重新执行 Step 6 验证。
