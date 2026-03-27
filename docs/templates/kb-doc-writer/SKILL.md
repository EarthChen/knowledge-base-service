---
name: kb-doc-writer
description: 基于知识库编写/更新项目文档，确保文档内容与真实代码一致。手动激活。
---

# KB Doc Writer

基于知识库（Knowledge Base）为项目编写或更新技术文档。通过 MCP 工具查询真实代码定义，杜绝文档中的臆造引用。

## 前提条件

- 项目已被知识库索引（`GET /api/v1/repositories` 可查到）
- Cursor MCP 已配置 `knowledge-base` 连接（`.cursor/mcp.json`）

## 工作流

### Step 1: 查询服务全貌

获取项目的索引统计，了解代码规模和结构：

```
rag_graph(query_type="graph_stats")
```

如有多仓库，确认当前仓库名：

```
rag_query(query="<项目名>", k=1, entity_type="all")
```

### Step 2: 获取接口与核心类列表

列出关键文件中的代码实体：

```
rag_graph(query_type="file_entities", file="src/main/java/.../controller/XxxController.java")
rag_graph(query_type="class_methods", name="XxxService")
```

对于需要了解继承关系的场景：

```
rag_graph(query_type="inheritance_tree", name="BaseService")
```

### Step 3: 获取调用关系

追踪核心方法的调用链，理解业务流程：

```
rag_graph(query_type="call_chain", name="handleRequest", depth=3, direction="downstream")
```

查看谁调用了某个公共方法（影响范围分析）：

```
rag_graph(query_type="call_chain", name="saveOrder", depth=2, direction="upstream")
```

### Step 4: 搜索已有文档

避免重复编写，检查是否已有相关文档：

```
rag_query(query="<功能关键词> 文档", k=5, entity_type="document")
```

如果已有文档，基于现有内容更新而非重写。

### Step 5: 生成/更新文档

基于 Step 1-4 的查询结果编写文档。遵循以下规范：

- **文档结构**遵循 code-review-bot `doc-maintenance` Skill 定义的标准（8 维度 + 规模自适应拆分）
- **代码引用**必须来自 KB 查询结果，不得凭记忆编写类名、方法签名
- **流程图**使用 Mermaid 语法，数据来自 `call_chain` 图查询
- **配置表格**从代码中 Grep 获取，用 KB 确认字段含义

### Step 6: 交叉验证

文档编写完成后，验证其中每个关键引用：

1. 提取文档中提到的所有类名、方法名
2. 对每个名称执行 `rag_query` 确认在代码中真实存在
3. 对签名有疑问的，用 `rag_graph(find_entity)` 获取精确定义
4. 修正任何不匹配的引用

### Step 7: 索引新文档

将新编写/更新的文档索引到知识库：

```
rag_index(directory="<项目路径>", mode="incremental")
```

## 与 code-review-bot doc-maintenance 的分工

| 场景 | 执行者 | 触发方式 |
|------|--------|----------|
| PR 触发的增量文档维护 | code-review-bot | 自动（PR webhook） |
| 开发者主动编写/大改文档 | **本 Skill** | 手动激活 |
| 新项目文档初始化 | **本 Skill** | 手动激活 |

## 降级策略

KB 不可用时（MCP 连接失败/超时），退回到 Grep + Read 方式获取代码信息，不阻塞文档编写。但完成后应在 KB 恢复时重新执行 Step 6 验证。
